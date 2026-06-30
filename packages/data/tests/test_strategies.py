"""Unit tests for the pure helpers in jobs.pre_race.strategies.

No database or FastF1 network access — sessions are faked with a plain object
carrying a `laps` DataFrame holding the columns the miner reads
(Driver, Stint, Compound, LapNumber).
"""

from __future__ import annotations

import pandas as pd

from formation_data.jobs.pre_race import strategies


class FakeSession:
    def __init__(self, laps=None):
        self.laps = laps


def _laps(*driver_specs: tuple[str, list[tuple[int, str, int, int]]]) -> pd.DataFrame:
    """Build a laps frame. Each spec: (driver, [(stint, compound, start, end), ...])."""
    rows = []
    for driver, stints in driver_specs:
        for stint, compound, start, end in stints:
            for lap in range(start, end + 1):
                rows.append(
                    {"Driver": driver, "Stint": stint, "Compound": compound, "LapNumber": lap}
                )
    return pd.DataFrame(rows)


# --- _driver_strategies ---


def test_driver_strategies_basic_one_stop():
    laps = _laps(("VER", [(1, "MEDIUM", 1, 20), (2, "HARD", 21, 52)]))
    [entry] = strategies._driver_strategies(FakeSession(laps))
    assert entry["driver"] == "VER"
    assert entry["compounds"] == ["MEDIUM", "HARD"]
    assert entry["stop_laps"] == [20]  # in-lap = last lap of the first stint


def test_driver_strategies_excludes_wet_compound():
    laps = _laps(("HAM", [(1, "INTERMEDIATE", 1, 10), (2, "MEDIUM", 11, 52)]))
    assert strategies._driver_strategies(FakeSession(laps)) == []


def test_driver_strategies_excludes_early_dnf():
    # Completes only 10 of 52 laps (< MIN_RACE_FRACTION) → dropped.
    laps = _laps(
        ("VER", [(1, "MEDIUM", 1, 52)]),  # sets total_laps = 52
        ("PER", [(1, "SOFT", 1, 10)]),
    )
    drivers = {e["driver"] for e in strategies._driver_strategies(FakeSession(laps))}
    assert drivers == {"VER"}


def test_driver_strategies_empty_laps():
    assert strategies._driver_strategies(FakeSession(pd.DataFrame())) == []


# --- _rank_strategies ---


def test_rank_orders_by_driver_count_and_collects_stop_laps():
    laps = _laps(
        ("A", [(1, "MEDIUM", 1, 20), (2, "HARD", 21, 52)]),
        ("B", [(1, "MEDIUM", 1, 22), (2, "HARD", 23, 52)]),
        ("C", [(1, "SOFT", 1, 15), (2, "HARD", 16, 52)]),
    )
    ranked = strategies._rank_strategies([FakeSession(laps)])
    assert [g["label"] for g in ranked] == ["MEDIUM->HARD", "SOFT->HARD"]
    assert ranked[0]["drivers"] == ["A", "B"]
    assert ranked[0]["stop_laps"] == [[20, 22]]  # one stop, both in-laps


# --- _pit_window ---


def test_pit_window_percentile_band_and_clamp():
    # Spread of in-laps; window is the 15th–85th percentile band, clamped to laps.
    lo, hi = strategies._pit_window([18, 20, 22, 24, 26], race_laps=52)
    assert 1 <= lo <= hi <= 52
    assert lo >= 18 and hi <= 26


def test_pit_window_single_observation_collapses():
    assert strategies._pit_window([30], race_laps=52) == (30, 30)


# --- _build_strategy ---


def test_build_strategy_shapes_stints_and_pins_final():
    group = {"label": "MEDIUM->HARD", "compounds": ["MEDIUM", "HARD"], "drivers": ["A", "B"], "stop_laps": [[20, 22]]}
    strategy, stints = strategies._build_strategy(7, 52, group, is_base=True)

    assert strategy.race_weekend_id == 7
    assert strategy.is_base is True
    assert strategy.num_stops == 1
    assert strategy.label == "MEDIUM->HARD"

    assert [s.stint_order for s in stints] == [1, 2]
    assert [s.compound for s in stints] == ["MEDIUM", "HARD"]
    # Final stint has no pit — pinned to race end.
    assert (stints[1].pit_lap_window_start, stints[1].pit_lap_window_end) == (52, 52)
    # First stint window sits within the observed in-laps.
    assert 20 <= stints[0].pit_lap_window_start <= stints[0].pit_lap_window_end <= 22
