"""Unit tests for the undercut/overcut model — synthetic two-car exchanges, no DB."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from formation_data.jobs.pre_season import undercut


class FakeSession:
    def __init__(self, laps):
        self.laps = laps


_TS = pd.Timestamp("2026-05-03 15:00")


def _driver_rows(driver, time_by_lap, in_lap, out_lap, status_by_lap=None, n_laps=14):
    status_by_lap = status_by_lap or {}
    rows = []
    for lap in range(1, n_laps + 1):
        rows.append(
            {
                "Driver": driver,
                "LapNumber": lap,
                "LapTime": 90.0,  # irrelevant to gap-based mining
                "Time": time_by_lap[lap],
                "PitInTime": _TS if lap == in_lap else pd.NaT,
                "PitOutTime": _TS if lap == out_lap else pd.NaT,
                "TrackStatus": status_by_lap.get(lap, "1"),
                "TyreLife": lap if lap < out_lap else lap - out_lap + 1,
                "Compound": "MEDIUM" if lap < out_lap else "HARD",
            }
        )
    return rows


def _undercut_session(gap_by_lap, a_status=None, b_status=None, n_laps=14):
    """A pits 10/11, B reacts 11/12. B's session Time = A's + gap_by_lap[lap]."""
    a_time = {lap: 90.0 * lap for lap in range(1, n_laps + 1)}
    b_time = {lap: 90.0 * lap + gap_by_lap[lap] for lap in range(1, n_laps + 1)}
    rows = _driver_rows("A", a_time, in_lap=10, out_lap=11, status_by_lap=a_status, n_laps=n_laps)
    rows += _driver_rows("B", b_time, in_lap=11, out_lap=12, status_by_lap=b_status, n_laps=n_laps)
    df = pd.DataFrame(rows)
    df["LapTime"] = pd.to_timedelta(df["LapTime"], unit="s")
    df["Time"] = pd.to_timedelta(df["Time"], unit="s")
    return FakeSession(df)


# Gap A->B: A ahead by 0.5 before the stops, growing to 2.0 after -> swing +1.5.
_GAP = {1: 0.5, 2: 0.5, 3: 0.5, 4: 0.5, 5: 0.5, 6: 0.5, 7: 0.5, 8: 0.5, 9: 0.5,
        10: 0.5, 11: 1.0, 12: 1.6, 13: 2.0, 14: 2.0}


# --- undercut_pairs ---


def test_undercut_pairs_detects_clean_exchange():
    pairs = undercut.undercut_pairs(_undercut_session(_GAP))
    assert len(pairs) == 1
    p = pairs[0]
    assert (p["a"], p["b"], p["reaction"]) == ("A", "B", 1)
    # gap_after(lap13)=2.0 minus gap_before(lap9)=0.5
    assert p["swing"] == pytest.approx(1.5)
    assert p["swap"] is False  # A was already ahead


def test_undercut_pairs_skips_safety_car_window():
    # SC (status 4) on B's out-lap disqualifies the exchange.
    pairs = undercut.undercut_pairs(_undercut_session(_GAP, b_status={12: "4"}))
    assert pairs == []


def test_undercut_pairs_skips_cars_not_fighting():
    far = dict(_GAP)
    for lap in range(1, 11):
        far[lap] = 5.0  # 5s apart before the stops -> not a real fight
    assert undercut.undercut_pairs(_undercut_session(far)) == []


def test_undercut_pairs_records_position_swap():
    # A starts 0.8s behind (gap negative) and ends 0.7s ahead -> swap True.
    gap = {lap: -0.8 for lap in range(1, 11)}
    gap.update({11: -0.3, 12: 0.2, 13: 0.7, 14: 0.7})
    pairs = undercut.undercut_pairs(_undercut_session(gap))
    assert len(pairs) == 1
    assert pairs[0]["swap"] is True
    assert pairs[0]["swing"] == pytest.approx(1.5)


# --- undercut_laptime_swing (model-driven) ---


def test_undercut_laptime_swing_formula():
    # deg * (stop_age - fresh) - warmup = 0.08*18 - 0.8
    assert undercut.undercut_laptime_swing(0.08, 0.8, 20.0) == pytest.approx(0.08 * 18 - 0.8)


def test_undercut_laptime_swing_nan_deg():
    assert np.isnan(undercut.undercut_laptime_swing(float("nan"), 0.8, 20.0))


def test_undercut_laptime_swing_nan_warmup_is_zero_penalty():
    assert undercut.undercut_laptime_swing(0.08, float("nan"), 20.0) == pytest.approx(0.08 * 18)


# --- empirical_summary (diagnostic cross-check) ---


def test_empirical_summary_reports_mined_pairs():
    out = undercut.empirical_summary([_undercut_session(_GAP)])
    assert out["n"] == 1
    assert out["median_swing"] == pytest.approx(1.5)
    assert out["swap_rate"] == 0.0  # A was already ahead


def test_empirical_summary_no_pairs():
    far = dict(_GAP)
    for lap in range(1, 11):
        far[lap] = 5.0
    out = undercut.empirical_summary([_undercut_session(far)])
    assert out["n"] == 0
    assert np.isnan(out["median_swing"])
    assert out["swap_rate"] is None


# --- Layer 2 strength ---


def test_undercut_strength_scales_with_overtaking_difficulty():
    hard = undercut.undercut_strength(1.0, overtaking_difficulty=1.0)
    easy = undercut.undercut_strength(1.0, overtaking_difficulty=0.0)
    assert hard == pytest.approx(1.0)            # full value where passing is impossible
    assert easy == pytest.approx(undercut.K_FLOOR)  # floored value where passing is trivial
    assert hard > easy


def test_undercut_strength_clamps_negative_swing():
    assert undercut.undercut_strength(-0.5, overtaking_difficulty=0.8) == 0.0


def test_overcut_strength_is_undercut_mirror():
    # Negative swing (staying out wins) becomes overcut strength.
    assert undercut.overcut_strength(-1.0, overtaking_difficulty=1.0) == pytest.approx(1.0)
    assert undercut.overcut_strength(1.0, overtaking_difficulty=1.0) == 0.0


def test_nan_swing_yields_zero_strength():
    assert undercut.undercut_strength(float("nan"), 0.8) == 0.0
    assert undercut.overcut_strength(float("nan"), 0.8) == 0.0
