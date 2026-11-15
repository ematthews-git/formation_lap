"""Unit tests for the pure helpers in jobs.pre_race.weather.

No database or network — just which days to forecast and the WMO weather-code
classifier.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from formation_data.domain import Circuit, RaceWeekend, Session
from formation_data.jobs.pre_race import weather


def _weekend(race_date: date, is_sprint: bool) -> RaceWeekend:
    return RaceWeekend(
        circuit_id="silverstone",
        season=2026,
        round_number=11,
        event_name="British Grand Prix",
        race_date=race_date,
        is_sprint=is_sprint,
        soft_compound="C4",
        medium_compound="C3",
        hard_compound="C2",
    )


# --- _forecast_days ---


def _circuit(timezone: str) -> Circuit:
    return Circuit(
        circuit_id="las_vegas",
        country="USA",
        track_length_km=6.2,
        num_corners=17,
        num_laps=50,
        sm_zones=3,
        jolpica_id="vegas",
        fastf1_location="Las Vegas",
        lat=36.1,
        lon=-115.2,
        timezone=timezone,
    )


def _session(kind: str, start: datetime) -> Session:
    return Session(race_weekend_id=1, kind=kind, session_order=1, name=kind, start_time=start)


def test_forecast_days_are_the_circuits_local_session_days():
    utc = timezone.utc
    # Las Vegas runs at night: Thursday-evening FP1 and the Saturday-night race are
    # Friday and Sunday in UTC, so UTC dates would ask for the wrong days.
    sessions = [
        _session("fp1", datetime(2026, 11, 20, 0, 30, tzinfo=utc)),  # Thu 16:30 local
        _session("quali", datetime(2026, 11, 21, 6, 0, tzinfo=utc)),  # Fri 22:00 local
        _session("race", datetime(2026, 11, 22, 6, 0, tzinfo=utc)),  # Sat 22:00 local
    ]
    days = weather._forecast_days(
        _weekend(date(2026, 11, 21), is_sprint=False), sessions, _circuit("America/Los_Angeles")
    )
    assert days == [date(2026, 11, 19), date(2026, 11, 20), date(2026, 11, 21)]


def test_forecast_days_without_a_timetable_are_friday_to_sunday():
    days = weather._forecast_days(
        _weekend(date(2026, 7, 5), is_sprint=True), [], _circuit("Europe/London")
    )
    assert days == [date(2026, 7, 3), date(2026, 7, 4), date(2026, 7, 5)]


# --- _classify ---


def test_classify_known_codes():
    assert weather._classify(0) == "Clear"
    assert weather._classify(3) == "Overcast"
    assert weather._classify(65) == "Rain"
    assert weather._classify(82) == "Showers"
    assert weather._classify(95) == "Thunderstorm"


def test_classify_handles_none_and_unknown():
    assert weather._classify(None) == "Unknown"
    assert weather._classify(123) == "Unknown"
