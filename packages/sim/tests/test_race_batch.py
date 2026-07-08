"""Parity tests for the vectorised batch simulator against the scalar reference.

``sim/race_batch.simulate_races`` advances S Monte-Carlo races at once; it must reproduce
the per-race model of ``sim/race.simulate_race``. Two checks:

* **Deterministic** — with every random draw pinned to a constant, the batch (S=1) must
  equal the scalar race *exactly* (same lap-time model, overtaking, pit, classification).
* **Statistical** — with real randomness the two paths are not bit-identical (bulk RNG
  draws in a different order) but the target's finish/time distributions and the candidate
  ranking must agree.
"""
from __future__ import annotations

import numpy as np
import pytest

from formation_sim.context.postquali import WeekendContext
from formation_sim.evaluation.monte_carlo import evaluate_driver
from formation_sim.generation.generator import Candidate
from formation_sim.params.circuit import CircuitProfile
from formation_sim.params.dnf import DNFModel
from formation_sim.params.estimate import ParameterSet
from formation_sim.params.lapmodel import LapModel, _Fit
from formation_sim.params.startline import StartModel
from formation_sim.settings import load_settings
from formation_sim.sim import race_batch
from formation_sim.sim.race import Entry, RaceContext, simulate_race
from formation_sim.sim.safety_car import GREEN


def _lap_model() -> LapModel:
    glob = _Fit(fuel=0.03, offset={"SOFT": -0.3, "MEDIUM": 0.0, "HARD": 0.25},
                deg={"SOFT": 0.06, "MEDIUM": 0.04, "HARD": 0.03}, resid_std=0.15, n=1000)
    return LapModel(glob=glob, offsets_global={"SOFT": -0.3, "MEDIUM": 0.0, "HARD": 0.25},
                    knee={"SOFT": 15.0, "MEDIUM": 22.0, "HARD": 30.0}, cliff_rate=0.02)


def _profile(sc_prob=0.0, vsc_prob=0.0) -> CircuitProfile:
    return CircuitProfile(circuit="test", n_laps=50, base_lap_time=90.0, pit_loss=22.0,
                          sc_prob=sc_prob, vsc_prob=vsc_prob, sc_expected_laps=4.0,
                          passes_per_race=30.0, overtaking_difficulty=0.5,
                          deg_severity=0.04, fuel_coef=0.03, n_races=100)


def _drivers_grid_pace(n):
    drivers = [f"D{i}" for i in range(n)]
    grid = {d: i + 1 for i, d in enumerate(drivers)}
    base = {d: 90.0 + 0.1 * i for i, d in enumerate(drivers)}
    return drivers, grid, base


_STRATS = [
    Candidate(("SOFT", "HARD"), (18,), 1, (18, 32), 0.0, 1.0),
    Candidate(("MEDIUM", "HARD"), (22,), 1, (22, 28), 0.0, 1.0),
    Candidate(("SOFT", "MEDIUM", "HARD"), (15, 32), 2, (15, 17, 18), 0.0, 1.0),
    Candidate(("MEDIUM", "SOFT"), (30,), 1, (30, 20), 0.0, 1.0),
    Candidate(("HARD", "MEDIUM"), (25,), 1, (25, 25), 0.0, 1.0),
    Candidate(("SOFT", "HARD"), (16,), 1, (16, 34), 0.0, 1.0),
    Candidate(("MEDIUM", "HARD"), (24,), 1, (24, 26), 0.0, 1.0),
    Candidate(("SOFT", "MEDIUM"), (20,), 1, (20, 30), 0.0, 1.0),
    Candidate(("HARD", "SOFT"), (28,), 1, (28, 22), 0.0, 1.0),
    Candidate(("MEDIUM", "HARD", "SOFT"), (14, 30), 2, (14, 16, 20), 0.0, 1.0),
]


class _StubRNG:
    """Deterministic generator: normals collapse to their mean, uniforms to 0."""
    def normal(self, loc=0.0, scale=1.0, size=None):
        return np.full(size, loc) if size is not None else loc

    def random(self, size=None):
        return np.zeros(size) if size is not None else 0.0

    def integers(self, low, high=None, size=None):
        return np.full(size, low) if size is not None else low

    def choice(self, arr, size=None, p=None):
        return arr[0]


