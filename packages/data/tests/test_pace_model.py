"""Unit tests for the shared pace_model helpers — pure pandas, no DB/network."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from formation_data.jobs.pre_season import pace_model


def _laps_df(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["LapTime"] = pd.to_timedelta(df["LapTime"], unit="s")
    if "Time" in df.columns:
        df["Time"] = pd.to_timedelta(df["Time"], unit="s")
    return df


# --- to_seconds ---


def test_to_seconds_converts_laptime_and_time():
    laps = _laps_df([{"LapTime": 90.0, "Time": 90.0}])
    out = pace_model.to_seconds(laps)
    assert out["LapTime_s"].iloc[0] == pytest.approx(90.0)
    assert out["Time_s"].iloc[0] == pytest.approx(90.0)


# --- green_flying ---


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
    out = pace_model.green_flying(laps)
    assert list(out["LapNumber"]) == [2]
    assert out["LapTime_s"].iloc[0] == pytest.approx(90.0)


# --- reference_pace ---


def test_reference_pace_medians_per_lap_with_min_cars():
    rows = []
    # Lap 2: four green cars -> kept, median of [90, 91, 92, 93] = 91.5
    for t in (90.0, 91.0, 92.0, 93.0):
        rows.append({"LapNumber": 2, "LapTime": t, "PitInTime": pd.NaT,
                     "PitOutTime": pd.NaT, "TrackStatus": "1", "TyreLife": 5})
    # Lap 3: only two green cars -> dropped (< min_cars=4)
    for t in (90.0, 92.0):
        rows.append({"LapNumber": 3, "LapTime": t, "PitInTime": pd.NaT,
                     "PitOutTime": pd.NaT, "TrackStatus": "1", "TyreLife": 6})
    ref = pace_model.reference_pace(_laps_df(rows), min_cars=4)
    assert list(ref.index) == [2]
    assert ref.loc[2] == pytest.approx(91.5)


# --- add_stint_id ---


def test_add_stint_id_increments_on_out_laps():
    laps = _laps_df(
        [
            {"LapNumber": 1, "LapTime": 90.0, "PitOutTime": pd.NaT},
            {"LapNumber": 2, "LapTime": 90.0, "PitOutTime": pd.NaT},
            {"LapNumber": 3, "LapTime": 95.0, "PitOutTime": pd.Timestamp("2026-05-03 15:01")},
            {"LapNumber": 4, "LapTime": 90.0, "PitOutTime": pd.NaT},
        ]
    )
    stints = pace_model.add_stint_id(laps)
    assert list(stints) == [0, 0, 1, 1]


# --- time_pivot ---


def test_time_pivot_reconstructs_gap():
    laps = _laps_df(
        [
            {"Driver": "VER", "LapNumber": 5, "LapTime": 90.0, "Time": 450.0},
            {"Driver": "HAM", "LapNumber": 5, "LapTime": 91.0, "Time": 451.2},
        ]
    )
    pivot = pace_model.time_pivot(laps)
    # HAM crosses 1.2s after VER -> VER ahead by 1.2s.
    gap = pivot.loc[5, "HAM"] - pivot.loc[5, "VER"]
    assert gap == pytest.approx(1.2)


# --- slick / clean_air ---


def test_slick_drops_wet_compounds():
    laps = _laps_df(
        [
            {"LapNumber": 1, "LapTime": 90.0, "Compound": "MEDIUM"},
            {"LapNumber": 2, "LapTime": 95.0, "Compound": "INTERMEDIATE"},
            {"LapNumber": 3, "LapTime": 99.0, "Compound": "WET"},
        ]
    )
    out = pace_model.slick(laps)
    assert list(out["Compound"]) == ["MEDIUM"]


def test_clean_air_keeps_leader_and_cars_in_clear_air():
    # Lap 5: VER leads (clean), HAM 0.4s back (dirty), RUS 2.0s back (clean).
    laps = _laps_df(
        [
            {"Driver": "VER", "LapNumber": 5, "LapTime": 90.0, "Time": 450.0},
            {"Driver": "HAM", "LapNumber": 5, "LapTime": 90.0, "Time": 450.4},
            {"Driver": "RUS", "LapNumber": 5, "LapTime": 90.0, "Time": 452.4},
        ]
    )
    out = pace_model.clean_air(laps, min_gap=1.0)
    assert set(out["Driver"]) == {"VER", "RUS"}  # HAM dropped (0.4s, dirty air)


def test_add_gap_to_ahead_leader_is_nan():
    laps = _laps_df(
        [
            {"Driver": "VER", "LapNumber": 5, "LapTime": 90.0, "Time": 450.0},
            {"Driver": "HAM", "LapNumber": 5, "LapTime": 90.0, "Time": 451.5},
        ]
    )
    out = pace_model.add_gap_to_ahead(laps).set_index("Driver")
    assert pd.isna(out.loc["VER", "GapAhead_s"])
    assert out.loc["HAM", "GapAhead_s"] == pytest.approx(1.5)


# --- least_squares_slope ---


def test_least_squares_slope_recovers_known_slope():
    x = [1, 2, 3, 4, 5]
    y = [10 + 0.3 * xi for xi in x]
    assert pace_model.least_squares_slope(x, y) == pytest.approx(0.3)


def test_least_squares_slope_degenerate_returns_nan():
    assert np.isnan(pace_model.least_squares_slope([2, 2, 2], [1, 2, 3]))
    assert np.isnan(pace_model.least_squares_slope([1.0], [1.0]))
