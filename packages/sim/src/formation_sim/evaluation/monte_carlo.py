"""Monte-Carlo evaluation of a driver's candidate strategies.

For a target driver we run many stochastic races. Competitors sample their own
strategies from the shared candidate pool (weighted by plausibility); the target's
strategy is the one under test. Common random numbers are used across the target's
candidates (same competitor strategies, same race-luck draws) so differences reflect
strategy, not noise. Evaluation returns raw per-candidate outcome matrices;
ranking/selection happens elsewhere.

The S sims are advanced together by :func:`formation_sim.sim.race_batch.simulate_races`
rather than one Python race at a time: all race-luck (safety cars, retirements, start
gains, per-lap noise, pit-loss variation, pass rolls) is drawn once up front and reused
across every candidate — which is the common-random-numbers property — then each
candidate only rebuilds the per-lap strategy grid and runs the vectorised race.
"""
from __future__ import annotations

import numpy as np

from formation_sim.context.postquali import WeekendContext
from formation_sim.generation.generator import Candidate
from formation_sim.sim import race_batch
from formation_sim.sim.safety_car import GREEN, SC, VSC

_MASK = (1 << 63) - 1


def _pool_arrays(pool: list[Candidate], n_laps: int):
    """Pad each candidate's strategy into fixed-width arrays for vectorised indexing.

    Returns ``(pits[K,P], n_stops[K], comp[K,P+1])`` where padded pit slots sit beyond
    the race (``n+1``) and padded stints repeat the final compound.
    """
    K = len(pool)
    P = max((len(c.pit_laps) for c in pool), default=0)
    pits = np.full((K, P), n_laps + 1, dtype=np.int64)
    n_stops = np.zeros(K, dtype=np.int64)
    comp = np.zeros((K, P + 1), dtype=np.int64)
    for k, c in enumerate(pool):
        ns = len(c.pit_laps)
        n_stops[k] = ns
        pits[k, :ns] = c.pit_laps
        ci = [race_batch._compound_index(x) for x in c.compounds]
        comp[k, :len(ci)] = ci
        comp[k, len(ci):] = ci[-1] if ci else race_batch._compound_index("MEDIUM")
    return pits, n_stops, comp


def _sample_race_luck(wctx: WeekendContext, drivers: list[str], S: int, P: int,
                      luck: np.random.Generator):
    """Draw all race randomness once (shared across candidates = common random numbers)."""
    prof, cfg = wctx.profile, wctx.cfg
    n, N = prof.n_laps, len(drivers)
    dnf, start = wctx.params.dnf, wctx.params.start

    # retirements
    dnf_prob = np.array([dnf.dnf_prob(d) for d in drivers])
    is_dnf = luck.random((S, N)) < dnf_prob[None, :]
    first = luck.random((S, N)) < dnf.p_first_lap
    rl = np.where(first, 1, luck.integers(2, n + 1, (S, N)))
    retire_lap = np.where(is_dnf, rl, n + 1)

    # lap-1 start gains (per-driver empirical distribution + Gaussian jitter)
    start_gain = np.empty((S, N))
    for i, d in enumerate(drivers):
        arr = start.deltas_by_driver.get(d)
        if arr is None or len(arr) < start.min_samples:
            arr = start.pooled
        start_gain[:, i] = arr[luck.integers(0, len(arr), S)] + luck.normal(0.0, start.sigma, S)

    # safety-car / VSC plan per sim
    sc = cfg["safety_car"]
    status = np.zeros((S, L := n), dtype=np.int64)
    laps = np.arange(1, L + 1)[None, :]

    def place(kind, lo, hi, prob):
        nonlocal status
        occurs = luck.random(S) < prob
        dur = luck.integers(int(lo), int(hi) + 1, S)
        start_lap = luck.integers(1, np.maximum(2, n - dur))
        mask = occurs[:, None] & (laps >= start_lap[:, None]) & (laps < (start_lap + dur)[:, None])
        status = np.where(mask & (status == GREEN), kind, status)

    place(SC, sc["sc_min_laps"], sc["sc_max_laps"], float(prof.sc_prob))
    place(VSC, sc["vsc_min_laps"], sc["vsc_max_laps"], float(prof.vsc_prob))

    noise = luck.standard_normal((S, N, L))
    pit_loss_var = luck.standard_normal((S, N, L))
    pass_roll = luck.random((S, L, N))
    pit_jit = luck.standard_normal((S, N, P)) if P else np.zeros((S, N, 0))
    return retire_lap, start_gain, status, noise, pit_loss_var, pass_roll, pit_jit


