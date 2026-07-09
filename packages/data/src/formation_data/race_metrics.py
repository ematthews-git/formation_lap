"""Empirical per-circuit race analytics — pure aggregation over collected FastF1 frames.

The observed-history counterpart to the sim's dry-only, model-derived context numbers: given
the tidy per-race frames the collector already produces (``session_laps`` / ``session_results``
/ ``weather_summary``), :func:`race_features` reduces one race to a flat feature dict, and
:func:`aggregate` rolls a circuit's races (every race, wet included, over the trailing window)
into the grouped stats blob persisted to ``circuit_race_stats``.

Nothing here touches FastF1, the DB, or the sim — it's pure pandas/numpy over the canonical
frames, so it's unit-testable with fabricated DataFrames. Conventions:
  * rates/probabilities are fractions in ``[0, 1]``; counts and seconds are absolute.
  * "deployments" are rising edges of the per-lap SC/VSC flags (one continuous period = one).
  * tyre metrics are computed on DRY races only, so they stay meaningful.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SLICKS = ("SOFT", "MEDIUM", "HARD")
POINTS_CUTOFF = 10  # a top-10 finish scores points
TOP10_GRID = 10  # "outside the top 10" on the grid
_MAX_PIT_LOSS_S = 80.0  # guard: in/out-lap deltas above this are garbage (SC laps run slow)
_MIN_STINT_LAPS = 4  # laps needed to fit a stint degradation slope


def _r(x, n=3):
    """Round to ``n`` dp, mapping None/NaN to None (JSON-friendly)."""
    if x is None:
        return None
    x = float(x)
    return None if not np.isfinite(x) else round(x, n)


def _b(series) -> pd.Series:
    """Coerce a (possibly nullable-boolean) flag column to a plain bool Series."""
    return series.astype("boolean").fillna(False).astype(bool)


# --------------------------------------------------------------------------- per-race helpers
def _rising_edges(flag_by_lap: pd.Series) -> int:
    """Number of False→True transitions in a lap-ordered boolean series (a leading True,
    e.g. a standing-start behind the SC, counts as one edge)."""
    b = flag_by_lap.to_numpy(dtype=bool)
    if b.size == 0:
        return 0
    prev = np.concatenate(([False], b[:-1]))
    return int(np.sum(b & ~prev))


def _classify_race(laps: pd.DataFrame, rainfall: bool) -> str:
    """dry / mixed / wet from compound usage and rainfall: WET tyres → wet; INTERs or any
    rainfall → mixed; otherwise dry."""
    compounds = set(laps["compound"].dropna().astype(str))
    if "WET" in compounds:
        return "wet"
    if "INTERMEDIATE" in compounds or rainfall:
        return "mixed"
    return "dry"


def _neutralised_pace(laps: pd.DataFrame, flag: str, min_laps: int = 3) -> float | None:
    """Median circulating lap time under a caution (``flag`` = is_sc / is_vsc), excluding
    in/out laps — the pace a car pitting under that caution is measured against. None if the
    caution had too few full laps to establish a baseline."""
    times = laps.loc[laps[flag] & ~laps["is_inlap"] & ~laps["is_outlap"], "lap_time_s"].dropna()
    return float(times.median()) if len(times) >= min_laps else None


def _pit_losses(laps: pd.DataFrame) -> dict[str, list[float]]:
    """Per-stop time loss for stops made under SC / VSC, measured against that caution's
    NEUTRALISED circulating pace: ``(in-lap − pace) + (out-lap − pace)``. Pitting under a
    caution is cheap precisely because the whole field is slowed, so baselining against the
    caution pace (not green pace) is what makes this come out below the sim's green pit loss.
    Green-flag stops are left to the sim's per-weekend estimate."""
    out: dict[str, list[float]] = {"sc": [], "vsc": []}
    pace = {"sc": _neutralised_pace(laps, "is_sc"), "vsc": _neutralised_pace(laps, "is_vsc")}
    for _, g in laps.groupby("driver"):
        g = g.sort_values("lap_number")
        for _, il in g[g["is_inlap"]].iterrows():
            nxt = g[(g["lap_number"] == il["lap_number"] + 1) & g["is_outlap"]]
            if not len(nxt):
                continue
            ol = nxt.iloc[0]
            it, ot = il["lap_time_s"], ol["lap_time_s"]
            if not (pd.notna(it) and pd.notna(ot)):
                continue
            if bool(il["is_sc"]) or bool(ol["is_sc"]):
                bucket = "sc"
            elif bool(il["is_vsc"]) or bool(ol["is_vsc"]):
                bucket = "vsc"
            else:
                continue
            base = pace[bucket]
            if base is None:
                continue
            loss = (it - base) + (ot - base)
            if 0.0 < loss < _MAX_PIT_LOSS_S:
                out[bucket].append(float(loss))
    return out


