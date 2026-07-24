"""Unit tests for the pure trace builder in formation_data.race_trace.

No database or FastF1 — laps/results are fabricated DataFrames in the collector's shape
(same style as test_race_metrics.py's fake frames).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from formation_data import race_metrics as rm
from formation_data import race_trace as rt

_LAP_FLAGS = {
    "is_sc": False, "is_vsc": False, "is_red": False, "is_yellow": False,
    "is_green": True, "is_inlap": False, "is_outlap": False,
    "is_accurate": True, "deleted": False,
}


def make_laps(rows: list[dict]) -> pd.DataFrame:
    """Build a per-lap frame. Each row: driver, lap, plus optional time/team/number/
    compound/position and flag overrides (defaults = green racing lap)."""
    out = []
    for r in rows:
        row = {
            "driver": r["driver"],
            "driver_number": str(r.get("number", 99)),
            "team": r.get("team", "TeamX"),
            "lap_number": float(r["lap"]),
            "lap_time_s": float(r.get("time", 90.0)),
            "stint": float(r.get("stint", 1)),
            "compound": r.get("compound", "MEDIUM"),
            "tyre_life": float(r.get("tyre_life", r["lap"])),
            "position": float(r.get("position", 1)),
            **_LAP_FLAGS,
        }
        for k in _LAP_FLAGS:
            if k in r:
                row[k] = r[k]
        out.append(row)
    df = pd.DataFrame(out)
    df["total_laps"] = df["lap_number"].max() if len(df) else 0
    return df


def make_results(rows: list[dict]) -> pd.DataFrame:
    out = []
    for r in rows:
        out.append({
            "driver": r["driver"],
            "team": r.get("team", "TeamX"),
            "grid": float(r.get("grid", 1)),
            "finish_position": float(r["finish"]) if r.get("finish") is not None else np.nan,
            "status": r.get("status", "Finished"),
            "points": float(r.get("points", 0)),
            "laps_completed": float(r.get("laps_completed", 50)),
            "race_time_s": np.nan,
            "gap_to_winner_s": np.nan,
            "dns": r.get("dns", False),
            "classified": r.get("classified", True),
            "dnf": r.get("dnf", False),
        })
    return pd.DataFrame(out)


def two_driver_race(n_laps: int, sc_laps: set[int] = frozenset()) -> pd.DataFrame:
    rows = []
    for lap in range(1, n_laps + 1):
        for code, num, team, pos in (("VER", 1, "Red Bull", 1), ("HAM", 44, "Mercedes", 2)):
            rows.append({
                "driver": code, "number": num, "team": team, "lap": lap,
                "position": pos,
                "is_sc": lap in sc_laps, "is_green": lap not in sc_laps,
            })
    return make_laps(rows)


TWO_RESULTS = [
    {"driver": "VER", "team": "Red Bull", "finish": 1},
    {"driver": "HAM", "team": "Mercedes", "finish": 2},
]


# --- track status ---


def test_status_precedence_and_length():
    laps = make_laps([
        {"driver": "VER", "lap": 1, "is_yellow": True, "is_green": False},
        {"driver": "HAM", "lap": 1, "is_sc": True, "is_green": False},  # sc beats yellow
        {"driver": "VER", "lap": 2, "is_vsc": True, "is_green": False},
        {"driver": "HAM", "lap": 2},
        {"driver": "VER", "lap": 3},
        {"driver": "HAM", "lap": 3},
    ])
    assert rt.status_by_lap(laps, 3) == ["sc", "vsc", "green"]


def test_status_red_wins():
    laps = make_laps([{"driver": "VER", "lap": 1, "is_red": True, "is_sc": True, "is_green": False}])
    assert rt.status_by_lap(laps, 1) == ["red"]


# --- overtakes ---


def test_passes_by_lap_sums_to_race_total():
    # VER and HAM swap on lap 2→3 and back on lap 4→5.
    rows = []
    order = {1: (1, 2), 2: (1, 2), 3: (2, 1), 4: (2, 1), 5: (1, 2)}
    for lap, (pv, ph) in order.items():
        rows.append({"driver": "VER", "lap": lap, "position": pv})
        rows.append({"driver": "HAM", "lap": lap, "position": ph})
    laps = make_laps(rows)
    per_lap = rm.passes_by_lap(laps)
    assert per_lap == {3: 1, 5: 1}
    assert rm._on_track_passes(laps) == 2.0


def test_passes_exclude_pit_cycle():
    # HAM "gains" a place only because VER pits (in-lap) — not an on-track pass.
    rows = [
        {"driver": "VER", "lap": 1, "position": 1},
        {"driver": "HAM", "lap": 1, "position": 2},
        {"driver": "VER", "lap": 2, "position": 1, "is_inlap": True},
        {"driver": "HAM", "lap": 2, "position": 2},
        {"driver": "VER", "lap": 3, "position": 2, "is_outlap": True},
        {"driver": "HAM", "lap": 3, "position": 1},
    ]
    assert rm.passes_by_lap(make_laps(rows)) == {}


# --- telemetry-based overtakes (durable lead changes) ---


def _progress(rows: dict[str, list[tuple[float, float, int]]]) -> dict:
    """Build a progress dict: {driver: [(t, prog, lap), ...]}."""
    return {
        drv: pd.DataFrame(pts, columns=["t", "prog", "lap"])
        for drv, pts in rows.items()
    }


def _flat_laps(codes: list[str], n_laps: int, **overrides) -> pd.DataFrame:
    """Minimal laps frame carrying only the exclusion flags overtakes_by_lap reads."""
    rows = []
    for c in codes:
        for lap in range(1, n_laps + 1):
            r = {"driver": c, "lap": lap, "position": 1}
            for key, laps_set in overrides.get(c, {}).items():
                if lap in laps_set:
                    r[key] = True
            rows.append(r)
    return make_laps(rows)


def test_overtakes_durable_swap_counts_once():
    # B is behind A, passes at t=20 and holds well beyond the 8s dwell → one pass on lap 2
    # (lap 1 is excluded as the start scramble, tested separately below).
    a = [(t, 1.0 + t * 0.001, 2) for t in range(0, 60, 2)]
    b = [(t, 1.0 + t * 0.001 + (-0.02 if t < 20 else 0.02), 2) for t in range(0, 60, 2)]
    prog = _progress({"A": a, "B": b})
    laps = _flat_laps(["A", "B"], 2)
    assert rt.overtakes_by_lap(prog, laps, dwell_s=8.0) == {2: 1}


def test_overtakes_flipflop_below_dwell_not_counted():
    # A and B trade the lead every 4s (below the 8s dwell) — a side-by-side scrap that
    # must not inflate. No swap persists long enough to confirm a change.
    a, b = [], []
    for t in range(0, 80, 2):
        lead = (t // 4) % 2 == 0  # flips every 4s
        off = 0.02 if lead else -0.02
        a.append((t, t * 0.001 + off, 1))
        b.append((t, t * 0.001 - off, 1))
    prog = _progress({"A": a, "B": b})
    assert sum(rt.overtakes_by_lap(prog, _flat_laps(["A", "B"], 1), dwell_s=8.0).values()) == 0


def test_overtakes_excludes_lap1_start_scramble():
    # A durable swap on lap 1 (the standing-start scramble) is not counted; the same
    # swap on a later lap is.
    a1 = [(t, t * 0.001, 1) for t in range(0, 60, 2)]
    b1 = [(t, t * 0.001 + (-0.02 if t < 20 else 0.02), 1) for t in range(0, 60, 2)]
    assert rt.overtakes_by_lap(_progress({"A": a1, "B": b1}), _flat_laps(["A", "B"], 1),
                               dwell_s=8.0) == {}
    a2 = [(t, 1.0 + t * 0.001, 2) for t in range(0, 60, 2)]
    b2 = [(t, 1.0 + t * 0.001 + (-0.02 if t < 20 else 0.02), 2) for t in range(0, 60, 2)]
    assert rt.overtakes_by_lap(_progress({"A": a2, "B": b2}), _flat_laps(["A", "B"], 2),
                               dwell_s=8.0) == {2: 1}


def test_overtakes_excludes_swaps_under_sc():
    # Swap on lap 2 (past the start), but under the safety car → excluded.
    a = [(t, 1.0 + t * 0.001, 2) for t in range(0, 60, 2)]
    b = [(t, 1.0 + t * 0.001 + (-0.02 if t < 20 else 0.02), 2) for t in range(0, 60, 2)]
    prog = _progress({"A": a, "B": b})
    laps = _flat_laps(["A", "B"], 2, A={"is_sc": {2}}, B={"is_sc": {2}})
    assert rt.overtakes_by_lap(prog, laps, dwell_s=8.0) == {}


def test_overtakes_falls_back_to_lap_resolution_without_telemetry():
    # No progress → lap-resolution passes_by_lap, so a race still gets a count.
    rows = []
    order = {1: (1, 2), 2: (1, 2), 3: (2, 1), 4: (2, 1)}
    for lap, (pv, ph) in order.items():
        rows.append({"driver": "VER", "lap": lap, "position": pv})
        rows.append({"driver": "HAM", "lap": lap, "position": ph})
    laps = make_laps(rows)
    assert rt.overtakes_by_lap({}, laps) == rm.passes_by_lap(laps) == {3: 1}


# --- weather ---


def test_weather_dry_race():
    laps = two_driver_race(3)
    assert rt.weather_by_lap(laps, {}, 3) == ["dry", "dry", "dry"]


def test_weather_rainfall_marks_damp():
    laps = two_driver_race(3)
    assert rt.weather_by_lap(laps, {2: True}, 3) == ["dry", "damp", "dry"]


def test_weather_compound_majority():
    rows = []
    for code in ("VER", "HAM", "LEC"):
        rows.append({"driver": code, "lap": 1, "compound": "INTERMEDIATE"})
        rows.append({"driver": code, "lap": 2, "compound": "WET"})
        rows.append({"driver": code, "lap": 3, "compound": "MEDIUM"})
    laps = make_laps(rows)
    assert rt.weather_by_lap(laps, {}, 3) == ["damp", "wet", "dry"]


# --- build_trace ---


def test_build_trace_shape_and_team_snapshot():
    laps = two_driver_race(5)
    trace = rt.build_trace(
        laps, make_results(TWO_RESULTS), {},
        season=2023, round_number=10, event_name="British Grand Prix",
    )
    assert trace is not None
    assert trace["version"] == rt.TRACE_VERSION
    assert trace["total_laps"] == 5
    for key in ("track_status", "weather", "excitement", "overtakes"):
        assert len(trace[key]) == 5
    ver = trace["drivers"][0]
    # Team comes from the race's own results — the period-correct snapshot.
    assert ver["code"] == "VER" and ver["team"] == "Red Bull"
    assert ver["finish_pos"] == 1 and ver["classified"] is True
    assert len(ver["lap_times"]) == 5


def test_build_trace_dnf_null_padded_and_pits():
    rows = []
    for lap in range(1, 6):
        rows.append({"driver": "VER", "number": 1, "team": "Red Bull", "lap": lap,
                     "is_inlap": lap == 3})
        if lap <= 2:  # HAM retires after lap 2
            rows.append({"driver": "HAM", "number": 44, "team": "Mercedes", "lap": lap,
                         "position": 2})
    results = make_results([
        {"driver": "VER", "team": "Red Bull", "finish": 1},
        {"driver": "HAM", "team": "Mercedes", "finish": 19, "classified": False, "dnf": True},
    ])
    trace = rt.build_trace(make_laps(rows), results, {},
                           season=2022, round_number=1, event_name="X")
    assert trace is not None
    ver, ham = trace["drivers"]
    assert ver["pit_laps"] == [3]
    assert ham["classified"] is False
    assert ham["lap_times"][:2] == [90.0, 90.0]
    assert ham["lap_times"][2:] == [None, None, None]


def test_build_trace_drops_start_procedure_pit_visits():
    # Aborted start: laps 1-3 behind the SC route the field through the pits
    # (FastF1 records in-laps); the real stop on lap 5 survives.
    rows = []
    for lap in range(1, 10):
        sc = lap <= 3
        rows.append({
            "driver": "VER", "number": 1, "team": "Red Bull", "lap": lap,
            "is_sc": sc, "is_green": not sc,
            "is_inlap": lap in (2, 3, 5),
        })
    results = make_results([{"driver": "VER", "team": "Red Bull", "finish": 1}])
    trace = rt.build_trace(make_laps(rows), results, {},
                           season=2025, round_number=1, event_name="X")
    assert trace["drivers"][0]["pit_laps"] == [5]


def test_build_trace_second_car_by_number():
    rows = []
    for lap in range(1, 7):
        rows.append({"driver": "VER", "number": 1, "team": "Red Bull", "lap": lap, "position": 1})
        rows.append({"driver": "TSU", "number": 22, "team": "Red Bull", "lap": lap, "position": 2})
    results = make_results([
        {"driver": "VER", "team": "Red Bull", "finish": 1},
        {"driver": "TSU", "team": "Red Bull", "finish": 2},
    ])
    trace = rt.build_trace(make_laps(rows), results, {},
                           season=2025, round_number=1, event_name="X")
    by_code = {d["code"]: d for d in trace["drivers"]}
    assert by_code["VER"]["second_car"] is False
    assert by_code["TSU"]["second_car"] is True


def test_build_trace_skips_dns_and_unusable():
    laps = two_driver_race(5)
    results = make_results(TWO_RESULTS + [
        {"driver": "HUL", "team": "Haas", "finish": None, "dns": True, "classified": False},
    ])
    trace = rt.build_trace(laps, results, {}, season=2021, round_number=2, event_name="X")
    assert [d["code"] for d in trace["drivers"]] == ["VER", "HAM"]
    assert rt.build_trace(make_laps([]), results, {},
                          season=2021, round_number=2, event_name="X") is None


def test_build_trace_rejects_race_that_never_raced():
    # 2021 Spa: a handful of laps entirely behind the SC — nothing worth tracing.
    laps = two_driver_race(4, sc_laps={1, 2, 3, 4})
    trace = rt.build_trace(laps, make_results(TWO_RESULTS), {},
                           season=2021, round_number=12, event_name="Belgian Grand Prix")
    assert trace is None


# --- excitement ---


def test_excitement_bounds_and_events():
    sc_laps = {5, 6}
    laps = two_driver_race(10, sc_laps=sc_laps)
    trace = rt.build_trace(laps, make_results(TWO_RESULTS), {},
                           season=2024, round_number=3, event_name="X")
    exc = trace["excitement"]
    assert all(0 <= v <= 100 for v in exc)
    assert len(exc) == 10
    # Deploy (lap 5) spikes above quiet running (lap 4); running under SC (lap 6) is
    # duller than the deploy; the restart (lap 7) spikes again.
    assert exc[4] > exc[3]
    assert exc[5] < exc[4]
    assert exc[6] > exc[5]


def test_excitement_deterministic():
    laps = two_driver_race(6)
    results = make_results(TWO_RESULTS)
    a = rt.build_trace(laps, results, {}, season=2024, round_number=3, event_name="X")
    b = rt.build_trace(laps, results, {}, season=2024, round_number=3, event_name="X")
    assert a == b


def test_excitement_red_restart_bumps_like_sc_restart():
    # A red flag on lap 5 then a green restart on lap 6 spikes the restart lap, same as an
    # SC restart would (bunched field, cold tyres) — not only ``prev == "sc"``.
    laps = two_driver_race(10)
    status = ["green"] * 10
    status[4] = "red"  # lap 5 red-flagged, lap 6 is the restart
    trace = rt.build_trace(laps, make_results(TWO_RESULTS), {}, season=2021,
                           round_number=1, event_name="X", status=status)
    exc = trace["excitement"]
    assert exc[5] > exc[6]  # restart lap (6) more exciting than the plain lap after it


# --- authoritative track status (windows -> laps) ---


def test_status_from_windows_restart_lap_is_green():
    # Half-open overlap: lap 3 starts exactly when the red window ends, so it is NOT
    # neutralised — it is the (green) restart lap, not one lap late.
    windows = pd.DataFrame(
        [(0.0, 100.0, "green"), (100.0, 200.0, "red"), (200.0, 300.0, "green")],
        columns=["t_start", "t_end", "status"],
    )
    bounds = {1: (0.0, 100.0), 2: (100.0, 200.0), 3: (200.0, 300.0)}
    assert rt._status_from_windows(windows, bounds, 3) == ["green", "red", "green"]


def test_status_from_windows_worst_status_and_uniform():
    # A lap overlapping two windows takes the worse (sc > vsc); a lap with no data is green.
    windows = pd.DataFrame(
        [(0.0, 50.0, "vsc"), (50.0, 120.0, "sc"), (120.0, 300.0, "green")],
        columns=["t_start", "t_end", "status"],
    )
    bounds = {1: (0.0, 100.0), 2: (120.0, 200.0)}  # lap 1 spans vsc+sc, lap 2 fully green
    assert rt._status_from_windows(windows, bounds, 3) == ["sc", "green", "green"]


def test_status_by_lap_prefers_windows_over_flags():
    # Per-lap flags say lap 2 is green for both cars, but the authoritative window puts an
    # SC across lap 2's time span → lap 2 is sc (a mid-lap deployment some cars missed).
    rows = []
    for lap, (lo, hi) in {1: (0, 90), 2: (90, 180), 3: (180, 270)}.items():
        for drv in ("VER", "HAM"):
            rows.append({"driver": drv, "lap": lap})
    laps = make_laps(rows)
    laps["lap_start_s"] = laps["lap_number"].map({1: 0.0, 2: 90.0, 3: 180.0})
    laps["lap_end_s"] = laps["lap_number"].map({1: 90.0, 2: 180.0, 3: 270.0})
    windows = pd.DataFrame(
        [(0.0, 90.0, "green"), (90.0, 180.0, "sc"), (180.0, 400.0, "green")],
        columns=["t_start", "t_end", "status"],
    )
    assert rt.status_by_lap(laps, 3, windows=windows) == ["green", "sc", "green"]


def test_red_restart_laps_after_each_red_block():
    # First racing (green/yellow) lap after a red block, plus the lap after it; sc/vsc laps
    # in between are skipped, not treated as the restart.
    assert rt._red_restart_laps(
        ["green", "red", "red", "green", "green"]
    ) == {4, 5}
    assert rt._red_restart_laps(
        ["green", "red", "sc", "green"]  # red -> sc -> green: restart is the green lap
    ) == {4, 5}


# --- overtake counter: neutralisation, DNF, jitter, no-netting ---


def test_overtakes_excludes_race_level_neutralised_lap():
    # A swap completes on lap 3, which is race-level SC even though the pair's own lap flags
    # read green (only some cars carried the code). It must not count.
    a = [(t, 2.0 + t * 0.001, 3) for t in range(0, 60, 2)]
    b = [(t, 2.0 + t * 0.001 + (-0.02 if t < 20 else 0.02), 3) for t in range(0, 60, 2)]
    prog = _progress({"A": a, "B": b})
    laps = _flat_laps(["A", "B"], 3)  # all-green per-driver flags
    assert rt.overtakes_by_lap(prog, laps, status=["green", "green", "sc"]) == {}
    # control: race-level green -> the same swap counts
    assert rt.overtakes_by_lap(prog, laps, status=["green", "green", "green"]) == {3: 1}


def test_overtakes_suppresses_dying_car():
    # B slows on lap 2 (its last) and is passed — the field streaming past a retiring car is
    # not a racing overtake.
    a = [(t, 1.0 + t * 0.001, 2) for t in range(0, 60, 2)]
    b = [(t, 1.0 + t * 0.001 + (0.02 if t < 20 else -0.02), 2) for t in range(0, 60, 2)]
    prog = _progress({"A": a, "B": b})
    laps = _flat_laps(["A", "B"], 2)
    dnf = make_results([
        {"driver": "A", "finish": 1},
        {"driver": "B", "finish": 19, "classified": False, "dnf": True, "laps_completed": 2},
    ])
    assert rt.overtakes_by_lap(prog, laps, results=dnf) == {}
    # control: B finishes -> the pass counts
    ok = make_results([
        {"driver": "A", "finish": 1},
        {"driver": "B", "finish": 2, "laps_completed": 2},
    ])
    assert rt.overtakes_by_lap(prog, laps, results=ok) == {2: 1}


def test_overtakes_nose_to_tail_jitter_not_counted():
    # Two cars glued within a few car-lengths (gap below min_sep) whose order flips every 12s
    # (past the dwell): telemetry jitter, not passes. None count.
    a, b = [], []
    for t in range(0, 120, 2):
        off = 0.003 if (t // 12) % 2 == 0 else -0.003  # < min_sep (~0.0056 at a 90s lap)
        a.append((t, 1.0 + t * 0.001, 2))
        b.append((t, 1.0 + t * 0.001 - off, 2))
    prog = _progress({"A": a, "B": b})
    assert sum(rt.overtakes_by_lap(prog, _flat_laps(["A", "B"], 2)).values()) == 0


def test_overtakes_counts_every_real_pass_without_netting():
    # A and B trade the lead three times, each drawing clear (0.02 > min_sep) and holding past
    # the dwell. All three count — the durable-event counter does NOT net them to one (which a
    # lap-to-lap position diff would). This is the property the counter exists to preserve.
    a, b = [], []
    for t in range(0, 120, 2):
        off = 0.02 if (t // 30) % 2 == 0 else -0.02  # phases: +,-,+,- over 120s = 3 swaps
        a.append((t, 1.0 + t * 0.001, 2))
        b.append((t, 1.0 + t * 0.001 - off, 2))
    prog = _progress({"A": a, "B": b})
    assert rt.overtakes_by_lap(prog, _flat_laps(["A", "B"], 2)) == {2: 3}
