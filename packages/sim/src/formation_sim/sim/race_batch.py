"""Vectorised, batched race simulator: run S Monte-Carlo races at once.

This is the across-sims analogue of :mod:`formation_sim.sim.race`. The scalar
``simulate_race`` plays out one stochastic race with a Python loop over sims, laps and
drivers; here every piece of state carries a leading ``sims`` axis so the S races are
advanced together with NumPy array ops. The only surviving Python loops are the two that
are genuinely sequential — laps, and positions within a lap — because lap ``t`` depends on
lap ``t-1`` and the overtaking pass is a front-to-back recurrence. Both loops now do
vectorised work across all S sims, so interpreter overhead drops from ``O(S·L·N)`` to
``O(L·N)`` while the arithmetic is identical.

Semantics mirror ``sim/race.py`` exactly (same lap-time model, safety-car / DRS / pit /
overtaking rules and classification). Results are **not** bit-identical to the scalar
path: drawing randomness in bulk over the sims axis changes the RNG realisation. Over many
sims the distributions are equivalent — ``tests/test_race_batch_parity.py`` checks this.
"""
from __future__ import annotations

import numpy as np

from formation_sim.params.lapmodel import COMPOUNDS
from formation_sim.sim.overtaking import OvertakeParams
from formation_sim.sim.safety_car import GREEN, SC, VSC

_BIG = 1e12  # cum sentinel that sorts retired cars behind every classified finisher


def _compound_index(name: str) -> int:
    return COMPOUNDS.index(name) if name in COMPOUNDS else COMPOUNDS.index("MEDIUM")