def _on_track_passes(laps: pd.DataFrame) -> float:
    """On-track overtakes: over each pair of consecutive green racing laps, the number of car
    pairs — both circulating (neither on an in/out lap) — that swap order. Counting only mutual
    green-lap order reversals excludes the pit-cycle churn a naive lap-to-lap position-gain sum
    counts as passes (a car promoted because a rival pitted was not overtaken on track)."""
    racing = laps[
        laps["is_green"] & ~laps["is_inlap"] & ~laps["is_outlap"] & laps["position"].notna()
    ]
    if not len(racing):
        return 0.0
    piv = racing.pivot_table(
        index="lap_number", columns="driver", values="position", aggfunc="first"
    ).sort_index()
    lap_nums = piv.index.to_numpy()
    passes = 0
    for i in range(len(lap_nums) - 1):
        if lap_nums[i + 1] != lap_nums[i] + 1:
            continue  # only truly consecutive laps (a gap means a car was pitting / lapped out)
        a = piv.iloc[i].to_numpy(dtype=float)
        b = piv.iloc[i + 1].to_numpy(dtype=float)
        valid = np.isfinite(a) & np.isfinite(b)
        pa, pb = a[valid], b[valid]
        # For each car x, count rivals y it was behind (pa[x] > pa[y]) and is now ahead of
        # (pb[x] < pb[y]) — each is one completed on-track pass. Self-compare is never a hit.
        for x in range(len(pa)):
            passes += int(np.sum((pa[x] > pa) & (pb[x] < pb)))
    return float(passes)


def _lap1_position_changes(laps: pd.DataFrame, results: pd.DataFrame) -> float:
    """Number of cars whose position at the end of lap 1 differs from their grid slot — the
    size of the start-line shuffle."""
    lap1 = laps.loc[laps["lap_number"] == 1, ["driver", "position"]]
    if not len(lap1):
        return 0.0
    m = lap1.merge(results[["driver", "grid"]], on="driver", how="inner")
    changed = m["grid"].notna() & m["position"].notna() & (m["grid"] != m["position"])
    return float(changed.sum())


def _post_lap1_position_changes(laps: pd.DataFrame, results: pd.DataFrame) -> float:
    """Number of classified cars whose finishing position differs from their position at the
    end of lap 1 — how much the order reshuffles across the race once the start has settled."""
    lap1 = laps.loc[laps["lap_number"] == 1, ["driver", "position"]].rename(
        columns={"position": "p1"}
    )
    if not len(lap1):
        return 0.0
    fin = results.loc[_b(results["classified"]), ["driver", "finish_position"]]
    m = lap1.merge(fin, on="driver", how="inner")
    changed = m["p1"].notna() & m["finish_position"].notna() & (m["p1"] != m["finish_position"])
    return float(changed.sum())


def _stint_slopes(laps: pd.DataFrame) -> list[float]:
    """Per-stint OLS slope of lap time vs tyre age (s/lap) on clean green laps — the observed
    within-stint trend, net of fuel burn (which pulls it down)."""
    clean = laps[
        laps["is_green"] & ~laps["is_inlap"] & ~laps["is_outlap"]
        & _b(laps["is_accurate"]) & ~_b(laps["deleted"])
    ]
    slopes: list[float] = []
    for _, g in clean.groupby(["driver", "stint"]):
        x = g["tyre_life"].to_numpy(dtype=float)
        y = g["lap_time_s"].to_numpy(dtype=float)
        ok = np.isfinite(x) & np.isfinite(y)
        if ok.sum() < _MIN_STINT_LAPS or np.ptp(x[ok]) < 1:
            continue
        slopes.append(float(np.polyfit(x[ok], y[ok], 1)[0]))
    return slopes


