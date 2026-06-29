"""Unit tests for the pace feeder metrics — synthetic FakeSessions, no DB/network."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from formation_data.jobs.pre_season import pace_metrics

_TS = pd.Timestamp("2026-05-03 15:00")


class FakeSession:
    def __init__(self, laps):
        self.laps = laps


def _laps_df(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["LapTime"] = pd.to_timedelta(df["LapTime"], unit="s")
    if "Time" in df.columns:
        df["Time"] = pd.to_timedelta(df["Time"], unit="s")
    return df


def _field_session(deg=0.10, fuelevo=-0.05, warmup=0.0, n_drivers=8, n_laps=24, pit0=9):
    """A full field, each car one stop at a staggered lap, true tyre model = (deg, warmup).

    LapTime = base + car_offset + deg*TyreLife + fuelevo*LapNumber (+warmup on the first
    flying lap). Cars are spaced far apart in session Time so every lap is clean air.
    Staggered stops decorrelate TyreLife from LapNumber across the field — the whole point
    of the cross-car estimator.
    """
    rows = []
    for i in range(n_drivers):
        pit = pit0 + i  # staggered stop
        offset = 0.1 * i
        for lap in range(1, n_laps + 1):
            tl = lap if lap <= pit else lap - pit
            lt = 90 + offset + deg * tl + fuelevo * lap + (warmup if tl == 2 else 0.0)
            rows.append(
                {
                    "Driver": f"D{i}",
                    "LapNumber": lap,
                    "LapTime": lt,
                    "Time": 100000.0 * i + lap * 90.0,  # cars far apart -> clean air
                    "PitInTime": _TS if lap == pit else pd.NaT,
                    "PitOutTime": _TS if lap == pit + 1 else pd.NaT,
                    "TrackStatus": "1",
                    "TyreLife": tl,
                    "Compound": "MEDIUM" if lap <= pit else "HARD",
                }
            )
    return FakeSession(_laps_df(rows))


# --- tyre_deg_rate (cross-car, same-lap) ---


def test_tyre_deg_rate_cancels_fuel_and_evolution():
    # Truth: deg 0.10/lap, plus a strong -0.05/lap fuel+evolution trend. A naive within-
    # stint slope would return ~0.05; the cross-car estimate must recover 0.10.
    deg = pace_metrics.tyre_deg_rate([_field_session(deg=0.10, fuelevo=-0.05)])
    assert deg == pytest.approx(0.10, abs=0.02)


def test_tyre_deg_rate_nan_on_thin_data():
    tiny = _laps_df(
        [{"Driver": "D0", "LapNumber": 2, "LapTime": 90.0, "Time": 180.0,
          "PitInTime": pd.NaT, "PitOutTime": pd.NaT, "TrackStatus": "1",
          "TyreLife": 2, "Compound": "MEDIUM"}]
    )
    assert np.isnan(pace_metrics.tyre_deg_rate([FakeSession(tiny)]))


# --- warmup_penalty ---


def test_warmup_penalty_detects_cold_tyres():
    cold = pace_metrics.warmup_penalty([_field_session(warmup=1.5)])
    none = pace_metrics.warmup_penalty([_field_session(warmup=0.0)])
    assert cold > 0.4
    assert cold > none + 0.4


# --- is_wet_race / wet exclusion ---


def test_is_wet_race_detects_intermediate_running():
    dry = _field_session().laps
    assert not pace_metrics.is_wet_race(FakeSession(dry))
    wet = dry.copy()
    wet.loc[wet.index[: len(wet) // 2], "Compound"] = "INTERMEDIATE"
    assert pace_metrics.is_wet_race(FakeSession(wet))


def test_tyre_model_skips_wet_race():
    wet = _field_session().laps.copy()
    wet["Compound"] = "WET"
    assert np.isnan(pace_metrics.tyre_deg_rate([FakeSession(wet)]))


# --- typical_stop_age ---


def test_typical_stop_age_uses_green_slick_stops():
    rows = [
        # counted: green slick stops at ages 18 and 22 -> median 20
        {"LapNumber": 18, "LapTime": 95.0, "PitInTime": _TS, "PitOutTime": pd.NaT,
         "TrackStatus": "1", "TyreLife": 18, "Compound": "MEDIUM"},
        {"LapNumber": 22, "LapTime": 95.0, "PitInTime": _TS, "PitOutTime": pd.NaT,
         "TrackStatus": "1", "TyreLife": 22, "Compound": "HARD"},
        # excluded: SC stop
        {"LapNumber": 30, "LapTime": 95.0, "PitInTime": _TS, "PitOutTime": pd.NaT,
         "TrackStatus": "4", "TyreLife": 30, "Compound": "MEDIUM"},
        # excluded: opening-lap incident stop
        {"LapNumber": 2, "LapTime": 95.0, "PitInTime": _TS, "PitOutTime": pd.NaT,
         "TrackStatus": "1", "TyreLife": 2, "Compound": "MEDIUM"},
        # excluded: switch to wets
        {"LapNumber": 25, "LapTime": 95.0, "PitInTime": _TS, "PitOutTime": pd.NaT,
         "TrackStatus": "1", "TyreLife": 25, "Compound": "INTERMEDIATE"},
    ]
    assert pace_metrics.typical_stop_age([FakeSession(_laps_df(rows))]) == pytest.approx(20.0)


def test_typical_stop_age_default_without_stops():
    no_stops = _laps_df(
        [{"LapNumber": 5, "LapTime": 90.0, "PitInTime": pd.NaT, "PitOutTime": pd.NaT,
          "TrackStatus": "1", "TyreLife": 5, "Compound": "MEDIUM"}]
    )
    assert pace_metrics.typical_stop_age([FakeSession(no_stops)], default=17.0) == 17.0


# --- overtaking_difficulty ---


def test_overtaking_difficulty_curated_ordering():
    assert pace_metrics.overtaking_difficulty("monaco") > pace_metrics.overtaking_difficulty("monza")
    assert pace_metrics.overtaking_difficulty("hungaroring") > pace_metrics.overtaking_difficulty("baku")


def test_overtaking_difficulty_unknown_circuit_default():
    assert pace_metrics.overtaking_difficulty("nordschleife") == 0.5
