"""Undercut / overcut strength — a two-layer model on top of the tyre model.

The undercut is a two-car move: the attacker pits first, then uses fresh-tyre pace to jump
a rival who reacts a lap or two later. Its strength is set by how much faster a fresh set is
than the rival's worn set — i.e. the tyre model, not the pit lane (which cancels between two
cars in the same lane) or fuel (both cars are on the same race laps).

Layer 1 — ``undercut_laptime_swing``: the on-track time (s) gained across the exchange,
derived from the circuit's tyre model — ``degradation × (stop_age − fresh_age) − warm-up``.
This is computed from thousands of clean laps (``pace_metrics.tyre_model``), which is far
more accurate than mining two-car gap swings: those carry ~1s/lap of tow/dirty-air scatter
and only ~10 pairs/circuit exist, so the median is dominated by noise (it even gets some
circuits' sign wrong). The pair miner (``undercut_pairs`` / ``empirical_summary``) is kept
only as a *diagnostic* cross-check, not as the source of the stored value.

Layer 2 — ``undercut_strength``: scales the Layer-1 swing by how *decisive* it is, i.e.
overtaking difficulty (a big swing on an easy-to-pass track is reversible, so worth less).
``overcut_strength`` is the mirror: the advantage to the car that stays out / pits later.

Pure functions over loaded FastF1 sessions — no DB or network. Tested in
``tests/test_undercut.py``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from formation_data.jobs.pre_season import pace_model

# Fresh-tyre age (laps) the undercutting car runs on the key lap.
FRESH_AGE = 2
# Floor on decisiveness: even where passing is trivial, a raw time gain has some value.
K_FLOOR = 0.4

# --- Diagnostic pair miner (cross-check only; does NOT drive undercut_strength) ---
# Two cars within this on-track gap (s) before the stops count as a genuine fight.
GAP_THRESHOLD = 2.5
# The rival must react within this many laps for the exchange to be a real undercut.
MAX_REACTION = 2
# Physically implausible single-exchange swings are tow/DRS flybys or incidents — dropped.
MAX_SWING = 4.0


# --- Layer 1: model-driven swing ---


def undercut_laptime_swing(
    deg_rate: float, warmup_penalty: float, typical_stop_age: float, fresh_age: int = FRESH_AGE
) -> float:
    """Single-exchange undercut swing (s) from the circuit's tyre model.

    The undercutting car runs a fresh set (``fresh_age``) against a rival on a
    ``typical_stop_age``-lap-old set: it gains the rival's accumulated degradation but pays
    its own fresh-tyre warm-up penalty. Positive ⇒ the undercut gains time; negative ⇒ the
    overcut wins. A NaN warm-up (too few fresh laps) is treated as no penalty; a NaN deg
    (no usable tyre data) yields NaN.
    """
    if not np.isfinite(deg_rate):
        return float("nan")
    warmup = warmup_penalty if np.isfinite(warmup_penalty) else 0.0
    return deg_rate * max(0.0, typical_stop_age - fresh_age) - warmup


# --- Diagnostic: empirical pair mining (cross-check only, does not drive strength) ---


def _green_pit_stops(laps: pd.DataFrame) -> dict[str, list[tuple[int, int]]]:
    """Per driver, the (in_lap, out_lap) of each normal slick→slick green stop.

    Keyed off PitInTime/PitOutTime; the out-lap must be the very next lap and land on
    a slick (drops red-flag tyre swaps and switches to wets).
    """
    stops: dict[str, list[tuple[int, int]]] = {}
    for drv, d in laps.groupby("Driver"):
        d = d.sort_values("LapNumber")
        by_lap = d.set_index("LapNumber")
        drv_stops = []
        for in_lap in d.loc[d["PitInTime"].notna(), "LapNumber"]:
            out_lap = int(in_lap) + 1
            if out_lap not in by_lap.index:
                continue
            out_row = by_lap.loc[out_lap]
            if pd.isna(out_row["PitOutTime"]):
                continue
            if out_row.get("Compound") not in pace_model.SLICKS:
                continue
            drv_stops.append((int(in_lap), out_lap))
        stops[drv] = drv_stops
    return stops


def _gap(pivot: pd.DataFrame, lap: int, a: str, b: str) -> float | None:
    """On-track gap (s) from A to B at ``lap`` (positive = A ahead); None if missing."""
    if lap not in pivot.index or a not in pivot.columns or b not in pivot.columns:
        return None
    ta, tb = pivot.at[lap, a], pivot.at[lap, b]
    if pd.isna(ta) or pd.isna(tb):
        return None
    return float(tb - ta)


def _all_green(status: pd.DataFrame, drv: str, lo: int, hi: int) -> bool:
    """True if every lap in [lo, hi] for ``drv`` is full green (no SC/VSC/red)."""
    if drv not in status.columns:
        return False
    for lap in range(lo, hi + 1):
        if lap not in status.index:
            return False
        s = status.at[lap, drv]
        if pd.isna(s) or any(c in str(s) for c in "4567"):
            return False
    return True


def undercut_pairs(
    session, gap_threshold: float = GAP_THRESHOLD, max_reaction: int = MAX_REACTION
) -> list[dict]:
    """Mine clean undercut exchanges from one race session.

    For each ordered pair (A, B) where A pits on lap N, B reacts on lap N+1..N+max,
    they ran *stably* close before A's stop (within ``gap_threshold`` at both N-1 and
    N-2, so a tow/DRS-train flyby doesn't masquerade as a fight), both ran green
    throughout the window, and the resulting swing is physically plausible
    (``|swing| <= MAX_SWING``): record the gap swing and whether A came out ahead.

        gap_before = gap at A's lap N-1
        gap_after  = gap one lap after B's out-lap (both past their single stop, so the
                     pit-lane transit cancels and only on-track pace remains)
        swing      = gap_after - gap_before   (positive = A gained by undercutting)
    """
    laps = pace_model.to_seconds(session.laps).sort_values(["Driver", "LapNumber"])
    pivot = pace_model.time_pivot(laps)
    status = laps.pivot_table(
        index="LapNumber", columns="Driver", values="TrackStatus", aggfunc="first"
    )
    stops = _green_pit_stops(laps)

    pairs = []
    for a, a_stops in stops.items():
        for in_a, _ in a_stops:
            before_lap = in_a - 1
            for b, b_stops in stops.items():
                if b == a:
                    continue
                for in_b, out_b in b_stops:
                    if not (1 <= in_b - in_a <= max_reaction):
                        continue
                    after_lap = out_b + 1
                    g_before = _gap(pivot, before_lap, a, b)
                    g_prev = _gap(pivot, before_lap - 1, a, b)  # stability check
                    g_after = _gap(pivot, after_lap, a, b)
                    if g_before is None or g_prev is None or g_after is None:
                        continue
                    if abs(g_before) > gap_threshold or abs(g_prev) > gap_threshold:
                        continue
                    if not (
                        _all_green(status, a, before_lap, after_lap)
                        and _all_green(status, b, before_lap, after_lap)
                    ):
                        continue
                    swing = g_after - g_before
                    if abs(swing) > MAX_SWING:
                        continue  # tow/DRS flyby, traffic or incident — not a tyre swing
                    pairs.append(
                        {
                            "a": a,
                            "b": b,
                            "reaction": int(in_b - in_a),
                            "swing": swing,
                            "swap": bool(g_before < 0 and g_after > 0),
                        }
                    )
    return pairs


def empirical_summary(sessions) -> dict:
    """Diagnostic cross-check: mined undercut exchanges across the sessions.

    Returns ``{"median_swing", "n", "swap_rate"}`` (swap_rate = fraction where the
    earlier-pitting car came out ahead). Reported alongside the model in `diagnose`; the
    binary swap-rate is more robust to gap noise than the seconds-swing, but neither drives
    the stored ``undercut_strength``.
    """
    swings, swaps = [], []
    for session in sessions:
        for p in undercut_pairs(session):
            swings.append(p["swing"])
            swaps.append(p["swap"])
    return {
        "median_swing": float(np.median(swings)) if swings else float("nan"),
        "n": len(swings),
        "swap_rate": float(np.mean(swaps)) if swaps else None,
    }


# --- Layer 2: effective strength ---


def _decisiveness(overtaking_difficulty: float, k_floor: float = K_FLOOR) -> float:
    """Map overtaking difficulty (0..1) to a swing multiplier in [k_floor, 1]."""
    return k_floor + (1.0 - k_floor) * overtaking_difficulty


def undercut_strength(
    laptime_swing: float, overtaking_difficulty: float, k_floor: float = K_FLOOR
) -> float:
    """Layer 2: the swing scaled by how decisive it is. Clamped at 0."""
    if not np.isfinite(laptime_swing):
        return 0.0
    return max(0.0, laptime_swing) * _decisiveness(overtaking_difficulty, k_floor)


def overcut_strength(
    laptime_swing: float, overtaking_difficulty: float, k_floor: float = K_FLOOR
) -> float:
    """Mirror of the undercut: advantage to the later-pitting car. Clamped at 0.

    When fresh rubber can't be deployed (cold/slow-warmup, low-deg circuits) the
    lap-time swing goes negative — staying out wins — and that becomes the overcut.
    """
    if not np.isfinite(laptime_swing):
        return 0.0
    return max(0.0, -laptime_swing) * _decisiveness(overtaking_difficulty, k_floor)