def race_features(laps: pd.DataFrame, results: pd.DataFrame, weather: dict) -> dict | None:
    """Reduce one race's frames to a flat feature dict, or None if the race has no laps.

    ``laps`` / ``results`` follow the collector's ``session_laps`` / ``session_results`` shape;
    ``weather`` its ``weather_summary`` dict. Flag columns may be nullable-boolean.
    """
    if laps is None or not len(laps):
        return None
    laps = laps.copy()
    for col in ("is_sc", "is_vsc", "is_red", "is_yellow", "is_green", "is_inlap", "is_outlap"):
        laps[col] = _b(laps[col])
    rainfall = bool(weather.get("rainfall_any", False))
    race_class = _classify_race(laps, rainfall)
    is_dry = race_class == "dry"

    by_lap = laps.groupby("lap_number")
    classified = results[_b(results["classified"])] if len(results) else results
    winners = classified[classified["finish_position"] == 1]
    winner_grid = float(winners["grid"].iloc[0]) if len(winners) else None

    # Classified (grid, finish) pairs for the grid→finish map + quali/finish correlation.
    gf = classified[(classified["grid"] >= 1) & (classified["finish_position"] >= 1)]
    grid_finish = list(zip(gf["grid"].astype(float), gf["finish_position"].astype(float)))

    podium_out10 = bool(
        len(gf[(gf["finish_position"] <= 3) & (gf["grid"] > TOP10_GRID)])
    )
    points_out10 = bool(
        len(gf[(gf["finish_position"] <= POINTS_CUTOFF) & (gf["grid"] > TOP10_GRID)])
    )

    dnf = _b(results["dnf"]) if len(results) else pd.Series(dtype=bool)
    laps_done = results.get("laps_completed")
    n_lap1_dnf = int((dnf & (laps_done <= 1)).sum()) if laps_done is not None else 0

    pit = _pit_losses(laps)

    # Timing: race_time_s is the winner's total (same on every row); gaps are to the winner.
    race_duration = _first_finite(results.get("race_time_s"))
    winner_to_p10 = _gap_at(results, 10)
    last_pos = classified["finish_position"].max() if len(classified) else np.nan
    winner_to_last = _gap_at(results, last_pos) if np.isfinite(last_pos) else None

    tt = _mid(weather.get("track_temp_min"), weather.get("track_temp_max"))
    at = _mid(weather.get("air_temp_min"), weather.get("air_temp_max"))

    feat = {
        "class": race_class,
        "is_dry": is_dry,
        "sc_any": bool(laps["is_sc"].any()),
        "vsc_any": bool(laps["is_vsc"].any()),
        "red_any": bool(laps["is_red"].any()),
        "rain_any": rainfall,
        "sc_deployments": _rising_edges(by_lap["is_sc"].any().sort_index()),
        "vsc_deployments": _rising_edges(by_lap["is_vsc"].any().sort_index()),
        "yellow_laps": int(by_lap["is_yellow"].any().sum()),
        "n_dnf": int(dnf.sum()),
        "n_lap1_dnf": n_lap1_dnf,
        "sc_pit_losses": pit["sc"],
        "vsc_pit_losses": pit["vsc"],
        "overtakes": _on_track_passes(laps),
        "pos_changes_after_lap1": _post_lap1_position_changes(laps, results),
        "pos_changes_lap1": _lap1_position_changes(laps, results),
        "winner_grid": winner_grid,
        "podium_outside_top10": podium_out10,
        "points_outside_top10": points_out10,
        "grid_finish_pairs": grid_finish,
        "air_temp": at,
        "track_temp": tt,
        "race_duration_s": race_duration,
        "winner_to_p10_s": winner_to_p10,
        "winner_to_last_s": winner_to_last,
        # dry-only tyre inputs (empty on wet/mixed races)
        "compound_laps": _compound_laps(laps) if is_dry else {},
        "stint_max": _max_stint(laps) if is_dry else None,
        "pit_ages": _pit_ages(laps) if is_dry else [],
        "stint_slopes": _stint_slopes(laps) if is_dry else [],
    }
    return feat