def build_schedules(
    pit_laps: np.ndarray,      # [S, N, P] planned in-laps (padded with n+1)
    n_stops: np.ndarray,       # [S, N]    real stop count per driver
    comp_idx_stint: np.ndarray,  # [S, N, P+1] compound index per stint (padded w/ last)
    jitter: np.ndarray,        # [S, N, P] standard-normal draws for pit-lap jitter
    n_laps: int,
    jitter_sd: float,
    min_stint: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Expand per-driver strategies into per-lap ``(compound, age, is_pit)`` grids.

    Vectorises ``race._jitter_pits`` + ``race._stint_schedule`` across the S×N grid.
    Returns ``comp[S,N,L]`` (compound index), ``age[S,N,L]`` (tyre life, laps) and
    ``is_pit[S,N,L]`` (bool, an in-lap this lap).
    """
    S, N, P = pit_laps.shape
    laps = np.arange(1, n_laps + 1)  # [L]

    # --- jitter each planned in-lap, clamped sequentially (prev + min_stint .. n-min_stint)
    real = np.arange(P)[None, None, :] < n_stops[..., None]  # [S,N,P] which stops exist
    jl = np.rint(pit_laps + jitter * jitter_sd).astype(np.int64)
    prev = np.zeros((S, N), dtype=np.int64)
    out = np.full((S, N, P), n_laps + 1, dtype=np.int64)
    for p in range(P):
        cand = np.clip(jl[:, :, p], prev + min_stint, n_laps - min_stint)
        has = real[:, :, p]
        out[:, :, p] = np.where(has, cand, n_laps + 1)
        prev = np.where(has, out[:, :, p], prev)
    pit_j = out  # [S,N,P] jittered in-laps (padded stops sit beyond the race at n+1)

    # --- stint index per lap = how many real in-laps have already passed
    stint = (laps[None, None, None, :] > pit_j[..., None]).sum(axis=2)  # [S,N,L]

    # compound per lap: gather the stint's compound
    comp = np.take_along_axis(comp_idx_stint, stint, axis=2)  # [S,N,L]

    # tyre age = laps since the in-lap that started this stint (0 for the first stint)
    prev_pit = np.take_along_axis(
        pit_j, np.clip(stint - 1, 0, P - 1), axis=2
    )  # [S,N,L] the in-lap that opened this stint
    prev_pit = np.where(stint >= 1, prev_pit, 0)
    age = laps[None, None, :] - prev_pit  # [S,N,L]

    # in-lap flag: this lap equals one of the jittered in-laps
    is_pit = (laps[None, None, None, :] == pit_j[..., None]).any(axis=2)  # [S,N,L]

    return comp.astype(np.int64), age.astype(np.float64), is_pit


def simulate_races(
    prof,
    lap_model,
    cfg: dict,
    *,
    drivers: list[str],      # [N] driver ids, index order (for per-driver deg dev)
    grid: np.ndarray,        # [N] starting position per driver
    base_pace: np.ndarray,   # [N] qualifying lap time (s)
    noise_std: np.ndarray,   # [N] per-driver lap-time noise SD
    comp_idx: np.ndarray,    # [S,N,L] compound index per lap
    age: np.ndarray,         # [S,N,L] tyre age per lap
    is_pit: np.ndarray,      # [S,N,L] in-lap flag
    retire_lap: np.ndarray,  # [S,N] lap of retirement (n+1 = classified)
    start_gain: np.ndarray,  # [S,N] lap-1 positions gained
    sc_status: np.ndarray,   # [S,L] GREEN/VSC/SC per lap
    noise: np.ndarray,       # [S,N,L] standard-normal lap-time noise
    pit_loss_var: np.ndarray,  # [S,N,L] standard-normal pit-loss variation
    pass_roll: np.ndarray,   # [S,L,N] uniforms for pass-probability rolls
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Advance S full-field races together. Returns ``finish[S,N]`` (1-based position),
    ``race_time[S,N]`` (NaN for DNF) and ``classified[S,N]`` (bool).
    """
    S, N, L = comp_idx.shape
    circ = prof.circuit
    sim_cfg = cfg["simulation"]
    lap1_pen = float(sim_cfg["lap1_penalty"])
    gap_scale = float(sim_cfg["start_gap_scale"])
    sc = cfg["safety_car"]
    op = OvertakeParams.for_circuit(prof.overtaking_difficulty, cfg)

    # --- per-(driver,compound) lap-model constants (circuit fixed for the race) ---
    fuel = lap_model.fuel_coef(circ)
    off_c = np.array([lap_model.pace_offset(c, circ) for c in COMPOUNDS])          # [C]
    knee_c = np.array([
        lap_model.knee_by_circuit.get(circ, {}).get(c, lap_model.knee.get(c, 1e9))
        for c in COMPOUNDS
    ])                                                                             # [C]
    slope_nc = np.array([[lap_model.deg_slope(c, circ, d) for c in COMPOUNDS]
                         for d in drivers])                                         # [N,C]
    cliff_rate = float(lap_model.cliff_rate)

    # --- clean-air lap-time grid: base + fuel + compound offset + degradation ---------
    di = np.arange(N)[None, :, None]
    off_grid = off_c[comp_idx]                                   # [S,N,L]
    slope_grid = slope_nc[np.broadcast_to(di, comp_idx.shape), comp_idx]
    over = np.maximum(0.0, age - knee_c[comp_idx])
    deg_grid = slope_grid * age + cliff_rate * over * over       # [S,N,L]
    laps_remaining = (np.arange(1, L + 1)[::-1] - 1).astype(float)  # n-lap for lap=1..n
    raw = base_pace[None, :, None] + fuel * laps_remaining[None, None, :] + off_grid + deg_grid

    # noise only on green laps; lap-1 start penalty; safety-car pace multiplier
    neutral = sc_status != GREEN                                 # [S,L]
    raw = raw + noise * noise_std[None, :, None] * (~neutral)[:, None, :]
    raw[:, :, 0] += lap1_pen - start_gain * gap_scale
    factor = np.ones((S, L))
    factor[sc_status == SC] = float(sc["sc_factor"])
    factor[sc_status == VSC] = float(sc["vsc_factor"])
    raw = raw * factor[:, None, :]

    # pit loss on in-laps, discounted under neutralisation, floored at 5s
    disc = np.ones((S, L))
    disc[sc_status == SC] = float(sc["sc_pit_discount"])
    disc[sc_status == VSC] = float(sc["vsc_pit_discount"])
    ploss = (float(prof.pit_loss) + pit_loss_var * 0.8) * disc[:, None, :]
    ploss = np.maximum(ploss, 5.0)
    raw = raw + np.where(is_pit, ploss, 0.0)

    # ---------------------------------------------------------------- lap-by-lap state
    cum = np.zeros((S, N))
    within = np.zeros((S, N), dtype=bool)
    alive = np.ones((S, N), dtype=bool)
    laps_done = np.zeros((S, N), dtype=np.int64)
    rows = np.arange(S)
    # track order (front->back), maintained across laps via single-position swaps so a
    # passing car cannot leapfrog more than one slot (mirrors race.resolve_lap exactly).
    order = np.broadcast_to(np.argsort(grid, kind="stable"), (S, N)).copy()

    for lap in range(1, L + 1):
        li = lap - 1
        alive &= retire_lap != lap
        laps_done = np.where(alive, lap, laps_done)
        raw_l = raw[:, :, li]
        neutral_l = neutral[:, li]                       # [S]
        is_sc_l = sc_status[:, li] == SC                 # [S]
        drs_enabled = (lap > 2) & ~neutral_l             # [S]

        # ---- branch A: free mixing (lap 1) or neutralised laps ----
        cum_free = np.where(alive, cum + raw_l, cum)
        # order by total time (captures pit drops); retired sink to the back
        free_sort = np.where(alive, cum_free, _BIG)
        order_free = np.argsort(free_sort, axis=1, kind="stable")
        rank = np.empty((S, N), dtype=np.int64)
        np.put_along_axis(rank, order_free,
                          np.broadcast_to(np.arange(N), (S, N)), axis=1)
        # leader among *alive* cars only (retired cars keep a stale, small cum)
        lead = free_sort.min(axis=1, keepdims=True)
        # under full SC, bunch the field to leader + rank*min_gap
        cum_bunched = np.where(is_sc_l[:, None] & alive, lead + rank * op.min_gap, cum_free)

        # ---- branch B: green-lap overtaking recurrence (front to back) ----
        cum_b, within_b, order_b = _resolve_lap_batch(
            order, cum, raw_l, within, alive, drs_enabled, pass_roll[:, li, :], op, rows
        )

        use_free = neutral_l | (lap == 1)                # [S]
        cum = np.where(use_free[:, None], cum_bunched, cum_b)
        within = np.where(use_free[:, None], False, within_b)
        order = np.where(use_free[:, None], order_free, order_b)

    # ------------------------------------------------------------------- classification
    # finishers first (by cum asc), then DNFs by (laps_done desc, grid asc)
    dnf_key = _BIG + (L + 1 - laps_done) * (N + 1) + grid[None, :]
    sort_val = np.where(alive, cum, dnf_key)
    finish_order = np.argsort(sort_val, axis=1, kind="stable")
    finish = np.empty((S, N), dtype=np.int64)
    np.put_along_axis(finish, finish_order,
                      np.broadcast_to(np.arange(1, N + 1), (S, N)), axis=1)
    race_time = np.where(alive, cum, np.nan)
    return finish, race_time, alive.copy()


def _resolve_lap_batch(order, cum, raw_l, within, alive, drs_enabled, roll, op, rows):
    """One green lap of overtaking, vectorised across sims (see race.resolve_lap).

    Retired cars are compacted to the back so the alive field occupies contiguous front
    slots; ``n_alive`` bounds the active slots per sim. Positions are then processed
    front-to-back: slot 0 runs free, each later car races the car directly ahead
    (``order[k-1]``), and a completed pass swaps the two slots so the order carried to the
    next lap can only change by one position per pass. Returns ``(new_cum, new_within,
    new_order)``.
    """
    S, N = cum.shape
    aio = np.take_along_axis(alive, order, axis=1)                 # alive flag in slot order
    perm = np.argsort(~aio, axis=1, kind="stable")                # stable: alive first
    ordr = np.take_along_axis(order, perm, axis=1)
    n_alive = aio.sum(axis=1)                                      # [S]

    new_cum = cum.copy()
    new_within = np.zeros_like(within)

    for k in range(N):
        active = k < n_alive                                       # [S] racing car at slot k
        if not active.any():
            continue
        me = ordr[:, k]
        if k == 0:
            new_cum[rows, me] = np.where(active, cum[rows, me] + raw_l[rows, me],
                                         new_cum[rows, me])
            continue
        ahead = ordr[:, k - 1]
        ahead_cum = new_cum[rows, ahead]
        within_me = within[rows, me]
        drs = np.where(drs_enabled & within_me, op.drs_bonus, 0.0)
        tent = cum[rows, me] + raw_l[rows, me] - drs
        gap = tent - ahead_cum
        clears = active & (gap >= op.min_gap)
        contest = active & (gap < op.min_gap)
        pace_adv = ahead_cum - tent
        passes = contest & (pace_adv >= op.threshold) & (roll[:, k] < op.pass_prob)
        stuck = contest & ~passes

        cm = new_cum[rows, me]
        cm = np.where(clears, tent, cm)
        cm = np.where(passes, np.minimum(tent + op.penalty, ahead_cum - op.min_gap), cm)
        cm = np.where(stuck, ahead_cum + op.min_gap, cm)
        new_cum[rows, me] = np.where(active, cm, new_cum[rows, me])

        wi = np.where(clears, gap <= op.drs_gap, False)
        wi = np.where(stuck, True, wi)
        new_within[rows, me] = np.where(active, wi, new_within[rows, me])

        # a completed pass costs the overtaken car `penalty` and swaps track positions
        new_cum[rows, ahead] = np.where(passes, ahead_cum + op.penalty, new_cum[rows, ahead])
        a, b = ordr[:, k - 1].copy(), ordr[:, k].copy()
        ordr[:, k - 1] = np.where(passes, b, a)
        ordr[:, k] = np.where(passes, a, b)

    return new_cum, new_within, ordr