def evaluate_driver(wctx: WeekendContext, target: str, pool: list[Candidate],
                    n_sims: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Return (finish[K, S], race_time[K, S]) for the target's K candidates."""
    cfg = wctx.cfg
    prof, lm = wctx.profile, wctx.params.lap
    n = prof.n_laps
    drivers = wctx.drivers()
    N, K, S = len(drivers), len(pool), n_sims
    t_idx = drivers.index(target)
    comp_pos = [i for i, d in enumerate(drivers) if d != target]
    ncomp = len(comp_pos)

    weights = np.array([c.prior for c in pool], dtype=float)
    weights = weights / weights.sum()

    # competitor strategy draws per sim (kept per-sim to match the scalar distribution)
    comp_choice = np.empty((S, ncomp), dtype=np.int64)
    for s in range(S):
        strat_rng = np.random.default_rng((seed * 1_000_003 + s) & _MASK)
        comp_choice[s] = strat_rng.choice(K, size=ncomp, p=weights)

    pool_pits, pool_ns, pool_comp = _pool_arrays(pool, n)
    P = pool_pits.shape[1]

    luck = np.random.default_rng((seed * 7919) & _MASK)
    retire_lap, start_gain, sc_status, noise, pit_loss_var, pass_roll, pit_jit = \
        _sample_race_luck(wctx, drivers, S, P, luck)

    grid = np.array([wctx.grid[d] for d in drivers], dtype=np.int64)
    base_pace = np.array([wctx.base_pace[d] for d in drivers])
    noise_std = np.array([lm.noise_std(d) for d in drivers])
    jitter_sd = float(cfg["simulation"]["pit_jitter_sd"])
    min_stint = int(cfg["generation"]["min_stint"])

    finish = np.full((K, S), np.nan)
    rtime = np.full((K, S), np.nan)
    for k in range(K):
        # per-(sim, driver) strategy: competitors sampled per sim, target = candidate k
        pit_arr = np.full((S, N, P), n + 1, dtype=np.int64)
        ns_arr = np.zeros((S, N), dtype=np.int64)
        comp_arr = np.zeros((S, N, P + 1), dtype=np.int64)
        pit_arr[:, comp_pos, :] = pool_pits[comp_choice]
        ns_arr[:, comp_pos] = pool_ns[comp_choice]
        comp_arr[:, comp_pos, :] = pool_comp[comp_choice]
        pit_arr[:, t_idx, :] = pool_pits[k]
        ns_arr[:, t_idx] = pool_ns[k]
        comp_arr[:, t_idx, :] = pool_comp[k]

        comp_idx, age, is_pit = race_batch.build_schedules(
            pit_arr, ns_arr, comp_arr, pit_jit, n, jitter_sd, min_stint)

        f, rt, _ = race_batch.simulate_races(
            prof, lm, cfg, drivers=drivers, grid=grid, base_pace=base_pace,
            noise_std=noise_std, comp_idx=comp_idx, age=age, is_pit=is_pit,
            retire_lap=retire_lap, start_gain=start_gain, sc_status=sc_status,
            noise=noise, pit_loss_var=pit_loss_var, pass_roll=pass_roll)
        finish[k] = f[:, t_idx]
        rtime[k] = rt[:, t_idx]
    return finish, rtime
