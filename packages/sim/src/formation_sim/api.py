"""Stable production entry point for consumers (e.g. the data pipeline).

``run.py``/``reporter.py`` produce the *per-driver* report; the *race-level* shown-5 that a
fan page displays lives in ``selection.field_display`` (previously only exercised by the
backtest). :func:`simulate_race` runs the full field once and returns the race-level result:
the ≤5 strategies most likely to be run at the race (compounds, pit windows, plausibility,
tier) plus the derived race-context statistics — the same field-aggregation the backtest's
race-level product metric scores (see ``validation/backtest.py``).

Everything here reuses existing components; nothing re-implements model logic.
"""
from __future__ import annotations

import os

import numpy as np

from formation_sim.context.postquali import build_postquali_context
from formation_sim.data import collector
from formation_sim.evaluation.monte_carlo import evaluate_driver
from formation_sim.generation.generator import build_pool
from formation_sim.params import circuit, estimate
from formation_sim.report.reporter import build_report
from formation_sim.selection.selector import field_display, plausibility_mass, select
from formation_sim.settings import load_settings


def _shown_entries(pool: list, idx: list[int], q_field: np.ndarray, cfg: dict) -> list[dict]:
    """Shape the field-display shown-5 pool indices into serialisable strategy dicts,
    labelling each with a coarse plausibility tier (same rule as ``selector.select``)."""
    thr = list(cfg.get("selection", {}).get("tier_thresholds", [0.6, 0.2]))
    t_hi = float(thr[0])
    t_lo = float(thr[1]) if len(thr) > 1 else t_hi
    q_top = float(q_field[idx[0]]) if idx else 1.0

    def tier(i: int) -> str:
        r = float(q_field[i]) / q_top if q_top > 0 else 0.0
        return "Most likely" if r >= t_hi else "Alternative" if r >= t_lo else "Long-shot"

    out = []
    for rank, i in enumerate(idx):
        c = pool[i]
        out.append({
            "rank": rank + 1,
            "compounds": list(c.compounds),
            "start_compound": c.start_compound,
            "n_stops": c.n_stops,
            "pit_laps": list(c.pit_laps),
            "pit_windows": [list(w) for w in c.pit_windows],
            "stint_lengths": list(c.stint_lengths),
            "plausibility": round(float(q_field[i]), 4),
            "tier": tier(i),
        })
    return out


def simulate_race(mode: str, year: int, rnd: int, n_sims: int | None = None,
                  seed: int | None = None, cfg: dict | None = None) -> dict:
    """Race-level strategy simulation for one Grand Prix.

    ``mode`` is ``"postquali"`` (grid + quali pace known) or ``"prelim"`` (season form only).
    Returns ``{meta, circuit_profile, race_stats, shown}`` where ``shown`` is the ≤5-strategy
    race-level display list. Requires FastF1 data for the target race (grid/quali for
    postquali; season form for prelim).
    """
    cfg = cfg or load_settings()
    # Share the pipeline's FastF1 cache when one is provided, so we don't keep a second copy
    # or double-spend the 500-req/h budget. ensure_cache() is guarded, so this one call wins.
    if os.environ.get("FASTF1_CACHE_DIR"):
        cfg = {**cfg, "data": {**cfg["data"], "cache_dir": os.environ["FASTF1_CACHE_DIR"]}}
    collector.ensure_cache(cfg)

    n_sims = n_sims or int(cfg["simulation"]["n_sims"])
    seed = seed if seed is not None else int(cfg["simulation"]["seed"])

    ps = estimate.fit_all(cfg)
    # Load the committed circuit-profile artifact rather than rebuilding it from ~110
    # historical sessions on every run (which needs a warm FastF1 cache and blows the
    # 500-req/h budget in CI). Falls back to a rebuild only if the artifact is absent.
    profiles = circuit.get_circuit_profiles(ps.lap, cfg)

    if mode == "postquali":
        wctx = build_postquali_context(year, rnd, ps, profiles, cfg)
    elif mode == "prelim":
        from formation_sim.context.prelim import build_prelim_context
        wctx = build_prelim_context(year, rnd, ps, profiles, cfg)
    else:
        raise ValueError(f"unknown mode: {mode!r} (expected 'postquali' or 'prelim')")

    pool = build_pool(wctx, cfg)
    n_pos = len(wctx.drivers())

    # Simulate the whole field: per-driver selection feeds the derived race stats, and the
    # per-driver plausibility mass is averaged into the field-level display (backtest.py:185-189).
    per_driver: dict[str, list] = {}
    q_sum = np.zeros(len(pool))
    n_q = 0
    for i, d in enumerate(wctx.drivers()):
        finish, rtime = evaluate_driver(wctx, d, pool, n_sims, seed + i)
        q_d, _, _ = plausibility_mass(pool, finish, rtime, cfg, n_pos)
        q_sum += q_d
        n_q += 1
        per_driver[d] = select(pool, finish, rtime, cfg, n_pos, wctx.prior)

    # build_report gives us meta + circuit_profile + race_stats (a pure read); we drop its
    # per-driver block and attach the race-level shown-5 instead.
    report = build_report(wctx, per_driver, n_sims, seed, cfg, profiles=profiles)
    q_field = q_sum / n_q if n_q else q_sum
    idx = field_display(pool, q_field, cfg)

    return {
        "meta": report["meta"],
        "circuit_profile": report["circuit_profile"],
        "race_stats": report["race_stats"],
        "shown": _shown_entries(pool, idx, q_field, cfg),
    }
