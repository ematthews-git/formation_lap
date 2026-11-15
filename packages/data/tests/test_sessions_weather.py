"""Session kinds, the per-day weather forecast and the API's per-session view of it,
circuit time zones, and what a weekend takes with it when deleted.

The database tests need a throwaway Postgres (FORMATION_TEST_DATABASE_URL, see
test_migrations.py).
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import exc as sa_exc

from formation_data import domain, migrate, repositories, schema
from formation_data.jobs.pre_race import weather
from formation_data.jobs.pre_season import sessions as sessions_job
from formation_data.jobs.static import circuits as circuits_seed
from formation_data.sources import fastf1_client, weather_client

needs_db = pytest.mark.skipif(
    not os.environ.get("FORMATION_TEST_DATABASE_URL"),
    reason="FORMATION_TEST_DATABASE_URL not set",
)


def _0006():
    return ScriptDirectory.from_config(migrate.config()).get_revision("0006").module


def test_seeded_time_zones_are_real_and_match_0006():
    for c in circuits_seed.CIRCUITS:
        ZoneInfo(c.timezone)  # raises for a zone that doesn't exist
    assert {c.circuit_id: c.timezone for c in circuits_seed.CIRCUITS} == _0006()._TIMEZONES


def test_session_kinds_match_0006_and_the_schema():
    m = _0006()
    for name in m._KIND_BY_NAME:
        for season in (2021, 2026):
            assert sessions_job.session_kind(name, season) == m._kind(name, season)
    assert set(sessions_job._KIND_BY_NAME.values()) == set(schema.SESSION_KINDS)
    assert sessions_job.session_kind("Sprint Qualifying", 2021) == "sprint"
    with pytest.raises(sessions_job.UnknownSession, match="'Sprint Race'"):
        sessions_job.session_kind("Sprint Race", 2026)


# --- database ---------------------------------------------------------------------------


@pytest.fixture
def conn(engine):
    migrate.upgrade()
    with engine.begin() as c:
        repositories.upsert(
            c,
            schema.circuits,
            [next(x for x in circuits_seed.CIRCUITS if x.circuit_id == "las_vegas")],
            ["circuit_id"],
        )
        repositories.upsert(
            c,
            schema.race_weekends,
            [
                domain.RaceWeekend(
                    circuit_id="las_vegas",
                    season=2026,
                    round_number=22,
                    event_name="Las Vegas Grand Prix",
                    race_date=date(2026, 11, 21),
                    is_sprint=False,
                )
            ],
            ["season", "round_number"],
        )
        yield c


def _utc(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=UTC)


# Thursday to Saturday nights in Las Vegas, which are Friday to Sunday in UTC.
_CONVENTIONAL = [
    (1, "Practice 1", _utc(20, 0, 30)),  # Thu 16:30 local
    (2, "Practice 2", _utc(20, 4)),  # Thu 20:00
    (3, "Practice 3", _utc(21, 0, 30)),  # Fri 16:30
    (4, "Qualifying", _utc(21, 4)),  # Fri 20:00
    (5, "Race", _utc(22, 6)),  # Sat 22:00
]


def _load_sessions(conn, monkeypatch, rows):
    monkeypatch.setattr(fastf1_client, "get_event_sessions", lambda *a, **k: rows)
    sessions_job.run(conn, season=2026)


@needs_db
def test_sessions_store_their_kind_and_follow_a_format_change(conn, monkeypatch):
    _load_sessions(conn, monkeypatch, _CONVENTIONAL)
    weekend = repositories.get_race_weekend(conn, 2026, 22)
    fp2 = repositories.get_session_by_kind(conn, weekend.id, "fp2")
    repositories.upsert_session_results(conn, fp2.id, [{"position": 1, "driver_id": "LEC"}])

    sprint = [
        (1, "Practice 1", _utc(20, 0, 30)),
        (2, "Sprint Qualifying", _utc(20, 4)),
        (3, "Sprint", _utc(21, 0, 30)),
        (4, "Qualifying", _utc(21, 4)),
        (5, "Race", _utc(22, 6)),
    ]
    _load_sessions(conn, monkeypatch, sprint)
    stored = repositories.list_sessions_for_weekend(conn, 2026, 22)
    assert [(s.session_order, s.kind) for s in stored] == [
        (1, "fp1"),
        (2, "sprint_quali"),
        (3, "sprint"),
        (4, "quali"),
        (5, "race"),
    ]
    # FP2 is gone, and its results with it.
    assert conn.exec_driver_sql("SELECT count(*) FROM session_results").scalar() == 0

    monkeypatch.setattr(
        fastf1_client, "get_event_sessions", lambda *a, **k: [(1, "Sprint Race", _utc(20, 1))]
    )
    with pytest.raises(sessions_job.UnknownSession):
        sessions_job.run(conn, season=2026)


def _forecast_day(day: str, code: int, rain: int) -> dict:
    return {
        "date": day,
        "weather_code": code,
        "temperature_2m_max": 18.0,
        "temperature_2m_min": 9.0,
        "precipitation_probability_max": rain,
        "wind_speed_10m_max": 12.0,
    }


@needs_db
def test_weather_is_stored_per_local_day_and_served_per_session(conn, monkeypatch):
    _load_sessions(conn, monkeypatch, _CONVENTIONAL)
    asked = {}

    def fake_forecast(lat, lon, start, end):
        asked.update(start=start, end=end)
        # Saturday (race day) is past the horizon: no forecast for it yet.
        return [
            _forecast_day("2026-11-19", 0, 0),
            _forecast_day("2026-11-20", 61, 70),
            {**_forecast_day("2026-11-21", 0, 0), "temperature_2m_max": None},
        ]

    monkeypatch.setattr(weather_client, "get_forecast", fake_forecast)
    weather.run(conn, season=2026, round_number=22)

    assert asked == {"start": date(2026, 11, 19), "end": date(2026, 11, 21)}
    stored = conn.exec_driver_sql(
        "SELECT forecast_date::text, condition FROM weather_forecasts ORDER BY 1"
    ).all()
    assert [tuple(r) for r in stored] == [("2026-11-19", "Clear"), ("2026-11-20", "Rain")]

    served = repositories.list_weather_for_weekend(conn, 2026, 22)
    assert [(w.session_kind, str(w.forecast_date), w.rain_probability) for w in served] == [
        ("fp1", "2026-11-19", 0),
        ("fp2", "2026-11-19", 0),
        ("fp3", "2026-11-20", 70),
        ("quali", "2026-11-20", 70),
    ]


@needs_db
def test_deleting_a_weekend_takes_what_belongs_to_it_but_not_history(conn, monkeypatch):
    _load_sessions(conn, monkeypatch, _CONVENTIONAL)
    weekend = repositories.get_race_weekend(conn, 2026, 22)
    race = repositories.get_session_by_kind(conn, weekend.id, "race")
    repositories.upsert_session_results(conn, race.id, [{"position": 1, "driver_id": "LEC"}])
    repositories.upsert(
        conn,
        schema.weather_forecasts,
        [
            domain.WeatherForecast(
                race_weekend_id=weekend.id,
                forecast_date=date(2026, 11, 21),
                condition="Clear",
                temp_high_c=18,
                temp_low_c=9,
                rain_probability=0,
                wind_speed_kph=10,
            )
        ],
        ["race_weekend_id", "forecast_date"],
    )
    repositories.insert_strategy_run(
        conn, domain.StrategyRun(race_weekend_id=weekend.id, source="historical"), []
    )

    conn.exec_driver_sql(f"DELETE FROM race_weekends WHERE id = {weekend.id}")
    for table in ("sessions", "session_results", "weather_forecasts", "strategy_runs"):
        assert conn.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar() == 0

    # A weekend that raced keeps its weekend row: results don't cascade.
    repositories.upsert_drivers(
        conn, [domain.Driver(driver_id="leclerc", given_name="Charles", family_name="Leclerc")]
    )
    conn.exec_driver_sql(
        "INSERT INTO teams (team_id, name) VALUES ('ferrari', 'Ferrari') ON CONFLICT DO NOTHING"
    )
    conn.exec_driver_sql(
        "INSERT INTO race_weekends (circuit_id, season, round_number, event_name, race_date, "
        "is_sprint) VALUES ('las_vegas', 2025, 22, 'Las Vegas Grand Prix', '2025-11-22', false)"
    )
    raced = repositories.get_race_weekend(conn, 2025, 22)
    conn.exec_driver_sql(
        "INSERT INTO race_results (race_weekend_id, position, driver_id, team_id) "
        f"VALUES ({raced.id}, 1, 'leclerc', 'ferrari')"
    )
    with pytest.raises(sa_exc.IntegrityError, match="race_results"):
        with conn.begin_nested():
            conn.exec_driver_sql(f"DELETE FROM race_weekends WHERE id = {raced.id}")


@needs_db
def test_status_strings_are_checked(conn):
    weekend = repositories.get_race_weekend(conn, 2026, 22)
    with pytest.raises(sa_exc.IntegrityError, match="weather_forecasts_condition_check"):
        with conn.begin_nested():
            conn.exec_driver_sql(
                "INSERT INTO weather_forecasts (race_weekend_id, forecast_date, condition, "
                "temp_high_c, temp_low_c, rain_probability, wind_speed_kph) VALUES "
                f"({weekend.id}, '2026-11-21', 'Sunny', 20, 10, 0, 5)"
            )
    with pytest.raises(sa_exc.IntegrityError, match="race_weekends_soft_compound_check"):
        with conn.begin_nested():
            conn.exec_driver_sql(
                f"UPDATE race_weekends SET soft_compound = 'C9' WHERE id = {weekend.id}"
            )
