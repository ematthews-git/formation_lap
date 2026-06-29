"""Shared lap-data utilities for the pre-season pace metrics.

Pure pandas helpers over a FastF1 ``session.laps`` DataFrame — no DB or network —
so the undercut model (``undercut.py``) and the feeder metrics (``pace_metrics.py``)
share one definition of "a clean lap", "reference pace", "a stint", and "the gap
between two cars". Unit-tested in ``tests/test_pace_model.py``.

FastF1 ``laps`` columns used here:
- ``LapNumber``   lap counter within the race
- ``LapTime``     Timedelta; NaT for in/out laps and invalid laps
- ``Time``        Timedelta of session time when the lap was completed (line crossing) —
                  the difference between two cars at the same LapNumber is their on-track gap
- ``PitInTime`` / ``PitOutTime``  Timedelta markers; identify in-laps and out-laps
- ``TrackStatus`` string of status digits (1 green, 4 SC, 5 red, 6/7 VSC)
- ``Compound`` / ``TyreLife``     tyre identity and age (laps) on the current set
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Track-status digits that mean "not racing at full pace": 4 SC, 5 red, 6/7 VSC.
NEUTRALISED = "[4567]"
SLICKS = {"SOFT", "MEDIUM", "HARD"}
WETS = {"INTERMEDIATE", "WET"}
# A lap with less than this gap (s) to the car ahead is in dirty air — its pace is
# inflated by the wake, so it's excluded from tyre-pace measurement.
CLEAN_AIR_GAP = 1.0


def to_seconds(laps: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with ``LapTime_s`` (and ``Time_s`` when ``Time`` is present)."""
    d = laps.copy()
    d["LapTime_s"] = d["LapTime"].dt.total_seconds()
    if "Time" in d.columns:
        d["Time_s"] = d["Time"].dt.total_seconds()
    return d


def green_flying(laps: pd.DataFrame) -> pd.DataFrame:
    """Green-flag flying laps: valid time, no in/out-lap, no SC/VSC/red, TyreLife>1.

    Accepts raw or ``to_seconds``-normalised laps; adds ``LapTime_s`` if missing.
    """
    d = laps if "LapTime_s" in laps.columns else to_seconds(laps)
    return d[
        d["LapTime_s"].notna()
        & d["PitInTime"].isna()
        & d["PitOutTime"].isna()
        & ~d["TrackStatus"].astype(str).str.contains(NEUTRALISED, regex=True)
        & (d["TyreLife"] > 1)
    ]


def reference_pace(laps: pd.DataFrame, min_cars: int = 4) -> pd.Series:
    """Median green-flying lap time (s) per LapNumber from cars staying out.

    The cross-field pace per lap moves with fuel burn and track evolution, so the
    residual of a car's lap against this reference is fuel/track-neutral — the basis
    for isolating tyre degradation. Laps with fewer than ``min_cars`` samples are
    dropped (too noisy to anchor on). Returned Series is indexed by LapNumber.
    """
    on_track = green_flying(laps)
    if on_track.empty:
        return pd.Series(dtype=float)
    agg = on_track.groupby("LapNumber")["LapTime_s"].agg(["median", "count"])
    return agg.loc[agg["count"] >= min_cars, "median"]


def add_stint_id(driver_laps: pd.DataFrame) -> pd.Series:
    """Stint index per lap for a *single* driver, incremented at each out-lap.

    Keys off PitOutTime, never FastF1's unreliable ``Stint`` counter. Expects the
    rows pre-sorted by LapNumber. Stint 0 is the opening stint.
    """
    return driver_laps["PitOutTime"].notna().cumsum()


def time_pivot(laps: pd.DataFrame) -> pd.DataFrame:
    """LapNumber × Driver table of session ``Time_s`` (cumulative time at the line).

    ``pivot.loc[lap, B] - pivot.loc[lap, A]`` is the on-track gap (s) from A to B at
    that lap: positive when A is ahead (B crosses the line later).
    """
    d = laps if "Time_s" in laps.columns else to_seconds(laps)
    return d.pivot_table(index="LapNumber", columns="Driver", values="Time_s")


def slick(laps: pd.DataFrame) -> pd.DataFrame:
    """Laps run on a dry (slick) compound — drops intermediate/wet running."""
    return laps[laps["Compound"].isin(SLICKS)]


def add_gap_to_ahead(laps: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with ``GapAhead_s``: the gap (s) to the car directly ahead on
    each lap (NaN for the lap leader). Needs ``Time_s`` (added if absent)."""
    d = laps if "Time_s" in laps.columns else to_seconds(laps)
    d = d.sort_values(["LapNumber", "Time_s"]).copy()
    # within each lap, cars are ordered by track position; the diff to the previous
    # car's line-crossing time is the gap to the car ahead.
    d["GapAhead_s"] = d.groupby("LapNumber")["Time_s"].diff()
    return d


def clean_air(laps: pd.DataFrame, min_gap: float = CLEAN_AIR_GAP) -> pd.DataFrame:
    """Keep only clean-air laps: the leader each lap, or cars ≥ ``min_gap`` behind."""
    d = laps if "GapAhead_s" in laps.columns else add_gap_to_ahead(laps)
    return d[d["GapAhead_s"].isna() | (d["GapAhead_s"] >= min_gap)]


def least_squares_slope(x, y) -> float:
    """Slope of the best-fit line ``y ~ x``; NaN if fewer than 2 distinct x values."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    if len(x) < 2 or np.ptp(x) == 0:
        return float("nan")
    return float(np.polyfit(x, y, 1)[0])
