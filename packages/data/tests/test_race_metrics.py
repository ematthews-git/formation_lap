"""Unit tests for the pure aggregation in formation_data.race_metrics.

No database or FastF1 — laps/results/weather are fabricated DataFrames in the collector's
shape (same style as test_strategies.py's fake frames).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from formation_data import race_metrics as rm

_LAP_FLAGS = {
    "is_sc": False, "is_vsc": False, "is_red": False, "is_yellow": False,
    "is_green": True, "is_inlap": False, "is_outlap": False,
    "is_accurate": True, "deleted": False,
}


def make_laps(rows: list[dict]) -> pd.DataFrame:
    """Build a per-lap frame. Each row: driver, lap, plus optional time/stint/compound/
    tyre_life/position and flag overrides (defaults = green racing lap)."""
    out = []
    for r in rows:
        row = {
            "driver": r["driver"],
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
        classified = r.get("classified", True)
        out.append({
            "driver": r["driver"],
            "grid": float(r.get("grid", 1)),
            "finish_position": float(r["finish"]) if r.get("finish") is not None else np.nan,
            "status": r.get("status", "Finished"),
            "points": float(r.get("points", 0)),
            "laps_completed": float(r.get("laps_completed", 50)),
            "race_time_s": r.get("race_time_s", np.nan),
            "gap_to_winner_s": r.get("gap", np.nan),
            "dns": r.get("dns", False),
            "classified": classified,
            "dnf": r.get("dnf", False),
        })
    return pd.DataFrame(out)


DRY = {"rainfall_any": False, "track_temp_min": 30.0, "track_temp_max": 40.0,
       "air_temp_min": 20.0, "air_temp_max": 24.0}


# --- race classification ---


def test_classify_dry():
    laps = make_laps([{"driver": "VER", "lap": 1, "compound": "MEDIUM"}])
    assert rm.race_features(laps, make_results([{"driver": "VER", "finish": 1}]), DRY)["class"] == "dry"


def test_classify_wet_from_wet_compound():
    laps = make_laps([{"driver": "VER", "lap": 1, "compound": "WET"}])
    feat = rm.race_features(laps, make_results([{"driver": "VER", "finish": 1}]), DRY)
    assert feat["class"] == "wet" and feat["is_dry"] is False


def test_classify_mixed_from_intermediate():
    laps = make_laps([{"driver": "VER", "lap": 1, "compound": "INTERMEDIATE"}])
    assert rm.race_features(laps, make_results([{"driver": "VER", "finish": 1}]), DRY)["class"] == "mixed"


def test_classify_mixed_from_rainfall():
    laps = make_laps([{"driver": "VER", "lap": 1, "compound": "MEDIUM"}])
    wet = {**DRY, "rainfall_any": True}
    assert rm.race_features(laps, make_results([{"driver": "VER", "finish": 1}]), wet)["class"] == "mixed"


# --- incidents ---


def test_sc_deployments_counts_separate_periods():
    # SC on laps 3-5 and 8-9 -> two deployments; VSC none.
    rows = []
    for lap in range(1, 11):
        sc = lap in (3, 4, 5, 8, 9)
        rows.append({"driver": "VER", "lap": lap, "is_sc": sc, "is_green": not sc})
    feat = rm.race_features(make_laps(rows), make_results([{"driver": "VER", "finish": 1}]), DRY)
    assert feat["sc_deployments"] == 2
    assert feat["sc_any"] is True and feat["vsc_any"] is False


def test_leading_sc_counts_as_one_deployment():
    rows = [{"driver": "VER", "lap": lap, "is_sc": lap <= 2, "is_green": lap > 2}
            for lap in range(1, 6)]
    feat = rm.race_features(make_laps(rows), make_results([{"driver": "VER", "finish": 1}]), DRY)
    assert feat["sc_deployments"] == 1


def test_yellow_laps_counted():
    rows = [{"driver": "VER", "lap": lap, "is_yellow": lap in (4, 5, 6)} for lap in range(1, 8)]
    feat = rm.race_features(make_laps(rows), make_results([{"driver": "VER", "finish": 1}]), DRY)
    assert feat["yellow_laps"] == 3


def test_dnf_and_lap1_dnf():
    laps = make_laps([{"driver": "VER", "lap": 1}, {"driver": "HAM", "lap": 1}])
    results = make_results([
        {"driver": "VER", "finish": 1, "classified": True},
        {"driver": "HAM", "finish": None, "classified": False, "dnf": True, "laps_completed": 1},
    ])
    feat = rm.race_features(laps, results, DRY)
    assert feat["n_dnf"] == 1 and feat["n_lap1_dnf"] == 1


# --- overtaking / position ---


def test_overtakes_counts_green_position_gains():
    # VER holds P1; HAM climbs 3 -> 2 -> 1 (two gains).
    laps = make_laps([
        {"driver": "VER", "lap": 1, "position": 1}, {"driver": "VER", "lap": 2, "position": 2},
        {"driver": "VER", "lap": 3, "position": 2},
        {"driver": "HAM", "lap": 1, "position": 3}, {"driver": "HAM", "lap": 2, "position": 2},
        {"driver": "HAM", "lap": 3, "position": 1},
    ])
    feat = rm.race_features(laps, make_results([{"driver": "HAM", "finish": 1}]), DRY)
    assert feat["overtakes"] == 2.0


def test_lap1_gains_from_grid_to_end_of_lap1():
    laps = make_laps([{"driver": "HAM", "lap": 1, "position": 2}])
    results = make_results([{"driver": "HAM", "grid": 5, "finish": 1}])  # gained 3 off the line
    assert rm.race_features(laps, results, DRY)["pos_changes_lap1"] == 3.0


# --- grid / finish ---


def test_winner_grid_and_pairs():
    laps = make_laps([{"driver": "VER", "lap": 1}, {"driver": "HAM", "lap": 1}])
    results = make_results([
        {"driver": "VER", "grid": 4, "finish": 1},
        {"driver": "HAM", "grid": 2, "finish": 2},
    ])
    feat = rm.race_features(laps, results, DRY)
    assert feat["winner_grid"] == 4.0
    assert sorted(feat["grid_finish_pairs"]) == [(2.0, 2.0), (4.0, 1.0)]


def test_podium_and_points_from_outside_top10():
    laps = make_laps([{"driver": "X", "lap": 1}])
    # P3 from grid 12 -> podium & points from outside top 10.
    results = make_results([{"driver": "X", "grid": 12, "finish": 3}])
    feat = rm.race_features(laps, results, DRY)
    assert feat["podium_outside_top10"] is True
    assert feat["points_outside_top10"] is True


# --- tyres (dry only) ---


def test_compound_and_stint_metrics_dry():
    laps = make_laps(
        [{"driver": "VER", "lap": lap, "stint": 1, "compound": "MEDIUM", "tyre_life": lap}
         for lap in range(1, 6)]
        + [{"driver": "VER", "lap": 6, "stint": 1, "compound": "MEDIUM", "tyre_life": 6, "is_inlap": True}]
        + [{"driver": "VER", "lap": lap, "stint": 2, "compound": "HARD", "tyre_life": lap - 6}
           for lap in range(7, 10)]
    )
    feat = rm.race_features(laps, make_results([{"driver": "VER", "finish": 1}]), DRY)
    assert feat["compound_laps"]["MEDIUM"] == 6  # 5 racing + in-lap (out-laps excluded)
    assert feat["compound_laps"]["HARD"] == 3
    assert feat["stint_max"] == 6  # stint 1 spans 6 laps
    assert feat["pit_ages"] == [6.0]


def test_tyre_metrics_empty_on_wet_race():
    laps = make_laps([{"driver": "VER", "lap": lap, "compound": "WET"} for lap in range(1, 6)])
    feat = rm.race_features(laps, make_results([{"driver": "VER", "finish": 1}]), DRY)
    assert feat["compound_laps"] == {} and feat["stint_max"] is None
    assert feat["pit_ages"] == [] and feat["stint_slopes"] == []


def test_stint_degradation_slope_positive():
    laps = make_laps([
        {"driver": "VER", "lap": lap, "stint": 1, "compound": "MEDIUM",
         "tyre_life": lap, "time": 90.0 + 0.2 * lap}
        for lap in range(1, 8)
    ])
    feat = rm.race_features(laps, make_results([{"driver": "VER", "finish": 1}]), DRY)
    assert feat["stint_slopes"] and feat["stint_slopes"][0] == pytest.approx(0.2, abs=1e-6)


# --- pit loss under SC/VSC ---


def test_sc_pit_loss_bucketed():
    laps = make_laps(
        [{"driver": "VER", "lap": lap, "time": 90.0} for lap in range(1, 6)]  # green pace ~90
        + [{"driver": "VER", "lap": 6, "time": 110.0, "is_inlap": True, "is_sc": True, "is_green": False}]
        + [{"driver": "VER", "lap": 7, "time": 100.0, "is_outlap": True, "is_sc": True, "is_green": False}]
    )
    feat = rm.race_features(laps, make_results([{"driver": "VER", "finish": 1}]), DRY)
    # loss = (110-90) + (100-90) = 30, bucketed under SC
    assert feat["sc_pit_losses"] == [pytest.approx(30.0)]
    assert feat["vsc_pit_losses"] == []


# --- timing ---


def test_timing_gaps():
    laps = make_laps([{"driver": d, "lap": 1} for d in ("VER", "X", "Y")])
    results = make_results([
        {"driver": "VER", "finish": 1, "race_time_s": 5400.0, "gap": 0.0},
        {"driver": "X", "finish": 10, "race_time_s": 5400.0, "gap": 45.5},
        {"driver": "Y", "finish": 15, "race_time_s": 5400.0, "gap": 80.0},
    ])
    feat = rm.race_features(laps, results, DRY)
    assert feat["race_duration_s"] == 5400.0
    assert feat["winner_to_p10_s"] == 45.5
    assert feat["winner_to_last_s"] == 80.0  # last classified = P15


# --- empty ---


def test_empty_laps_returns_none():
    assert rm.race_features(pd.DataFrame(), make_results([]), DRY) is None


# --- aggregate ---


def _feat(**over):
    base = {
        "class": "dry", "is_dry": True,
        "sc_any": False, "vsc_any": False, "red_any": False, "rain_any": False,
        "sc_deployments": 0, "vsc_deployments": 0, "yellow_laps": 0,
        "n_dnf": 0, "n_lap1_dnf": 0, "sc_pit_losses": [], "vsc_pit_losses": [],
        "overtakes": 0.0, "pos_changes_after_lap1": 0.0, "pos_changes_lap1": 0.0,
        "winner_grid": 1.0, "podium_outside_top10": False, "points_outside_top10": False,
        "grid_finish_pairs": [], "air_temp": None, "track_temp": None,
        "race_duration_s": None, "winner_to_p10_s": None, "winner_to_last_s": None,
        "compound_laps": {}, "stint_max": None, "pit_ages": [], "stint_slopes": [],
    }
    base.update(over)
    base["is_dry"] = base["class"] == "dry"  # keep the derived flag consistent
    return base


def test_aggregate_rates_and_counts():
    feats = [
        _feat(sc_any=True, n_dnf=2),
        _feat(sc_any=False, n_dnf=4),
    ]
    blob = rm.aggregate(feats, seasons=[2024, 2023])
    assert blob["meta"]["n_races"] == 2 and blob["meta"]["seasons"] == [2023, 2024]
    assert blob["incidents"]["sc_probability"] == 0.5
    assert blob["incidents"]["avg_retirements"] == 3.0


def test_aggregate_winner_grid_rates():
    feats = [_feat(winner_grid=1.0), _feat(winner_grid=7.0), _feat(winner_grid=4.0)]
    blob = rm.aggregate(feats, seasons=[2024])
    assert blob["grid"]["pole_to_win_rate"] == pytest.approx(1 / 3, abs=1e-3)
    assert blob["grid"]["winner_outside_top5_rate"] == pytest.approx(1 / 3, abs=1e-3)
    assert blob["grid"]["win_outside_top3_quali_rate"] == pytest.approx(2 / 3, abs=1e-3)


def test_aggregate_grid_map_and_correlation():
    # Perfect grid==finish across two races -> Spearman 1.0 and identity map.
    pairs = [(1.0, 1.0), (2.0, 2.0), (3.0, 3.0)]
    feats = [_feat(grid_finish_pairs=pairs), _feat(grid_finish_pairs=pairs)]
    blob = rm.aggregate(feats, seasons=[2024])
    assert blob["grid"]["quali_finish_correlation"] == pytest.approx(1.0)
    assert blob["grid"]["avg_finish_by_grid"] == {"1": 1.0, "2": 2.0, "3": 3.0}


def test_aggregate_compound_usage_normalised():
    feats = [_feat(compound_laps={"MEDIUM": 30, "HARD": 10})]
    blob = rm.aggregate(feats, seasons=[2024])
    assert blob["tyres"]["compound_usage_frequency"] == {"MEDIUM": 0.75, "HARD": 0.25}


def test_aggregate_weather_shares():
    feats = [_feat(**{"class": c}) for c in ("dry", "mixed", "wet", "dry")]
    blob = rm.aggregate(feats, seasons=[2024])
    assert blob["weather"]["dry_race_share"] == 0.5
    assert blob["weather"]["mixed_race_share"] == 0.25
    assert blob["weather"]["wet_race_share"] == 0.25
    assert blob["meta"]["n_dry"] == 2


def test_aggregate_empty_is_robust():
    blob = rm.aggregate([], seasons=[])
    assert blob["meta"]["n_races"] == 0
    assert blob["incidents"]["sc_probability"] is None
    assert blob["tyres"]["compound_usage_frequency"] == {}
    assert blob["grid"]["avg_finish_by_grid"] == {}
