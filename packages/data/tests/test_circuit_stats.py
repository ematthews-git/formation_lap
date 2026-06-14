"""Unit tests for the pure DataFrame helpers in jobs.pre_season.circuit_stats.

No database or FastF1 network access — sessions are faked with plain objects
carrying the two attributes the helpers read (race_control_messages, laps).
"""

from __future__ import annotations

import pandas as pd
import pytest

from formation_data.jobs.pre_season import circuit_stats


class FakeSession:
    def __init__(self, race_control_messages=None, laps=None):
        self.race_control_messages = race_control_messages
        self.laps = laps


def _rc(rows: list[tuple[str, str]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["Message", "Status"])


# --- _safety_car_probability ---


def test_sc_counts_full_safety_car():
    session = FakeSession(_rc([("SAFETY CAR DEPLOYED", "DEPLOYED")]))
    assert circuit_stats._safety_car_probability([session]) == 100


def test_sc_excludes_virtual_safety_car():
    session = FakeSession(_rc([("VIRTUAL SAFETY CAR DEPLOYED", "DEPLOYED")]))
    assert circuit_stats._safety_car_probability([session]) == 0


def test_sc_requires_deployed_status():
    session = FakeSession(_rc([("SAFETY CAR IN THIS LAP", "ENDING")]))
    assert circuit_stats._safety_car_probability([session]) == 0


def test_sc_returns_int_percent():
    with_sc = FakeSession(_rc([("SAFETY CAR DEPLOYED", "DEPLOYED")]))
    without = FakeSession(_rc([("YELLOW FLAG", "")]))
    assert circuit_stats._safety_car_probability([with_sc, without]) == 50
    assert circuit_stats._safety_car_probability([with_sc, without, without]) == 33


def test_sc_rejects_empty_sessions():
    with pytest.raises(ValueError):
        circuit_stats._safety_car_probability([])


# --- _red_flag_probability ---


def test_red_flag_counted():
    session = FakeSession(_rc([("RED FLAG", "")]))
    assert circuit_stats._red_flag_probability([session]) == 100


def test_red_flag_matches_within_longer_message():
    session = FakeSession(_rc([("RED FLAG DEPLOYED FOR DEBRIS", "")]))
    assert circuit_stats._red_flag_probability([session]) == 100


def test_red_flag_absent():
    session = FakeSession(_rc([("CHEQUERED FLAG", "")]))
    assert circuit_stats._red_flag_probability([session]) == 0


def test_red_flag_rejects_empty_sessions():
    with pytest.raises(ValueError):
        circuit_stats._red_flag_probability([])


# --- _green_flying ---


def _laps_df(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["LapTime"] = pd.to_timedelta(df["LapTime"], unit="s")
    return df


def test_green_flying_filters():
    laps = _laps_df(
        [
            # kept: clean flying lap
            {"LapNumber": 2, "LapTime": 90.0, "PitInTime": pd.NaT,
             "PitOutTime": pd.NaT, "TrackStatus": "1", "TyreLife": 5},
            # dropped: in-lap
            {"LapNumber": 3, "LapTime": 91.0, "PitInTime": pd.Timestamp("2026-05-03 15:00"),
             "PitOutTime": pd.NaT, "TrackStatus": "1", "TyreLife": 6},
            # dropped: safety car (TrackStatus contains 4)
            {"LapNumber": 4, "LapTime": 99.0, "PitInTime": pd.NaT,
             "PitOutTime": pd.NaT, "TrackStatus": "45", "TyreLife": 7},
            # dropped: first lap on tyre
            {"LapNumber": 5, "LapTime": 92.0, "PitInTime": pd.NaT,
             "PitOutTime": pd.NaT, "TrackStatus": "1", "TyreLife": 1},
            # dropped: no lap time
            {"LapNumber": 6, "LapTime": float("nan"), "PitInTime": pd.NaT,
             "PitOutTime": pd.NaT, "TrackStatus": "1", "TyreLife": 8},
        ]
    )
    out = circuit_stats._green_flying(laps)
    assert list(out["LapNumber"]) == [2]
    assert out["LapTime_s"].iloc[0] == pytest.approx(90.0)


# --- _fresh_tyre_advantage ---


def test_fresh_tyre_advantage_single_clean_stop():
    pit_lap = 10
    rows = []
    for lap in range(1, 21):
        rows.append(
            {
                "Driver": "VER",
                "LapNumber": lap,
                # worn mediums 92.0s, fresh hards 90.5s; slow in/out laps
                "LapTime": 95.0 if lap == pit_lap
                else 94.0 if lap == pit_lap + 1
                else 92.0 if lap < pit_lap
                else 90.5,
                "PitInTime": pd.Timestamp("2026-05-03 15:00") if lap == pit_lap else pd.NaT,
                "PitOutTime": pd.Timestamp("2026-05-03 15:01") if lap == pit_lap + 1 else pd.NaT,
                "TrackStatus": "1",
                "TyreLife": lap if lap <= pit_lap else lap - pit_lap,
                "Compound": "MEDIUM" if lap <= pit_lap else "HARD",
            }
        )
    session = FakeSession(laps=_laps_df(rows))

    df = circuit_stats._fresh_tyre_advantage(session, fuel_rate=-0.06, n=3)

    assert len(df) == 1
    row = df.iloc[0]
    assert row["drv"] == "VER"
    assert row["pit_lap"] == pit_lap
    assert row["from"] == "MEDIUM"
    # worn = laps 7-9 (92.0s), fresh = laps 12-14 (90.5s), 5 laps apart:
    # (92.0 - 90.5) + (-0.06 * 5) = 1.2
    assert row["fresh_adv"] == pytest.approx(1.2)