def test_batch_matches_scalar_exactly_when_deterministic():
    cfg = load_settings()
    cfg = {**cfg, "simulation": {**cfg["simulation"], "pit_jitter_sd": 0.0}}
    lm = _lap_model()
    dnf = DNFModel(prob_by_driver={}, global_prob=0.0, p_first_lap=0.0)  # no retirements
    start = StartModel(deltas_by_driver={}, pooled=np.array([0.0]), sigma=0.0, min_samples=5)
    prof = _profile()
    drivers, grid, base = _drivers_grid_pace(len(_STRATS))
    n, N = prof.n_laps, len(drivers)

    ents = [Entry(d, "", grid[d], base[d], _STRATS[i].compounds, _STRATS[i].pit_laps)
            for i, d in enumerate(drivers)]
    res = simulate_race(RaceContext(prof, lm, dnf, start, ents, cfg), _StubRNG())

    P = max(len(c.pit_laps) for c in _STRATS)
    pit = np.full((1, N, P), n + 1, np.int64)
    ns = np.zeros((1, N), np.int64)
    comp = np.zeros((1, N, P + 1), np.int64)
    for i, c in enumerate(_STRATS):
        ns[0, i] = len(c.pit_laps)
        pit[0, i, :len(c.pit_laps)] = c.pit_laps
        ci = [race_batch._compound_index(x) for x in c.compounds]
        comp[0, i, :len(ci)] = ci
        comp[0, i, len(ci):] = ci[-1]

    comp_idx, age, is_pit = race_batch.build_schedules(
        pit, ns, comp, np.zeros((1, N, P)), n, 0.0, int(cfg["generation"]["min_stint"]))
    f, rt, _ = race_batch.simulate_races(
        prof, lm, cfg, drivers=drivers,
        grid=np.array([grid[d] for d in drivers], np.int64),
        base_pace=np.array([base[d] for d in drivers]),
        noise_std=np.array([lm.noise_std(d) for d in drivers]),
        comp_idx=comp_idx, age=age, is_pit=is_pit,
        retire_lap=np.full((1, N), n + 1, np.int64), start_gain=np.zeros((1, N)),
        sc_status=np.full((1, n), GREEN, np.int64), noise=np.zeros((1, N, n)),
        pit_loss_var=np.zeros((1, N, n)), pass_roll=np.zeros((1, n, N)))

    for i, d in enumerate(drivers):
        assert res.finish_position[d] == f[0, i]
        assert res.race_time[d] == pytest.approx(rt[0, i], abs=1e-9)


def _scalar_eval(wctx, target, pool, n_sims, seed):
    mask = (1 << 63) - 1
    drivers = wctx.drivers()
    competitors = [d for d in drivers if d != target]
    w = np.array([c.prior for c in pool], float)
    w /= w.sum()
    K = len(pool)
    finish = np.full((K, n_sims), np.nan)
    rtime = np.full((K, n_sims), np.nan)
    for s in range(n_sims):
        idx = np.random.default_rng((seed * 1_000_003 + s) & mask).choice(K, size=len(competitors), p=w)
        comp = {d: pool[i] for d, i in zip(competitors, idx)}
        for k, cand in enumerate(pool):
            rng = np.random.default_rng((seed * 7919 + s) & mask)
            sm = dict(comp)
            sm[target] = cand
            ents = [Entry(d, "", wctx.grid[d], wctx.base_pace[d], sm[d].compounds, sm[d].pit_laps)
                    for d in drivers]
            r = simulate_race(RaceContext(wctx.profile, wctx.params.lap, wctx.params.dnf,
                                          wctx.params.start, ents, wctx.cfg), rng)
            finish[k, s] = r.finish_position[target]
            rtime[k, s] = r.race_time[target]
    return finish, rtime


def test_batch_matches_scalar_distribution():
    cfg = load_settings()
    lm = _lap_model()
    dnf = DNFModel(prob_by_driver={}, global_prob=0.10, p_first_lap=0.25)
    start = StartModel(deltas_by_driver={}, pooled=np.array([-1.0, 0.0, 1.0]),
                       sigma=1.0, min_samples=5)
    prof = _profile(sc_prob=0.40, vsc_prob=0.30)
    ps = ParameterSet(lap=lm, dnf=dnf, start=start)
    drivers, grid, base = _drivers_grid_pace(10)
    wctx = WeekendContext(year=2026, round=1, circuit="test", profile=prof, params=ps,
                          prior=None, grid=grid, base_pace=base, teams={},
                          allocation=("SOFT", "MEDIUM", "HARD"), cfg=cfg)
    pool = _STRATS[:4]
    target, S, seed = "D3", 3000, 12345

    fb, tb = evaluate_driver(wctx, target, pool, S, seed)
    fs, ts = _scalar_eval(wctx, target, pool, S, seed)

    mean_fb = np.array([np.nanmean(fb[k]) for k in range(len(pool))])
    mean_fs = np.array([np.nanmean(fs[k]) for k in range(len(pool))])
    for k in range(len(pool)):
        assert mean_fb[k] == pytest.approx(mean_fs[k], abs=0.3)
        assert np.nanmean(tb[k]) == pytest.approx(np.nanmean(ts[k]), abs=5.0)
    # the best-expected-finish candidate must agree (near-tied candidates may swap under
    # independent RNG realisations, so the full ordering is not asserted)
    assert int(np.argmin(mean_fb)) == int(np.argmin(mean_fs))
