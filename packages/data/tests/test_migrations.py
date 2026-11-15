"""Migrations build exactly what schema.py declares, and adopt pre-Alembic databases safely.

The database tests need a throwaway Postgres: set FORMATION_TEST_DATABASE_URL to a
database whose name contains "test" (CI provides one). Its public schema is dropped and
recreated before each test. Without the variable they're skipped.

    docker exec formation_lap_db createdb -U formation formation_lap_test
    FORMATION_TEST_DATABASE_URL=postgresql+psycopg2://formation:formation@localhost:5432/formation_lap_test \\
        uv run pytest packages/data/tests/test_migrations.py
"""

from __future__ import annotations

import os
import re

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

from formation_data import migrate, schema

TEST_URL = os.environ.get("FORMATION_TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not TEST_URL, reason="FORMATION_TEST_DATABASE_URL not set")


def test_revisions_form_one_line_with_ids_matching_filenames():
    script = ScriptDirectory.from_config(migrate.config())
    assert len(script.get_heads()) == 1, "two revisions share a parent; merge or rebase one"
    revisions = list(script.walk_revisions())  # newest first
    for n, rev in enumerate(reversed(revisions), start=1):
        assert rev.revision == f"{n:04d}"
        assert re.match(rf"{rev.revision}_\w+\.py$", os.path.basename(rev.path))
    assert revisions[-1].revision == migrate.BASELINE_REVISION


def _tables(eng) -> set[str]:
    with eng.connect() as conn:
        return set(inspect(conn).get_table_names())


def _version(eng) -> str | None:
    with eng.connect() as conn:
        return migrate.current_revision(conn)


@needs_db
def test_upgrade_from_empty_matches_schema_py(engine):
    assert migrate.upgrade() == (None, migrate.head_revision())
    assert migrate.check() == []
    assert _tables(engine) == set(schema.metadata.tables) | {"alembic_version"}


@needs_db
def test_downgrade_to_base_and_back(engine):
    migrate.upgrade()
    migrate.downgrade("base")
    assert _tables(engine) == {"alembic_version"}
    migrate.upgrade()
    assert migrate.check() == []


@needs_db
def test_upgrade_is_a_no_op_when_current(engine):
    _, head = migrate.upgrade()
    assert migrate.upgrade() == (head, head)


@needs_db
def test_refuses_a_database_built_before_migrations(engine):
    schema.metadata.create_all(engine)
    with pytest.raises(migrate.MigrationError, match="before migrations"):
        migrate.upgrade()
    assert _version(engine) is None


# --- 0003: race history references race_weekends -------------------------------------


def _exec(eng, *statements: str) -> None:
    with eng.begin() as conn:
        for sql in statements:
            conn.exec_driver_sql(sql)


def _circuit(circuit_id: str, timezone: str | None = None) -> str:
    """A circuits row; pass `timezone` at 0006 and later, where it's required."""
    tz_col, tz_val = (", timezone", f", '{timezone}'") if timezone else ("", "")
    return (
        "INSERT INTO circuits (circuit_id, country, track_length_km, num_corners, num_laps, "
        f"sm_zones, jolpica_id, fastf1_location, lat, lon{tz_col}) VALUES "
        f"('{circuit_id}', 'X', 5.0, 10, 50, 2, '{circuit_id}', '{circuit_id}', 0, 0{tz_val})"
    )


def _weekend(circuit_id: str, season: int, rnd: int) -> str:
    return (
        "INSERT INTO race_weekends (circuit_id, season, round_number, event_name, race_date, "
        f"is_sprint) VALUES ('{circuit_id}', {season}, {rnd}, 'GP', '{season}-07-0{rnd % 9 + 1}', false)"
    )


@needs_db
def test_0003_points_history_at_the_right_weekend(engine):
    migrate.upgrade("0002")
    _exec(
        engine,
        _circuit("spielberg"),
        _circuit("singapore"),
        # a 2020 double-header, and a 2026 calendar whose stored round (16) lags the
        # official one the results were written under (17)
        _weekend("spielberg", 2020, 1),
        _weekend("spielberg", 2020, 2),
        _weekend("singapore", 2026, 16),
        "INSERT INTO race_results (circuit_id, season, round_number, position, driver_id, team) "
        "VALUES ('spielberg', 2020, 2, 1, 'hamilton', 'Mercedes'), "
        "('spielberg', 2020, 1, 1, 'bottas', 'Mercedes'), "
        "('singapore', 2026, 17, 1, 'norris', 'McLaren')",
        "INSERT INTO race_traces (circuit_id, season, round_number, trace) "
        "VALUES ('spielberg', 2020, 2, '{}')",
        "INSERT INTO race_overtakes (circuit_id, season, round_number, overtakes) "
        "VALUES ('singapore', 2026, 17, '{}')",
    )
    migrate.upgrade("0003")
    with engine.connect() as conn:
        winners = dict(
            conn.exec_driver_sql("""
                SELECT rw.season || ' R' || rw.round_number, rr.driver_id
                FROM race_results rr JOIN race_weekends rw ON rw.id = rr.race_weekend_id
            """).all()
        )
    assert winners == {"2020 R1": "bottas", "2020 R2": "hamilton", "2026 R16": "norris"}

    # ...and back: the copies come back from the weekend each row points at.
    migrate.downgrade("0002")
    with engine.connect() as conn:
        rows = conn.exec_driver_sql(
            "SELECT season, round_number, circuit_id, driver_id FROM race_results ORDER BY 1, 2"
        ).all()
    assert [tuple(r) for r in rows] == [
        (2020, 1, "spielberg", "bottas"),
        (2020, 2, "spielberg", "hamilton"),
        (2026, 16, "singapore", "norris"),
    ]


@needs_db
def test_0003_refuses_history_with_no_weekend(engine):
    migrate.upgrade("0002")
    _exec(
        engine,
        _circuit("monza"),
        _weekend("monza", 2026, 16),
        "INSERT INTO race_results (circuit_id, season, round_number, position, driver_id, team) "
        "VALUES ('monza', 2020, 8, 1, 'gasly', 'AlphaTauri')",
    )
    with pytest.raises(migrate.MigrationError, match="weekends refresh --season 2020"):
        migrate.upgrade()
    assert _version(engine) == "0002"
    assert "season" in {c["name"] for c in inspect(engine).get_columns("race_results")}


@needs_db
def test_resolve_race_weekend(engine):
    from formation_data import repositories

    migrate.upgrade()
    _exec(
        engine,
        _circuit("silverstone", "Europe/London"),
        _circuit("monza", "Europe/Rome"),
        _weekend("silverstone", 2020, 4),
        _weekend("silverstone", 2020, 5),
        _weekend("monza", 2026, 16),
    )
    with engine.connect() as conn:

        def resolve(circuit_id, season, rnd):
            return repositories.resolve_race_weekend(
                conn, season=season, circuit_id=circuit_id, round_number=rnd
            ).round_number

        assert resolve("silverstone", 2020, 5) == 5  # double-header: the round decides
        assert resolve("monza", 2026, 17) == 16  # one visit: a lagging round still matches
        with pytest.raises(repositories.RaceWeekendNotFound, match="none is round 6"):
            resolve("silverstone", 2020, 6)
        with pytest.raises(repositories.RaceWeekendNotFound, match="--season 2021"):
            resolve("monza", 2021, 14)


# --- 0004: drivers and teams --------------------------------------------------------


def _0004():
    """The 0004 revision module, for its frozen copy of the seeds."""
    script = ScriptDirectory.from_config(migrate.config())
    return script.get_revision("0004").module


def test_0004_snapshot_matches_the_seeds():
    """0004 inserts a frozen copy of the teams and drivers seeds; for the seasons it
    covers, the seeds must still say the same thing, or a fresh database and a seeded
    one would disagree."""
    from formation_data.jobs.static import drivers as static_drivers
    from formation_data.jobs.static import teams as static_teams

    m = _0004()
    assert {(t.team_id, t.name) for t in static_teams.TEAMS} >= set(m._TEAMS)
    seeded = {
        (t.team_id, t.season, t.name, t.jolpica_id, t.fastf1_name)
        for t in static_teams.TEAM_SEASONS
        if t.season <= 2026
    }
    assert seeded == set(m._TEAM_SEASONS)
    frozen = {d[0]: (d[2], d[3], d[4], d[5]) for d in m._DRIVERS}
    for d in static_drivers.DRIVERS:
        assert frozen.get(d.driver_id) == (d.given_name, d.family_name, d.code, d.nationality)


@needs_db
def test_0004_points_names_at_drivers_and_teams(engine):
    migrate.upgrade("0003")
    _exec(
        engine,
        _circuit("shanghai"),
        _circuit("spa"),
        _weekend("spa", 2020, 7),
        _weekend("spa", 2026, 13),
        "INSERT INTO race_results (race_weekend_id, position, driver_id, team) "
        "SELECT id, 1, 'verstappen', 'Red Bull' FROM race_weekends WHERE season = 2020",
        "INSERT INTO race_results (race_weekend_id, position, driver_id, team) "
        "SELECT id, 2, 'gasly', 'AlphaTauri' FROM race_weekends WHERE season = 2020",
        "INSERT INTO race_results (race_weekend_id, position, driver_id, team) "
        "SELECT id, 1, 'lindblad', 'RB F1 Team' FROM race_weekends WHERE season = 2026",
        "INSERT INTO standings (season, after_round, type, position, name, points) VALUES "
        "(2026, 13, 'driver', 1, 'Arvid Lindblad', 25), "
        "(2026, 13, 'constructor', 1, 'RB F1 Team', 25)",
        "INSERT INTO lap_records (circuit_id, driver, year, lap_time_seconds) VALUES "
        "('shanghai', 'Schumacher', 2004, 92.238), ('spa', 'Perez', 2024, 104.701)",
        "INSERT INTO drivers (driver_id, full_name, nationality, team, season) VALUES "
        "('lindblad', 'Arvid Lindblad', 'British', 'Racing Bulls', 2026)",
    )
    migrate.upgrade()
    assert migrate.check() == []

    def rows(sql):
        with engine.connect() as conn:
            return [tuple(r) for r in conn.exec_driver_sql(sql).all()]

    assert rows(
        "SELECT rw.season, rr.position, rr.driver_id, rr.team_id FROM race_results rr "
        "JOIN race_weekends rw ON rw.id = rr.race_weekend_id ORDER BY 1, 2"
    ) == [
        (2020, 1, "max_verstappen", "red_bull"),
        (2020, 2, "gasly", "racing_bulls"),
        (2026, 1, "arvid_lindblad", "racing_bulls"),
    ]
    assert rows("SELECT driver_id, position, points FROM driver_standings") == [
        ("arvid_lindblad", 1, 25.0)
    ]
    assert rows("SELECT team_id, position FROM constructor_standings") == [("racing_bulls", 1)]
    assert rows("SELECT circuit_id, driver_id FROM lap_records ORDER BY 1") == [
        ("shanghai", "michael_schumacher"),
        ("spa", "perez"),
    ]
    assert rows("SELECT driver_id, team_id, season, valid_from::text FROM seats") == [
        ("arvid_lindblad", "racing_bulls", 2026, "2026-01-01")
    ]

    # ...and back: names come back from the rows each reference points at.
    migrate.downgrade("0003")
    assert rows(
        "SELECT driver_id, team FROM race_results ORDER BY race_weekend_id, position"
    ) == [("verstappen", "Red Bull Racing"), ("gasly", "AlphaTauri"), ("lindblad", "Racing Bulls")]
    assert rows("SELECT type, name FROM standings ORDER BY 1") == [
        ("constructor", "Racing Bulls"),
        ("driver", "Arvid Lindblad"),
    ]
    assert rows("SELECT driver FROM lap_records ORDER BY circuit_id") == [
        ("Schumacher",),
        ("Pérez",),
    ]
    assert rows("SELECT driver_id, team, season FROM drivers") == [
        ("lindblad", "Racing Bulls", 2026)
    ]
    migrate.upgrade()
    assert migrate.check() == []


@needs_db
def test_0004_refuses_names_it_does_not_know(engine):
    migrate.upgrade("0003")
    _exec(
        engine,
        _circuit("monza"),
        _weekend("monza", 2020, 8),
        "INSERT INTO race_results (race_weekend_id, position, driver_id, team) "
        "SELECT id, 1, 'button', 'Brawn' FROM race_weekends",
    )
    with pytest.raises(migrate.MigrationError) as err:
        migrate.upgrade()
    assert "driver 'button'" in str(err.value) and "team 'Brawn'" in str(err.value)
    assert _version(engine) == "0003"
    assert "team" in {c["name"] for c in inspect(engine).get_columns("race_results")}


# --- 0005: strategy runs -------------------------------------------------------------


def _strategy_0004(weekend: str, source: str, phase: str | None, label: str, at: str) -> str:
    """A 0004-shaped strategies row (with one stint) for the weekend matching `weekend`."""
    phase_sql = f"'{phase}'" if phase else "NULL"
    return (
        "WITH s AS (INSERT INTO strategies (race_weekend_id, source, phase, is_base, "
        "num_stops, label, updated_at) "
        f"SELECT id, '{source}', {phase_sql}, true, 0, '{label}', '{at}' FROM race_weekends "
        f"WHERE {weekend} RETURNING id) "
        "INSERT INTO strategy_stints (strategy_id, stint_order, compound, "
        "pit_lap_window_start, pit_lap_window_end) SELECT id, 1, 'HARD', 44, 44 FROM s"
    )


@needs_db
def test_0005_moves_strategies_into_runs(engine):
    migrate.upgrade("0004")
    r9, r10 = "round_number = 9", "round_number = 10"
    _exec(
        engine,
        _circuit("spa"),
        _weekend("spa", 2026, 9),
        _weekend("spa", 2026, 10),
        _strategy_0004(r9, "historical", None, "MEDIUM->HARD", "2026-06-30 01:00+00"),
        _strategy_0004(r9, "historical", None, "SOFT->HARD", "2026-06-30 01:00+00"),
        _strategy_0004(r9, "sim", "postquali", "HARD->MEDIUM", "2026-07-07 03:00+00"),
        "INSERT INTO sim_race_stats (race_weekend_id, phase, generated_at, stats) "
        "SELECT id, 'postquali', '2026-07-07 03:00+00', '{\"x\": 1}' FROM race_weekends "
        f"WHERE {r9}",
        # sim strategies whose stats row is missing still make a run
        _strategy_0004(r10, "sim", "prelim", "MEDIUM->HARD", "2026-07-10 03:00+00"),
    )
    migrate.upgrade()
    assert migrate.check() == []

    def rows(sql):
        with engine.connect() as conn:
            return [tuple(r) for r in conn.exec_driver_sql(sql).all()]

    runs = (
        "SELECT rw.round_number, r.source, r.phase, r.stats->>'x', "
        "(SELECT count(*) FROM strategies s WHERE s.run_id = r.id) "
        "FROM {} r JOIN race_weekends rw ON rw.id = r.race_weekend_id ORDER BY 1, 2"
    )
    assert rows(runs.format("strategy_runs")) == [
        (9, "historical", None, None, 2),
        (9, "sim", "postquali", "1", 1),
        (10, "sim", "prelim", None, 1),
    ]
    assert rows("SELECT count(*) FROM strategy_stints") == [(4,)]

    # A newer run for weekend 9 becomes the current one; the older one stays stored.
    _exec(
        engine,
        "WITH r AS (INSERT INTO strategy_runs (race_weekend_id, source, phase, stats, "
        f"generated_at) SELECT id, 'sim', 'postquali', '{{\"x\": 2}}', '2026-07-08 00:00+00' "
        f"FROM race_weekends WHERE {r9} RETURNING id) "
        "INSERT INTO strategies (run_id, is_base, num_stops, label) "
        "SELECT id, true, 1, 'SOFT->HARD' FROM r",
    )
    assert rows(runs.format("current_strategy_runs")) == [
        (9, "historical", None, None, 2),
        (9, "sim", "postquali", "2", 1),
        (10, "sim", "prelim", None, 1),
    ]

    # ...and back: each weekend keeps its current run per source.
    migrate.downgrade("0004")
    assert rows(
        "SELECT rw.round_number, s.source, s.phase, s.label FROM strategies s "
        "JOIN race_weekends rw ON rw.id = s.race_weekend_id ORDER BY 1, 2, 4"
    ) == [
        (9, "historical", None, "MEDIUM->HARD"),
        (9, "historical", None, "SOFT->HARD"),
        (9, "sim", "postquali", "SOFT->HARD"),
        (10, "sim", "prelim", "MEDIUM->HARD"),
    ]
    assert rows("SELECT phase, stats->>'x' FROM sim_race_stats") == [("postquali", "2")]
    migrate.upgrade()
    assert migrate.check() == []


@needs_db
def test_0005_refuses_strategies_from_two_runs(engine):
    migrate.upgrade("0004")
    r9 = "round_number = 9"
    _exec(
        engine,
        _circuit("spa"),
        _weekend("spa", 2026, 9),
        _strategy_0004(r9, "sim", "prelim", "MEDIUM->HARD", "2026-07-07 03:00+00"),
        _strategy_0004(r9, "sim", "postquali", "SOFT->HARD", "2026-07-08 03:00+00"),
    )
    with pytest.raises(migrate.MigrationError, match="2026 R9: sim rows from more than one run"):
        migrate.upgrade()
    assert _version(engine) == "0004"
    assert "sim_race_stats" in _tables(engine)


@needs_db
def test_current_strategy_runs_view_has_the_tables_columns(engine):
    """The view lists strategy_runs' columns by name, and schema.py mirrors them; a
    column added to strategy_runs needs the view recreated in the same revision."""
    migrate.upgrade()
    view = [c["name"] for c in inspect(engine).get_columns("current_strategy_runs")]
    assert view == [c.name for c in schema.strategy_runs.c]
    assert view == [c.name for c in schema.current_strategy_runs.c]


# --- 0006: cleanup ---------------------------------------------------------------------


@needs_db
def test_0006_moves_rows_onto_the_new_keys(engine):
    migrate.upgrade("0005")
    weekend = "(SELECT id FROM race_weekends WHERE round_number = 11)"
    _exec(
        engine,
        _circuit("silverstone"),
        "INSERT INTO race_weekends (circuit_id, season, round_number, event_name, race_date, "
        "is_sprint) VALUES ('silverstone', 2026, 11, 'British GP', '2026-07-05', true)",
        "INSERT INTO sessions (race_weekend_id, session_order, name, start_time) VALUES "
        f"({weekend}, 1, 'Practice 1', '2026-07-03 11:30+00'), "
        f"({weekend}, 2, 'Sprint Qualifying', '2026-07-03 15:30+00'), "
        f"({weekend}, 5, 'Race', '2026-07-05 14:00+00')",
        # the old job's guesses: two names for Friday, with one forecast between them
        "INSERT INTO weather_forecasts (race_weekend_id, session_name, session_date, condition, "
        "temp_high_c, temp_low_c, rain_probability, wind_speed_kph, updated_at) VALUES "
        f"({weekend}, 'FP1', '2026-07-03', 'Rain', 18, 11, 80, 20, '2026-07-01'), "
        f"({weekend}, 'Sprint Qualifying', '2026-07-03', 'Rain', 18, 11, 80, 20, '2026-07-01'), "
        f"({weekend}, 'Race', '2026-07-05', 'Clear', 24, 14, 5, 9, '2026-07-01')",
        "INSERT INTO derived_artifacts (kind, year, round_number, data) "
        "VALUES ('laps', 2026, 11, '\\x00')",
        "INSERT INTO circuit_stats (circuit_id, season, sc_probability, red_flag_probability) "
        "VALUES ('silverstone', 2026, 50, 0)",
    )
    migrate.upgrade()
    assert migrate.check() == []

    def rows(sql):
        with engine.connect() as conn:
            return [tuple(r) for r in conn.exec_driver_sql(sql).all()]

    assert rows("SELECT timezone FROM circuits") == [("Europe/London",)]
    assert rows("SELECT name, kind FROM sessions ORDER BY session_order") == [
        ("Practice 1", "fp1"),
        ("Sprint Qualifying", "sprint_quali"),
        ("Race", "race"),
    ]
    assert rows(
        "SELECT forecast_date::text, condition FROM weather_forecasts ORDER BY 1"
    ) == [("2026-07-03", "Rain"), ("2026-07-05", "Clear")]
    assert rows("SELECT kind, season, round_number FROM derived_artifacts") == [("laps", 2026, 11)]
    assert "circuit_stats" not in _tables(engine)

    # ...and back: each day becomes the session rows the old job wrote for it.
    migrate.downgrade("0005")
    assert rows(
        "SELECT session_name, session_date::text FROM weather_forecasts ORDER BY 2, 1"
    ) == [("FP1", "2026-07-03"), ("Sprint Qualifying", "2026-07-03"), ("Race", "2026-07-05")]
    assert rows("SELECT year FROM derived_artifacts") == [(2026,)]
    assert "circuit_stats" in _tables(engine)
    migrate.upgrade()
    assert migrate.check() == []


@needs_db
def test_0006_refuses_what_it_cannot_place(engine):
    migrate.upgrade("0005")
    _exec(
        engine,
        _circuit("nurburgring"),
        _weekend("nurburgring", 2020, 11),
        "INSERT INTO sessions (race_weekend_id, session_order, name, start_time) "
        "SELECT id, 1, 'Sprint Race', '2020-10-09 10:00+00' FROM race_weekends",
        "UPDATE race_weekends SET soft_compound = 'C9'",
    )
    with pytest.raises(migrate.MigrationError) as err:
        migrate.upgrade()
    msg = str(err.value)
    assert "circuits nurburgring: no time zone" in msg
    assert "no kind for 'Sprint Race'" in msg
    assert "race_weekends.soft_compound: 'C9'" in msg
    assert _version(engine) == "0005"
