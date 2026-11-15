"""Drivers and teams: the seeds, resolving what sources name, and the reads built on them.

Needs a throwaway Postgres (FORMATION_TEST_DATABASE_URL, see test_migrations.py).
"""

from __future__ import annotations

import os
from datetime import date

import pytest

from formation_data import domain, migrate, repositories, schema
from formation_data.jobs.post_race import race_results
from formation_data.jobs.static import drivers as static_drivers
from formation_data.jobs.static import teams as static_teams

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
            "num_laps, sm_zones, jolpica_id, fastf1_location, lat, lon) VALUES "
            "('spa', 'BE', 7.0, 19, 44, 2, 'spa', 'Spa-Francorchamps', 0, 0)"
        )
        yield c


def _weekend(conn, season: int, rnd: int) -> domain.RaceWeekend:
    repositories.upsert(
        conn,
        schema.race_weekends,
        [
            domain.RaceWeekend(
                circuit_id="spa",
                season=season,
                round_number=rnd,
                event_name="Belgian Grand Prix",
                race_date=date(season, 7, rnd),
                is_sprint=False,
            )
        ],
        ["season", "round_number"],
    )
    return repositories.get_race_weekend(conn, season, rnd)


def _result(position: int, driver_id: str, family: str, code: str, constructor: str) -> dict:
    return {
        "position": str(position),
        "Driver": {
            "driverId": driver_id,
            "givenName": "Test",
            "familyName": family,
            "code": code,
            "nationality": "British",
        },
        "Constructor": {"constructorId": constructor, "name": "whatever Jolpica calls it"},
    }


def test_seeds_load_and_reload(conn):
    for _ in range(2):
        static_teams.run(conn)
        static_drivers.run(conn, season=2026)
    grid = repositories.list_season_grid(conn, 2026, today=date(2026, 6, 1))
    assert len(grid) == 22
    lindblad = next(g for g in grid if g.driver_id == "arvid_lindblad")
    assert (lindblad.full_name, lindblad.team_id, lindblad.team) == (
        "Arvid Lindblad",
        "racing_bulls",
        "Racing Bulls",
    )


def test_results_store_drivers_and_teams_by_source_key(conn):
    weekend = _weekend(conn, 2024, 10)
    race = {
        "round": "10",
        "Results": [
            _result(1, "rookie_one", "One", "ONE", "rb"),
            _result(2, "max_verstappen", "Verstappen", "VER", "red_bull"),
        ],
    }
    race_results._persist_race(conn, weekend, race)
    stored = repositories.list_race_results(conn, 2024)
    assert [(r.driver_id, r.family_name, r.team_id, r.team) for r in stored] == [
        ("rookie_one", "One", "racing_bulls", "RB"),  # a new driver is added as they race
        ("max_verstappen", "Verstappen", "red_bull", "Red Bull Racing"),
    ]

    # A corrected classification reorders the same drivers without tripping either key.
    race["Results"] = [
        _result(1, "max_verstappen", "Verstappen", "VER", "red_bull"),
        _result(2, "rookie_one", "One", "ONE", "rb"),
    ]
    race_results._persist_race(conn, weekend, race)
    assert [r.driver_id for r in repositories.list_race_results(conn, 2024)] == [
        "max_verstappen",
        "rookie_one",
    ]

    race["Results"] = [_result(1, "button", "Button", "BUT", "brawn")]
    with pytest.raises(repositories.TeamNotFound, match="'brawn' isn't a 2024 team"):
        race_results._persist_race(conn, weekend, race)


def test_driver_codes_resolve_within_a_season(conn):
    weekend = _weekend(conn, 2022, 14)
    race_results._persist_race(
        conn,
        weekend,
        {"round": "14", "Results": [_result(1, "mick_schumacher", "Schumacher", "MSC", "haas")]},
    )
    assert repositories.driver_for_code(conn, "MSC", 2022).driver_id == "mick_schumacher"
    # Michael is MSC too, but has no 2022 race or seat
    with pytest.raises(repositories.DriverNotFound, match="no driver with code 'MSC'"):
        repositories.driver_for_code(conn, "MSC", 2004)


