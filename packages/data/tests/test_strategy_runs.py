"""Strategy runs: every generation is kept, and reads show each weekend's latest run.

Needs a throwaway Postgres (FORMATION_TEST_DATABASE_URL, see test_migrations.py).
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import exc as sa_exc

from formation_data import domain, flexibility, migrate, repositories, schema

pytestmark = pytest.mark.skipif(
    not os.environ.get("FORMATION_TEST_DATABASE_URL"),
    reason="FORMATION_TEST_DATABASE_URL not set",
)


@pytest.fixture
def conn(engine):
    migrate.upgrade()
    with engine.begin() as c:
        c.exec_driver_sql(
            "INSERT INTO circuits (circuit_id, country, track_length_km, num_corners, "
            "num_laps, sm_zones, jolpica_id, fastf1_location, lat, lon, timezone) VALUES "
            "('spa', 'BE', 7.0, 19, 44, 2, 'spa', 'Spa-Francorchamps', 0, 0, 'Europe/Brussels')"
        )
        yield c


def _weekend(conn, rnd: int) -> domain.RaceWeekend:
    repositories.upsert(
        conn,
        schema.race_weekends,
        [
            domain.RaceWeekend(
                circuit_id="spa",
                season=2026,
                round_number=rnd,
                event_name="Belgian Grand Prix",
                race_date=date(2026, 7, rnd),
                is_sprint=False,
            )
        ],
        ["season", "round_number"],
    )
    return repositories.get_race_weekend(conn, 2026, rnd)


def _strategy(label: str, *, base: bool = False, plausibility: float | None = None):
    compounds = label.split("->")
    stints = [
        domain.StrategyStint(
            strategy_id=0,
            stint_order=n,
            compound=c,
            pit_lap_window_start=20 * n,
            pit_lap_window_end=20 * n + 2,
        )
        for n, c in enumerate(compounds, start=1)
    ]
    strategy = domain.Strategy(
        is_base=base,
        num_stops=len(compounds) - 1,
        label=label,
        plausibility=plausibility,
        tier="Most likely" if plausibility else None,
    )
    return strategy, stints


def _sim_run(conn, weekend, phase, stats, *strategies, at=None) -> int:
    return repositories.insert_strategy_run(
        conn,
        domain.StrategyRun(
            race_weekend_id=weekend.id, source="sim", phase=phase, stats=stats, generated_at=at
        ),
        list(strategies),
    )


def _count(conn, table: str) -> int:
    return conn.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar()


def test_runs_are_kept_and_the_latest_one_is_shown(conn):
    weekend = _weekend(conn, 9)
    t0 = datetime(2026, 7, 6, tzinfo=UTC)
    prelim = _sim_run(
        conn,
        weekend,
        "prelim",
        {"race_stats": {"chaos_index_0to100": 10}},
        _strategy("MEDIUM->HARD", base=True, plausibility=0.6),
        _strategy("SOFT->HARD", plausibility=0.4),
        at=t0,
    )
    postquali = _sim_run(
        conn,
        weekend,
        "postquali",
        {"race_stats": {"chaos_index_0to100": 30}},
        _strategy("HARD->MEDIUM", base=True, plausibility=1.0),
        at=t0 + timedelta(days=5),
    )
    # A later historical run is its own source: it leaves the sim's runs alone.
    repositories.insert_strategy_run(
        conn,
        domain.StrategyRun(race_weekend_id=weekend.id, source="historical"),
        [_strategy("MEDIUM->HARD", base=True)],
    )

    sim = repositories.list_strategies_for_weekend(conn, 2026, 9, "sim")
    assert [(s.run_id, s.phase, s.label, [t.compound for t in s.stints]) for s in sim] == [
        (postquali, "postquali", "HARD->MEDIUM", ["HARD", "MEDIUM"])
    ]
    (hist,) = repositories.list_strategies_for_weekend(conn, 2026, 9, "historical")
    assert (hist.source, hist.phase, hist.label) == ("historical", None, "MEDIUM->HARD")
    stats = repositories.get_sim_race_stats(conn, 2026, 9)
    assert (stats.id, stats.phase, stats.stats["race_stats"]["chaos_index_0to100"]) == (
        postquali,
        "postquali",
        30,
    )
    # ...while prelim is still stored.
    assert (_count(conn, "strategy_runs"), _count(conn, "strategies")) == (3, 4)
    assert prelim < postquali


def test_deleting_a_run_takes_its_strategies_and_stints(conn):
    run_id = _sim_run(conn, _weekend(conn, 9), "prelim", {}, _strategy("SOFT->MEDIUM->HARD"))
    assert _count(conn, "strategy_stints") == 3
    conn.exec_driver_sql(f"DELETE FROM strategy_runs WHERE id = {run_id}")
    assert (_count(conn, "strategies"), _count(conn, "strategy_stints")) == (0, 0)


def test_a_sim_run_needs_a_phase(conn):
    weekend = _weekend(conn, 9)
    with pytest.raises(sa_exc.IntegrityError, match="source_phase"):
        with conn.begin_nested():
            _sim_run(conn, weekend, None, {})
    with pytest.raises(sa_exc.IntegrityError, match="source_phase"):
        with conn.begin_nested():
            repositories.insert_strategy_run(
                conn,
                domain.StrategyRun(race_weekend_id=weekend.id, source="historical", phase="prelim"),
                [],
            )


def test_postquali_is_due_until_a_postquali_run_exists(conn):
    weekend = _weekend(conn, 9)
    now = datetime(2026, 7, 8, 18, tzinfo=UTC)
    repositories.upsert(
        conn,
        schema.sessions,
        [
            domain.Session(
                race_weekend_id=weekend.id,
                kind=kind,
                session_order=order,
                name=name,
                start_time=start,
            )
            for order, kind, name, start in (
                (4, "quali", "Qualifying", now - timedelta(hours=3)),
                (5, "race", "Race", now + timedelta(hours=20)),
            )
        ],
        ["race_weekend_id", "kind"],
    )

    def due():
        return [w.round_number for w in repositories.weekends_postquali_due(conn, now)]

    _sim_run(conn, weekend, "prelim", {})
    assert due() == [9]
    _sim_run(conn, weekend, "postquali", {})
    assert due() == []


def test_season_ranks_read_each_weekends_current_run(conn):
    a, b = _weekend(conn, 9), _weekend(conn, 10)
    stops = {"1": 0.5, "2": 0.5}
    t0 = datetime(2026, 7, 6, tzinfo=UTC)
    # Weekend A's older run would rank it last on chaos; its current run ranks it first.
    _sim_run(conn, a, "prelim", {"race_stats": {"chaos_index_0to100": 5}}, at=t0)
    _sim_run(
        conn,
        a,
        "postquali",
        {"race_stats": {"chaos_index_0to100": 80, "stop_count_distribution": stops}},
        _strategy("MEDIUM->HARD", base=True, plausibility=0.7),
        _strategy("SOFT->HARD", plausibility=0.3),
        at=t0 + timedelta(days=1),
    )
    _sim_run(
        conn,
        b,
        "prelim",
        {"race_stats": {"chaos_index_0to100": 50, "stop_count_distribution": stops}},
        _strategy("MEDIUM->HARD", base=True, plausibility=1.0),
        at=t0,
    )
    assert repositories.chaos_rank(conn, 2026, 9) == flexibility.rank_of(80.0, [80.0, 50.0])
    expected = flexibility.flexibility_score(stops, [0.7, 0.3])
    field = [expected, flexibility.flexibility_score(stops, [1.0])]
    assert repositories.strategy_flexibility_rank(conn, 2026, 9) == flexibility.rank_of(
        expected, field
    )


def test_both_jobs_add_runs_without_touching_each_other(conn, monkeypatch):
    import formation_sim.api

    from formation_data.jobs.pre_race import sim_strategies, strategies

    weekend = _weekend(conn, 9)

    def fake_sim(mode, season, round_number, n_sims=None):
        return {
            "shown": [
                {"rank": 1, "compounds": ["MEDIUM", "HARD"], "n_stops": 1,
                 "pit_windows": [[18, 24]], "plausibility": 0.8, "tier": "Most likely"},
            ],
            "meta": {"mode": mode},
            "circuit_profile": {},
            "race_stats": {"chaos_index_0to100": 40},
        }

    monkeypatch.setattr(formation_sim.api, "simulate_race", fake_sim)
    groups = [{"label": "SOFT->HARD", "compounds": ["SOFT", "HARD"], "drivers": ["A", "B"],
               "stop_laps": [[15, 17]]}]
    monkeypatch.setattr(strategies, "_mine_most_recent_dry", lambda season, loc: (2025, groups))

    sim_strategies.run(conn, season=2026, round_number=9, mode="prelim")
    strategies.run(conn, season=2026, round_number=9)  # used to delete the sim's rows
    sim_strategies.run(conn, season=2026, round_number=9, mode="postquali")

    runs = conn.exec_driver_sql(
        "SELECT source, phase, stats->'meta'->>'mode' FROM strategy_runs "
        f"WHERE race_weekend_id = {weekend.id} ORDER BY id"
    ).all()
    assert [tuple(r) for r in runs] == [
        ("sim", "prelim", "prelim"),
        ("historical", None, None),
        ("sim", "postquali", "postquali"),
    ]
    (sim,) = repositories.list_strategies_for_weekend(conn, 2026, 9, "sim")
    assert (sim.phase, sim.label, sim.plausibility) == ("postquali", "MEDIUM->HARD", 0.8)
    (hist,) = repositories.list_strategies_for_weekend(conn, 2026, 9, "historical")
    assert (hist.label, hist.is_base, hist.stints[-1].pit_lap_window_end) == ("SOFT->HARD", True, 44)
