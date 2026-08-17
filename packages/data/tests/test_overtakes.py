"""Unit tests for the pure overtake detector in formation_data.overtakes.

No database or FastF1 — track positions, laps and results are fabricated frames in the
shape ``formation_sim.data.track_position`` produces (same style as test_race_trace.py).

The circuit is a synthetic 1000 m oval; cars advance at a steady 50 m/s unless a test
says otherwise, so a lap takes 20 s and the durability rules have room to bite.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from formation_data import overtakes as ov

L = 1000.0  # synthetic lap length, metres
V = 50.0  # nominal speed, m/s
DT = 1.0

_LAP_FLAGS = {
    "is_sc": False, "is_vsc": False, "is_red": False, "is_yellow": False,
    "is_green": True, "is_inlap": False, "is_outlap": False,
    "is_accurate": True, "deleted": False,
}


def positions(offsets: dict[str, list[float]], *, t0: float = 0.0,
              speed: dict[str, list[float]] | None = None,
              off_line: dict[str, list[float]] | None = None) -> dict[str, pd.DataFrame]:
    """Build track positions from per-driver race-distance series.

    ``offsets[code][k]`` is that driver's race distance at sample ``k``; lap and s follow
    from it, which is exactly the relationship the real frame carries.
    """
    out = {}
    for code, rd in offsets.items():
        rd = np.asarray(rd, dtype=float)
        t = t0 + np.arange(len(rd)) * DT
        v = np.asarray(speed[code], dtype=float) if speed and code in speed \
            else np.full(len(rd), V * 3.6)
        o = np.asarray(off_line[code], dtype=float) if off_line and code in off_line \
            else np.zeros(len(rd))
        out[code] = pd.DataFrame({
            "t": t,
            "s": np.mod(rd, L),
            "lap": np.floor(np.maximum(rd, 0.0) / L) + 1.0,
            "race_dist": rd,
            "speed": v,
            "drs": np.zeros(len(rd)),
            "off_line": o,
        })
    return out


def make_laps(codes, n_laps: int, **per_driver) -> pd.DataFrame:
    """Minimal laps frame: one row per driver-lap, with optional pit stamps."""
    rows = []
    for c in codes:
        for lap in range(1, n_laps + 1):
            r = {"driver": c, "lap_number": float(lap), "position": 1.0,
                 "lap_time_s": L / V, "lap_start_s": (lap - 1) * L / V,
                 "lap_end_s": lap * L / V, "pit_in_s": np.nan, "pit_out_s": np.nan,
                 **_LAP_FLAGS}
            for key, mapping in (per_driver.get(c) or {}).items():
                if lap in mapping:
                    r[key] = mapping[lap]
            rows.append(r)
    return pd.DataFrame(rows)


def ramp(start: float, n: int, v: float = V) -> list[float]:
    return [start + v * DT * k for k in range(n)]


def swap(n: int, at: int, lead: float = 30.0) -> tuple[list[float], list[float]]:
    """Two cars a hair apart; B goes ahead of A at sample ``at`` and stays there."""
    a = ramp(0.0, n)
    b = [x + (-lead if k < at else lead) for k, x in enumerate(ramp(0.0, n))]
    return a, b


def detect(pos, laps, **kw):
    kw.setdefault("track_length_m", L)
    return ov.detect_overtakes(pos, laps, **kw)


def kinds(events):
    out = {}
    for e in events:
        out[e["kind"]] = out.get(e["kind"], 0) + 1
    return out


# --- the core rule -----------------------------------------------------------------


def test_durable_swap_after_the_start_counts_once():
    # Launch phase is over well before sample 60 (the leader clears 15% of lap 1 in the
    # first few samples), so this is a plain racing pass.
    a, b = swap(120, at=60)
    ev = detect(positions({"A": a, "B": b}), make_laps(["A", "B"], 7))
    assert kinds(ev) == {ov.KIND_RACING: 1}
    assert (ev[0]["gainer"], ev[0]["loser"]) == ("B", "A")


def test_lunge_that_does_not_stick_is_not_a_pass():
    # B leads for 3 s then drops back — below min_dwell_s, and it never survives to the
    # line, so neither durability rule is met.
    a = ramp(0.0, 120)
    b = [x + (30.0 if 60 <= k < 63 else -30.0) for k, x in enumerate(ramp(0.0, 120))]
    assert detect(positions({"A": a, "B": b}), make_laps(["A", "B"], 7)) == []


def test_swap_must_survive_to_the_line_not_just_the_dwell():
    # B leads for 8 s (past the 5 s dwell) but A retakes before the lap ends. Counting on
    # dwell alone would score this; the official rule — hold it to the start/finish line —
    # is what stops a corner-by-corner scrap inflating the total.
    a = ramp(0.0, 120)
    b = [x + (30.0 if 60 <= k < 68 else -30.0) for k, x in enumerate(ramp(0.0, 120))]
    assert detect(positions({"A": a, "B": b}), make_laps(["A", "B"], 7)) == []


def test_repeated_genuine_passes_each_count():
    # A pass, then a re-pass a full lap later. Both stick to their own line crossing, so
    # both are real and neither nets the other away.
    n = 200
    a = ramp(0.0, n)
    b = []
    for k, x in enumerate(ramp(0.0, n)):
        b.append(x + (-30.0 if k < 60 else 30.0 if k < 140 else -30.0))
    ev = detect(positions({"A": a, "B": b}), make_laps(["A", "B"], 11))
    assert kinds(ev) == {ov.KIND_RACING: 2}


# --- classification ----------------------------------------------------------------


def test_pit_stop_position_change_is_not_an_overtake():
    a, b = swap(120, at=60)
    laps = make_laps(["A", "B"], 7, A={"pit_in_s": {3: 55.0}, "pit_out_s": {4: 75.0}})
    ev = detect(positions({"A": a, "B": b}), laps)
    assert kinds(ev) == {ov.KIND_PIT: 1}


def test_racing_either_side_of_a_pit_stop_still_counts():
    # The old counter dropped the whole in-lap and out-lap. Here A pits around t=60 and is
    # genuinely passed at t=200, long after rejoining — that pass is racing.
    a, b = swap(300, at=200)
    laps = make_laps(["A", "B"], 16,
                     A={"pit_in_s": {3: 55.0}, "pit_out_s": {4: 75.0}})
    ev = detect(positions({"A": a, "B": b}), laps)
    assert kinds(ev) == {ov.KIND_RACING: 1}


def test_crossing_between_cars_a_lap_apart_is_discarded():
    # Ranking by race distance already keeps a lapped car a full lap behind, so a crossing
    # between two cars a lap apart can only come from a corrupt position signal — Monaco's
    # tunnel drops GPS, and the projection jumps. Such an event must never be counted.
    a = ramp(500.0, 120)  # crossing lands mid-lap, nowhere near the line
    b = [x + (-30.0 if k < 60 else 30.0) for k, x in enumerate(ramp(500.0, 120))]
    pos = positions({"A": a, "B": b})
    pos["B"]["lap"] = pos["B"]["lap"] + 1.0  # B is a lap up on the timing feed
    ev = detect(pos, make_laps(["A", "B"], 13))
    assert ov.KIND_RACING not in kinds(ev)
    assert kinds(ev) == {ov.KIND_LAPPED: 1}


def test_nose_to_tail_across_the_line_still_counts():
    # The two cars disagree about the lap number for a second or two while they straddle
    # the start/finish line. They are metres apart and racing; the lapped guard must not
    # swallow the pass.
    a = ramp(940.0, 120)
    b = [x + (-30.0 if k < 60 else 30.0) for k, x in enumerate(ramp(940.0, 120))]
    ev = detect(positions({"A": a, "B": b}), make_laps(["A", "B"], 8))
    assert kinds(ev) == {ov.KIND_RACING: 1}


def test_swap_under_safety_car_is_not_an_overtake():
    a, b = swap(120, at=60)
    windows = pd.DataFrame([(0.0, 40.0, "green"), (40.0, 200.0, "sc")],
                           columns=["t_start", "t_end", "status"])
    ev = detect(positions({"A": a, "B": b}), make_laps(["A", "B"], 7),
                status_windows=windows)
    assert kinds(ev) == {ov.KIND_NEUTRALISED: 1}


def test_standing_start_shuffle_is_not_an_overtake():
    # The swap happens 2 s in, while the leader is still short of the opening corners.
    a, b = swap(120, at=2)
    ev = detect(positions({"A": a, "B": b}), make_laps(["A", "B"], 7))
    assert kinds(ev) == {ov.KIND_START: 1}


def test_racing_later_on_lap_one_still_counts():
    # Everything after the launch phase on lap 1 is real racing — the old rule threw the
    # whole opening lap away. Lap 1 ends at sample 20 here; the pass lands at 15.
    a, b = swap(60, at=15)
    ev = detect(positions({"A": a, "B": b}), make_laps(["A", "B"], 4))
    assert kinds(ev) == {ov.KIND_RACING: 1}
    assert ev[0]["lap"] == 1


# --- attrition ---------------------------------------------------------------------


def test_car_crawling_when_passed_is_attrition_not_racing():
    # A's speed collapses to a fifth of its norm right where it is passed.
    n = 120
    a = ramp(0.0, n)
    b = [x + (-30.0 if k < 60 else 30.0) for k, x in enumerate(ramp(0.0, n))]
    spd = {"A": [V * 3.6 if k < 55 else V * 3.6 * 0.15 for k in range(n)]}
    ev = detect(positions({"A": a, "B": b}, speed=spd), make_laps(["A", "B"], 7))
    assert kinds(ev) == {ov.KIND_ATTRITION: 1}


def test_whole_field_streaming_past_one_car_is_one_car_in_trouble():
    # Four cars go by A inside a few seconds. That is not four racing moves — it is the
    # failure mode that made the old counter's totals unusable.
    # A crawls from t=58; B-E hold station relative to each other and simply arrive, so
    # every event here involves A and none of them is B-vs-C.
    n = 160
    a = []
    d = 0.0
    for k in range(n):
        d += (V if k < 58 else V * 0.15) * DT
        a.append(d)
    pos = {"A": a}
    for i, c in enumerate("BCDE"):
        pos[c] = ramp(-60.0 - i * 40.0, n)
    ev = detect(positions(pos), make_laps(list("ABCDE"), 9))
    assert ov.KIND_RACING not in kinds(ev)
    assert kinds(ev).get(ov.KIND_ATTRITION, 0) == 4
    assert {e["loser"] for e in ev} == {"A"}


def test_passing_a_retiring_car_is_attrition():
    a, b = swap(120, at=60)
    results = pd.DataFrame([{"driver": "A", "dnf": True, "laps_completed": 4.0},
                            {"driver": "B", "dnf": False, "laps_completed": 7.0}])
    ev = detect(positions({"A": a, "B": b}), make_laps(["A", "B"], 7), results=results)
    assert kinds(ev) == {ov.KIND_ATTRITION: 1}


def test_car_off_the_racing_line_is_attrition():
    n = 120
    a = ramp(0.0, n)
    b = [x + (-30.0 if k < 60 else 30.0) for k, x in enumerate(ramp(0.0, n))]
    off = {"A": [0.0 if k < 55 else 40.0 for k in range(n)]}
    ev = detect(positions({"A": a, "B": b}, off_line=off), make_laps(["A", "B"], 7))
    assert kinds(ev) == {ov.KIND_ATTRITION: 1}


# --- corroboration by the official feed ---------------------------------------------


def test_swap_the_official_feed_never_saw_is_rejected():
    # Telemetry says the order changed; F1's classification feed says it never did. That is
    # coordinate noise, and no threshold on the telemetry alone separates it from a pass.
    a, b = swap(120, at=60)
    official = pd.concat([
        pd.DataFrame({"t": [0.0, 100.0], "driver": "A", "position": [1.0, 1.0]}),
        pd.DataFrame({"t": [0.0, 100.0], "driver": "B", "position": [2.0, 2.0]}),
    ])
    assert detect(positions({"A": a, "B": b}), make_laps(["A", "B"], 7),
                  official=official) == []


def test_swap_the_official_feed_confirms_is_kept():
    a, b = swap(120, at=60)
    official = pd.concat([
        pd.DataFrame({"t": [0.0, 61.0], "driver": "A", "position": [1.0, 2.0]}),
        pd.DataFrame({"t": [0.0, 61.0], "driver": "B", "position": [2.0, 1.0]}),
    ])
    ev = detect(positions({"A": a, "B": b}), make_laps(["A", "B"], 7), official=official)
    assert kinds(ev) == {ov.KIND_RACING: 1}


# --- attribution and the stored blob -------------------------------------------------


def test_event_is_attributed_to_the_nearest_corner():
    corners = pd.DataFrame({"Number": [1, 2, 3], "Letter": ["", "", ""],
                            "s": [100.0, 500.0, 900.0]})
    a, b = swap(120, at=60)
    ev = detect(positions({"A": a, "B": b}), make_laps(["A", "B"], 7), corners=corners)
    assert len(ev) == 1
    # sample 60 puts the pair at race distance 3000 m -> s = 0 -> corner 1 wraps closest.
    assert ev[0]["corner"] in (1, 3)
    assert ev[0]["s"] is not None


def test_summarise_splits_racing_from_gross():
    events = [
        {"kind": ov.KIND_RACING, "lap": 2, "corner": 4, "corner_letter": ""},
        {"kind": ov.KIND_RACING, "lap": 2, "corner": 4, "corner_letter": ""},
        {"kind": ov.KIND_ATTRITION, "lap": 3, "corner": 1, "corner_letter": ""},
        {"kind": ov.KIND_LAPPED, "lap": 3, "corner": 1, "corner_letter": ""},
        {"kind": ov.KIND_PIT, "lap": 4, "corner": 1, "corner_letter": ""},
        {"kind": ov.KIND_START, "lap": 1, "corner": 1, "corner_letter": ""},
    ]
    s = ov.summarise(events, total_laps=5)
    assert s["totals"]["racing"] == 2
    # gross adds attrition and lapping (a car really did go past) but never pit or start.
    assert s["totals"]["gross"] == 4
    assert s["by_lap"] == [0, 2, 0, 0, 0]
    assert s["by_corner"] == {"4": 2}


def test_no_telemetry_yields_no_events():
    assert ov.detect_overtakes({}, make_laps(["A"], 3)) == []