def test_upsert_drivers_keeps_a_known_code(conn):
    repositories.upsert_drivers(
        conn, [domain.Driver(driver_id="x", given_name="A", family_name="B", code="XXX")]
    )
    repositories.upsert_drivers(
        conn, [domain.Driver(driver_id="x", given_name="A", family_name="B2")]
    )
    row = conn.exec_driver_sql("SELECT family_name, code FROM drivers WHERE driver_id = 'x'")
    assert tuple(row.one()) == ("B2", "XXX")


def test_grid_follows_mid_season_seat_changes(conn):
    def seat(driver_id, team_id, start, end=None):
        return domain.Seat(
            driver_id=driver_id, team_id=team_id, season=2025, valid_from=start, valid_to=end
        )

    swap, replaced = date(2025, 4, 1), date(2025, 5, 7)
    repositories.upsert_drivers(
        conn,
        [domain.Driver(driver_id="doohan", given_name="Jack", family_name="Doohan")],
    )
    repositories.upsert(
        conn,
        schema.seats,
        [
            seat("lawson", "red_bull", date(2025, 1, 1), swap),
            seat("lawson", "racing_bulls", swap),
            seat("tsunoda", "racing_bulls", date(2025, 1, 1), swap),
            seat("tsunoda", "red_bull", swap),
            seat("doohan", "alpine", date(2025, 1, 1), replaced),
            seat("colapinto", "alpine", replaced),
        ],
        ["driver_id", "valid_from"],
    )

    def grid(today):
        return {g.driver_id: g.team_id for g in repositories.list_season_grid(conn, 2025, today)}

    assert grid(date(2024, 12, 1)) == {  # before the season: its opening grid
        "lawson": "red_bull",
        "tsunoda": "racing_bulls",
        "doohan": "alpine",
    }
    assert grid(date(2025, 4, 1)) == {
        "lawson": "racing_bulls",
        "tsunoda": "red_bull",
        "doohan": "alpine",
    }
    assert grid(date(2026, 3, 1)) == {  # after it: the closing grid
        "lawson": "racing_bulls",
        "tsunoda": "red_bull",
        "colapinto": "alpine",
    }


def test_standings_read_the_latest_race_with_names(conn):
    r1, r2 = _weekend(conn, 2024, 1), _weekend(conn, 2024, 2)
    for weekend, leader in ((r1, "max_verstappen"), (r2, "norris")):
        repositories.replace_standings(
            conn,
            weekend.id,
            [domain.DriverStanding(race_weekend_id=weekend.id, driver_id=leader, position=1, points=25)],
            [domain.ConstructorStanding(race_weekend_id=weekend.id, team_id="audi", position=1, points=25)],
        )
    (driver,) = repositories.list_standings(conn, 2024, "driver")
    assert (driver.after_round, driver.name, driver.driver_id) == (2, "Lando Norris", "norris")
    (team,) = repositories.list_standings(conn, 2024, "constructor", after_round=1)
    assert (team.after_round, team.name, team.team_id) == (1, "Kick Sauber", "audi")


def test_race_traces_gain_team_ids(conn):
    weekend = _weekend(conn, 2024, 3)
    repositories.upsert_race_trace(
        conn,
        weekend.id,
        {"drivers": [{"code": "TSU", "team": "RB"}, {"code": "BUT", "team": "Brawn GP"}]},
    )
    (trace,) = repositories.list_race_traces_for_circuit(conn, "spa")
    assert [d["team_id"] for d in trace.trace["drivers"]] == ["racing_bulls", None]
    with pytest.raises(repositories.TeamNotFound, match="Brawn GP"):
        repositories.require_fastf1_teams(conn, 2024, {"RB", "Brawn GP"})
