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
