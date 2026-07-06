"""What-if strategy evaluation — score hand-specified strategies with the real model.

Runs the same Monte-Carlo the selector uses, but on strategies *you* specify (compounds +
pit laps), for one driver, against a realistic competitor field. Use it to sanity-check the
generator — e.g. does a MEDIUM->SOFT with a *later* stop actually evaluate better than an
early one?

Run:
  uv run python -m formation_sim.whatif --year 2026 --round 9 --mode postquali \
      --driver VER --sims 250 \
      --strategy MEDIUM-SOFT@24 --strategy MEDIUM-SOFT@32 --strategy MEDIUM-SOFT@40 \
      --strategy MEDIUM-HARD@28

Each --strategy is  COMPOUND-COMPOUND-...@pit,pit,...  where the pit laps are the laps you
pit on (one fewer than the number of compounds). Point FASTF1_CACHE_DIR at a warm cache to
avoid network. Lower mean_race_time / mean_finish = stronger.
"""

from __future__ import annotations

import argparse
import os

from formation_sim.data import collector
from formation_sim.evaluation.monte_carlo import evaluate_driver
from formation_sim.evaluation.outcomes import Outcome
from formation_sim.generation.generator import Candidate, _lengths_from_pits, build_pool
from formation_sim.params import circuit, estimate
from formation_sim.settings import load_settings


def parse_strategy(spec: str) -> tuple[tuple[str, ...], tuple[int, ...]]:
    """ "MEDIUM-SOFT@40" -> (("MEDIUM","SOFT"), (40,)); "M-H-H@18,34" style short codes OK."""
    comp_part, _, pit_part = spec.partition("@")
    expand = {"S": "SOFT", "M": "MEDIUM", "H": "HARD"}
    compounds = tuple(
        expand.get(c.strip().upper(), c.strip().upper())
        for c in comp_part.split("-")
        if c.strip()
    )
    pits = tuple(int(x) for x in pit_part.split(",") if x.strip()) if pit_part else ()
    return compounds, pits


def make_candidate(
    compounds: tuple[str, ...], pits: tuple[int, ...], n_laps: int
) -> Candidate:
    n_stops = len(compounds) - 1
    if len(pits) != n_stops:
        raise ValueError(
            f"{'-'.join(compounds)} is a {n_stops}-stop strategy; it needs {n_stops} "
            f"pit lap(s), got {len(pits)} ({list(pits)})"
        )
    pits = tuple(sorted(pits))
    lengths = _lengths_from_pits(pits, n_laps)
    # analytic_cost unused here; prior=0 => competitors never sample this what-if candidate,
    # so it's scored only on the target driver.
    return Candidate(tuple(compounds), pits, n_stops, lengths, 0.0, 0.0)


def run(
    mode: str,
    year: int,
    rnd: int,
    driver: str | None,
    strategies: list[tuple[tuple[str, ...], tuple[int, ...]]],
    n_sims: int,
    seed: int,
) -> None:
    cfg = load_settings()
    if os.environ.get("FASTF1_CACHE_DIR"):
        cfg = {
            **cfg,
            "data": {**cfg["data"], "cache_dir": os.environ["FASTF1_CACHE_DIR"]},
        }
    collector.ensure_cache(cfg)

    ps = estimate.fit_all(cfg)
    profiles = circuit.build_circuit_profiles(ps.lap, cfg)
    if mode == "postquali":
        from formation_sim.context.postquali import build_postquali_context

        wctx = build_postquali_context(year, rnd, ps, profiles, cfg)
    elif mode == "prelim":
        from formation_sim.context.prelim import build_prelim_context

        wctx = build_prelim_context(year, rnd, ps, profiles, cfg)
    else:
        raise ValueError(f"unknown mode {mode!r}")

    n_laps = int(wctx.profile.n_laps)
    field = build_pool(wctx, cfg)  # realistic competitor field
    whatif = [make_candidate(c, p, n_laps) for c, p in strategies]
    pool = field + whatif  # target scored on the appended ones
    target = driver or min(wctx.drivers(), key=lambda d: wctx.grid[d])  # default: pole
    if target not in wctx.drivers():
        raise SystemExit(f"driver {target!r} not in field: {sorted(wctx.drivers())}")

    finish, rtime = evaluate_driver(wctx, target, pool, n_sims, seed)

    print(
        f"\n{wctx.circuit} {year} R{rnd} [{mode}]  driver={target} "
        f"grid={wctx.grid[target]}  {n_laps} laps  sims={n_sims}\n"
    )
    hdr = (
        f"{'strategy':16s} {'stints':14s} {'E[fin]':>7} {'E[fin|fin]':>10} "
        f"{'racetime_s':>11} {'win%':>6} {'pod%':>6} {'dnf%':>6}"
    )
    print(hdr)
    print("-" * len(hdr))
    base = len(field)
    rows = []
    for i, cand in enumerate(whatif):
        o = Outcome(finish[base + i], rtime[base + i])
        rows.append((cand, o))
    best_rt = min((o.mean_race_time for _, o in rows), default=float("nan"))
    for cand, o in rows:
        lab = (
            "-".join(c[0] for c in cand.compounds)
            + " @"
            + ",".join(map(str, cand.pit_laps))
        )
        star = "  <- fastest" if o.mean_race_time == best_rt else ""
        print(
            f"{lab:16s} {str(list(cand.stint_lengths)):14s} {o.mean_finish:7.2f} "
            f"{o.mean_finish_classified:10.2f} {o.mean_race_time:11.1f} "
            f"{o.p_win * 100:6.1f} {o.p_podium * 100:6.1f} {o.p_dnf * 100:6.1f}{star}"
        )
    print()


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Score hand-specified strategies with the sim."
    )
    ap.add_argument("--mode", default="postquali", choices=["postquali", "prelim"])
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--driver", default=None, help="driver code (default: pole sitter)")
    ap.add_argument("--sims", type=int, default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument(
        "--strategy",
        action="append",
        required=True,
        dest="strategies",
        metavar="COMP-COMP@pit,pit",
        help="repeatable; e.g. MEDIUM-SOFT@40",
    )
    args = ap.parse_args()

    cfg = load_settings()
    n_sims = args.sims or int(cfg["simulation"]["n_sims"])
    seed = args.seed if args.seed is not None else int(cfg["simulation"]["seed"])
    strategies = [parse_strategy(s) for s in args.strategies]
    run(args.mode, args.year, args.round, args.driver, strategies, n_sims, seed)


if __name__ == "__main__":
    main()