def _first_finite(series) -> float | None:
    if series is None:
        return None
    for v in series:
        if pd.notna(v) and np.isfinite(float(v)):
            return float(v)
    return None


def _gap_at(results: pd.DataFrame, position: float) -> float | None:
    """Gap to the winner (s) for the finisher in ``position``, or None if lapped/absent."""
    if "gap_to_winner_s" not in results or not np.isfinite(position):
        return None
    row = results[results["finish_position"] == position]
    if not len(row):
        return None
    v = row["gap_to_winner_s"].iloc[0]
    return float(v) if pd.notna(v) and np.isfinite(float(v)) else None


def _mid(lo, hi) -> float | None:
    vals = [float(v) for v in (lo, hi) if v is not None and pd.notna(v) and np.isfinite(float(v))]
    return sum(vals) / len(vals) if vals else None


def _compound_laps(laps: pd.DataFrame) -> dict[str, int]:
    """Slick-compound lap counts (racing laps only, out-laps excluded)."""
    racing = laps[~laps["is_outlap"]]
    counts = racing["compound"].value_counts()
    return {c: int(counts.get(c, 0)) for c in SLICKS if counts.get(c, 0) > 0}


def _max_stint(laps: pd.DataFrame) -> int | None:
    """Longest stint (in laps) run on a slick compound."""
    slick = laps[laps["compound"].isin(SLICKS)]
    if not len(slick):
        return None
    return int(slick.groupby(["driver", "stint"]).size().max())


def _pit_ages(laps: pd.DataFrame) -> list[float]:
    """Tyre age (laps) at each green-flag pit stop (in-lap tyre_life on a slick)."""
    inlaps = laps[laps["is_inlap"] & laps["compound"].isin(SLICKS)]
    return [float(v) for v in inlaps["tyre_life"] if pd.notna(v) and np.isfinite(float(v))]


# --------------------------------------------------------------------------- cross-race rollup
def _mean(vals) -> float | None:
    vals = [float(v) for v in vals if v is not None and np.isfinite(float(v))]
    return sum(vals) / len(vals) if vals else None


def _rate(flags) -> float | None:
    flags = [bool(f) for f in flags]
    return sum(flags) / len(flags) if flags else None


