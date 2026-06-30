"""Unit tests for the pure helpers in jobs.pre_race.weather.

No database or network — just the session-schedule synthesis and the WMO
weather-code classifier.
"""

from __future__ import annotations

from datetime import date

from formation_data.domain import RaceWeekend
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


# --- _session_schedule ---


def test_conventional_weekend_sessions():
    sessions = weather._session_schedule(_weekend(date(2026, 7, 5), is_sprint=False))
    assert [name for name, _ in sessions] == ["FP1", "FP2", "FP3", "Qualifying", "Race"]
    # Fri/Sat/Sun = race-2 / race-1 / race
    assert dict(sessions)["FP1"] == date(2026, 7, 3)
    assert dict(sessions)["FP3"] == date(2026, 7, 4)
    assert dict(sessions)["Race"] == date(2026, 7, 5)


def test_sprint_weekend_sessions():
    sessions = weather._session_schedule(_weekend(date(2026, 7, 5), is_sprint=True))
    assert [name for name, _ in sessions] == [
        "FP1",
        "Sprint Qualifying",
        "Sprint",
        "Qualifying",
        "Race",
    ]
    assert dict(sessions)["Sprint"] == date(2026, 7, 4)


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
