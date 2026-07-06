"""Unit tests for the pure shaping helpers in jobs.pre_race.sim_strategies.

No database or FastF1 — the sim result is a plain dict (the shape
formation_sim.api.simulate_race returns), and we check it maps to Strategy +
StrategyStint rows correctly.
"""

from __future__ import annotations

from formation_data.jobs.pre_race import sim_strategies


def _entry(rank=1, compounds=("MEDIUM", "HARD"), windows=((18, 24),), plausibility=0.42,
           tier="Most likely"):
    return {
        "rank": rank,
        "compounds": list(compounds),
        "n_stops": len(compounds) - 1,
        "pit_windows": [list(w) for w in windows],
        "plausibility": plausibility,
        "tier": tier,
    }


# --- _clamp ---


def test_clamp_within_bounds():
    assert sim_strategies._clamp(18, 24, 50) == (18, 24)


def test_clamp_floor_and_ceiling():
    assert sim_strategies._clamp(0, 200, 50) == (1, 50)


def test_clamp_orders_lo_le_hi():
    assert sim_strategies._clamp(30, 20, 50) == (30, 30)


# --- _build_strategy ---


def test_build_strategy_one_stop_maps_fields():
    strat, stints = sim_strategies._build_strategy(7, 52, _entry(), mode="prelim")
    assert (strat.source, strat.phase, strat.is_base) == ("sim", "prelim", True)
    assert strat.num_stops == 1
    assert strat.label == "MEDIUM->HARD"
    assert (strat.plausibility, strat.tier) == (0.42, "Most likely")

    assert [(s.stint_order, s.compound) for s in stints] == [(1, "MEDIUM"), (2, "HARD")]
    # first stint carries the pit window; final stint runs to the flag
    assert (stints[0].pit_lap_window_start, stints[0].pit_lap_window_end) == (18, 24)
    assert (stints[1].pit_lap_window_start, stints[1].pit_lap_window_end) == (52, 52)


def test_build_strategy_non_base_when_not_rank_one():
    strat, _ = sim_strategies._build_strategy(7, 52, _entry(rank=3), mode="postquali")
    assert strat.is_base is False
    assert strat.phase == "postquali"


def test_build_strategy_two_stop_windows_clamped_to_race_laps():
    entry = _entry(compounds=("SOFT", "MEDIUM", "HARD"), windows=((10, 15), (48, 60)))
    strat, stints = sim_strategies._build_strategy(7, 50, entry, mode="prelim")
    assert strat.num_stops == 2
    assert [s.compound for s in stints] == ["SOFT", "MEDIUM", "HARD"]
    assert (stints[1].pit_lap_window_start, stints[1].pit_lap_window_end) == (48, 50)  # hi clamped
    assert (stints[2].pit_lap_window_start, stints[2].pit_lap_window_end) == (50, 50)  # final stint
