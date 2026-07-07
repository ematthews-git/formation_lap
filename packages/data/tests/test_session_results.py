"""Unit tests for the session-results path.

No database or FastF1 network — the FastF1 event schedule and session are faked with
plain pandas objects, and the "results due" arithmetic is a pure helper.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd

from formation_data import repositories
from formation_data.sources import fastf1_client


# --- repositories.results_due_at (pure duration + delay arithmetic) ---


def test_results_due_at_uses_session_duration_plus_delay():
    start = datetime(2026, 7, 5, 14, 0, tzinfo=timezone.utc)
    # Race = 120 min running + 45 min delay = 165 min after start.
    assert repositories.results_due_at("Race", start) == datetime(
        2026, 7, 5, 16, 45, tzinfo=timezone.utc
    )
    # Practice = 60 + 45 = 105 min.
    assert repositories.results_due_at("Practice 1", start) == datetime(
        2026, 7, 5, 15, 45, tzinfo=timezone.utc
    )
    # Sprint Qualifying = 45 + 45 = 90 min.
    assert repositories.results_due_at("Sprint Qualifying", start) == datetime(
        2026, 7, 5, 15, 30, tzinfo=timezone.utc
    )


def test_results_due_at_unknown_name_falls_back_to_default_duration():
    start = datetime(2026, 7, 5, 14, 0, tzinfo=timezone.utc)
    # Unknown name → 60 min default + 45 delay = 105 min.
    assert repositories.results_due_at("Mystery Session", start) == datetime(
        2026, 7, 5, 15, 45, tzinfo=timezone.utc
    )


# --- fastf1_client pure formatters ---


def test_fmt_lap_formats_minutes_and_sub_minute():
    assert fastf1_client._fmt_lap(89.9) == "1:29.900"
    assert fastf1_client._fmt_lap(58.25) == "58.250"
    assert fastf1_client._fmt_lap(None) is None


def test_fmt_time_formats_gap_and_full_time_and_handles_missing():
    assert fastf1_client._fmt_time(pd.Timedelta("0:00:05.3")) == "5.300"
    assert fastf1_client._fmt_time(pd.Timedelta("1:30:00")) == "1:30:00.000"
    assert fastf1_client._fmt_time(pd.NaT) is None
    assert fastf1_client._fmt_time(None) is None


# --- fastf1_client.get_session_results ---


class _FakeSession:
    def __init__(self, results: pd.DataFrame, laps: pd.DataFrame):
        self.results = results
        self.laps = laps

    def load(self, **_kwargs):  # noqa: D401 — no-op stand-in for FastF1's loader
        return None


def _patch(monkeypatch, session: _FakeSession) -> None:
    """Stub the event-schedule lookup (→ one Silverstone round) and get_session."""
    schedule = pd.DataFrame(
        [
            {
                "EventFormat": "conventional",
                "Location": "Silverstone",
                "RoundNumber": 12,
                "EventDate": pd.Timestamp("2026-07-05"),
            }
        ]
    )
    monkeypatch.setattr(fastf1_client, "get_event_schedule", lambda season: schedule)
    monkeypatch.setattr(
        fastf1_client.fastf1, "get_session", lambda *a, **k: session
    )


_LAPS = pd.DataFrame(
    {
        "Driver": ["VER", "HAM", "VER", "HAM"],
        "LapTime": pd.to_timedelta(
            ["0:01:30.5", "0:01:31.2", "0:01:29.9", "0:01:32.0"]
        ),
    }
)  # fastest: VER 89.9s, HAM 91.2s


def test_race_results_ordered_by_position(monkeypatch):
    results = pd.DataFrame(
        [
            {
                "Abbreviation": "HAM", "DriverNumber": "44", "FullName": "Lewis Hamilton",
                "TeamName": "Ferrari", "Position": 2.0,
                "Time": pd.Timedelta("0:00:05.3"), "Status": "Finished", "Points": 18.0,
            },
            {
                "Abbreviation": "VER", "DriverNumber": "1", "FullName": "Max Verstappen",
                "TeamName": "Red Bull", "Position": 1.0,
                "Time": pd.Timedelta("1:30:00"), "Status": "Finished", "Points": 25.0,
            },
        ]
    )
    _patch(monkeypatch, _FakeSession(results, _LAPS))

    rows = fastf1_client.get_session_results(2026, "Silverstone", date(2026, 7, 5), "Race")

    assert [r["driver_id"] for r in rows] == ["VER", "HAM"]
    assert rows[0]["position"] == 1
    assert rows[0]["points"] == 25.0
    assert rows[0]["status"] == "Finished"
    assert rows[0]["fastest_lap_s"] == 89.9
    assert rows[1]["time"] == "5.300"


def test_practice_results_ranked_by_fastest_lap(monkeypatch):
    # Practice has no official order — Position is NaN, rank comes from the fastest lap.
    results = pd.DataFrame(
        [
            {
                "Abbreviation": "HAM", "DriverNumber": "44", "FullName": "Lewis Hamilton",
                "TeamName": "Ferrari", "Position": float("nan"), "Status": None,
                "Points": float("nan"),
            },
            {
                "Abbreviation": "VER", "DriverNumber": "1", "FullName": "Max Verstappen",
                "TeamName": "Red Bull", "Position": float("nan"), "Status": None,
                "Points": float("nan"),
            },
        ]
    )
    _patch(monkeypatch, _FakeSession(results, _LAPS))

    rows = fastf1_client.get_session_results(
        2026, "Silverstone", date(2026, 7, 5), "Practice 1"
    )

    assert [r["driver_id"] for r in rows] == ["VER", "HAM"]
    assert [r["position"] for r in rows] == [1, 2]
    assert rows[0]["time"] == "1:29.900"  # VER's fastest lap
    assert rows[0]["points"] is None


def test_qualifying_uses_best_flying_lap(monkeypatch):
    results = pd.DataFrame(
        [
            {
                "Abbreviation": "VER", "DriverNumber": "1", "FullName": "Max Verstappen",
                "TeamName": "Red Bull", "Position": 1.0, "Status": None,
                "Points": float("nan"),
                "Q1": pd.Timedelta("0:01:30.0"), "Q2": pd.Timedelta("0:01:29.0"),
                "Q3": pd.Timedelta("0:01:28.5"),
            },
        ]
    )
    _patch(monkeypatch, _FakeSession(results, _LAPS))

    rows = fastf1_client.get_session_results(
        2026, "Silverstone", date(2026, 7, 5), "Qualifying"
    )

    assert rows[0]["position"] == 1
    assert rows[0]["fastest_lap_s"] == 88.5  # best of Q1/Q2/Q3
    assert rows[0]["time"] == "1:28.500"


def test_null_positions_fall_back_to_fastest_lap_ranking(monkeypatch):
    # Sprint Qualifying sheets can arrive with no Position — rank by best lap instead.
    results = pd.DataFrame(
        [
            {
                "Abbreviation": "HAM", "DriverNumber": "44", "FullName": "Lewis Hamilton",
                "TeamName": "Ferrari", "Position": float("nan"), "Status": None,
                "Points": float("nan"), "Q1": pd.Timedelta("0:01:29.0"),
                "Q2": pd.Timedelta("0:01:28.4"), "Q3": pd.NaT,
            },
            {
                "Abbreviation": "VER", "DriverNumber": "1", "FullName": "Max Verstappen",
                "TeamName": "Red Bull", "Position": float("nan"), "Status": None,
                "Points": float("nan"), "Q1": pd.Timedelta("0:01:29.5"),
                "Q2": pd.Timedelta("0:01:28.9"), "Q3": pd.NaT,
            },
        ]
    )
    _patch(monkeypatch, _FakeSession(results, _LAPS))

    rows = fastf1_client.get_session_results(
        2026, "Silverstone", date(2026, 7, 5), "Sprint Qualifying"
    )

    # HAM's 1:28.4 beats VER's 1:28.9 → HAM P1 even though both had NaN Position.
    assert [(r["driver_id"], r["position"]) for r in rows] == [("HAM", 1), ("VER", 2)]
    assert rows[0]["time"] == "1:28.400"


def test_empty_classification_returns_empty(monkeypatch):
    _patch(monkeypatch, _FakeSession(pd.DataFrame(), pd.DataFrame()))
    assert (
        fastf1_client.get_session_results(2026, "Silverstone", date(2026, 7, 5), "Race")
        == []
    )


def test_unresolvable_event_returns_empty(monkeypatch):
    monkeypatch.setattr(
        fastf1_client,
        "get_event_schedule",
        lambda season: pd.DataFrame(
            [{"EventFormat": "conventional", "Location": "Monza", "RoundNumber": 16,
              "EventDate": pd.Timestamp("2026-09-06")}]
        ),
    )
    # Location "Silverstone" isn't in the (Monza-only) schedule → no event → [].
    assert (
        fastf1_client.get_session_results(2026, "Silverstone", date(2026, 7, 5), "Race")
        == []
    )