def aggregate(features: list[dict], *, seasons: list[int]) -> dict:
    """Roll per-race feature dicts into the grouped ``circuit_race_stats`` blob.

    Robust to an empty list (returns a blob whose metric groups are all None/empty). Rates are
    fractions in [0, 1]; ``avg_finish_by_grid`` maps each grid slot (as a string key) to the
    mean classified finish across the window; ``quali_finish_correlation`` is Spearman ρ over
    all pooled (grid, finish) pairs.
    """
    dry = [f for f in features if f["is_dry"]]
    n = len(features)

    winner_grids = [f["winner_grid"] for f in features if f["winner_grid"] is not None]
    pairs = [p for f in features for p in f["grid_finish_pairs"]]
    compound_laps = _pool_compounds(dry)
    stint_slopes = [s for f in dry for s in f["stint_slopes"]]
    pit_ages = [a for f in dry for a in f["pit_ages"]]
    stint_maxes = [f["stint_max"] for f in dry if f["stint_max"] is not None]
    sc_losses = [x for f in features for x in f["sc_pit_losses"]]
    vsc_losses = [x for f in features for x in f["vsc_pit_losses"]]

    return {
        "meta": {
            "n_races": n,
            "n_dry": len(dry),
            "seasons": sorted(seasons),
        },
        "incidents": {
            "sc_probability": _r(_rate(f["sc_any"] for f in features)),
            "vsc_probability": _r(_rate(f["vsc_any"] for f in features)),
            "red_flag_probability": _r(_rate(f["red_any"] for f in features)),
            "avg_sc_deployments": _r(_mean(f["sc_deployments"] for f in features), 2),
            "avg_vsc_deployments": _r(_mean(f["vsc_deployments"] for f in features), 2),
            "avg_yellow_flag_laps": _r(_mean(f["yellow_laps"] for f in features), 1),
            "avg_retirements": _r(_mean(f["n_dnf"] for f in features), 2),
            "avg_lap1_dnfs": _r(_mean(f["n_lap1_dnf"] for f in features), 2),
        },
        "pit": {
            "sc_pit_loss_s": _r(np.median(sc_losses) if sc_losses else None, 1),
            "vsc_pit_loss_s": _r(np.median(vsc_losses) if vsc_losses else None, 1),
        },
        "overtaking": {
            "avg_overtakes_per_race": _r(_mean(f["overtakes"] for f in features), 1),
            "avg_position_changes_after_lap1": _r(
                _mean(f["pos_changes_after_lap1"] for f in features), 1
            ),
            "avg_position_changes_lap1": _r(_mean(f["pos_changes_lap1"] for f in features), 1),
        },
        "grid": {
            "pole_to_win_rate": _r(_rate(g == 1 for g in winner_grids)),
            "win_outside_top3_quali_rate": _r(_rate(g > 3 for g in winner_grids)),
            "winner_outside_top5_rate": _r(_rate(g > 5 for g in winner_grids)),
            "podium_outside_top10_rate": _r(_rate(f["podium_outside_top10"] for f in features)),
            "points_outside_top10_rate": _r(_rate(f["points_outside_top10"] for f in features)),
            "quali_finish_correlation": _r(_spearman(pairs)),
            "avg_finish_by_grid": _avg_finish_by_grid(pairs),
        },
        "tyres": {
            "compound_usage_frequency": _normalise(compound_laps),
            "max_stint_length": max(stint_maxes) if stint_maxes else None,
            "avg_tyre_age_at_pit": _r(_mean(pit_ages), 1),
            "avg_stint_degradation_s_per_lap": _r(_mean(stint_slopes), 3),
        },
        "weather": {
            "dry_race_share": _r(_rate(f["class"] == "dry" for f in features)),
            "mixed_race_share": _r(_rate(f["class"] == "mixed" for f in features)),
            "wet_race_share": _r(_rate(f["class"] == "wet" for f in features)),
            "rain_during_race_rate": _r(_rate(f["rain_any"] for f in features)),
            "avg_air_temp_c": _r(_mean(f["air_temp"] for f in features), 1),
            "avg_track_temp_c": _r(_mean(f["track_temp"] for f in features), 1),
        },
        "timing": {
            "avg_race_duration_s": _r(_mean(f["race_duration_s"] for f in features), 1),
            "avg_winner_to_p10_s": _r(_mean(f["winner_to_p10_s"] for f in features), 1),
            "avg_winner_to_last_s": _r(_mean(f["winner_to_last_s"] for f in features), 1),
        },
    }


def _pool_compounds(dry: list[dict]) -> dict[str, int]:
    pooled: dict[str, int] = {}
    for f in dry:
        for c, n in f["compound_laps"].items():
            pooled[c] = pooled.get(c, 0) + n
    return pooled


def _normalise(counts: dict[str, int]) -> dict[str, float]:
    total = sum(counts.values())
    if total <= 0:
        return {}
    return {c: round(n / total, 3) for c, n in counts.items()}


def _avg_finish_by_grid(pairs: list[tuple[float, float]]) -> dict[str, float]:
    """Mean classified finish for each grid slot, keyed by the grid position (string)."""
    by_grid: dict[int, list[float]] = {}
    for grid, finish in pairs:
        by_grid.setdefault(int(grid), []).append(finish)
    return {str(g): round(float(np.mean(v)), 2) for g, v in sorted(by_grid.items())}


def _spearman(pairs: list[tuple[float, float]]) -> float | None:
    """Spearman rank correlation between grid and finish over pooled classified pairs."""
    if len(pairs) < 3:
        return None
    df = pd.DataFrame(pairs, columns=["grid", "finish"])
    if df["grid"].nunique() < 2 or df["finish"].nunique() < 2:
        return None
    rho = df["grid"].corr(df["finish"], method="spearman")
    return float(rho) if pd.notna(rho) else None
