"""Pre-race job — generate strategy options for an upcoming race.

Cadence: T-7, refreshed alongside weather if CircuitStats changes.

Generation rules (full design in the plan; comments here are the implementation sketch):

1. Always emit a base 1-stop: medium → hard.
   - `is_base = True` if the dominant historical strategy for this circuit was a 1-stop.
2. Always emit a base 2-stop: soft → medium → hard.
   - `is_base = True` instead of (1) if the dominant historical strategy was a 2-stop.
3. Emit an "aggressive undercut" variant when CircuitStats.undercut_strength > UNDERCUT_THRESHOLD.
4. Emit a "safety-car gamble" variant when CircuitStats.sc_probability > SC_GAMBLE_THRESHOLD.

Pit windows per stint: derived from RaceWeekend.num_laps and per-compound tire-life heuristics.

Upsert keys:
- Strategy           UniqueConstraint(race_weekend_id, label)
- StrategyStint      UniqueConstraint(strategy_id, stint_order)
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

UNDERCUT_THRESHOLD = 0.6  # tune once real CircuitStats exist
SC_GAMBLE_THRESHOLD = 50  # SC probability is stored as int percent


def run(session: Session, *, season: int, round_number: int) -> None:
    # TODO:
    #   rw = _get_race_weekend(session, season, round_number)
    #   stats = _get_circuit_stats(session, rw.circuit_id, rw.season)
    #   plans = []
    #   plans.append(_one_stop_base(rw, stats))
    #   plans.append(_two_stop_base(rw, stats))
    #   if stats.undercut_strength > UNDERCUT_THRESHOLD:
    #       plans.append(_undercut_variant(rw, stats))
    #   if stats.sc_probability > SC_GAMBLE_THRESHOLD:
    #       plans.append(_sc_gamble_variant(rw, stats))
    #   for plan in plans:
    #       strategy_id = _upsert_strategy(session, rw, plan)
    #       _upsert_stints(session, strategy_id, plan.stints)
    logger.info(
        "pre_race.strategies.run season=%s round=%s (skeleton)", season, round_number
    )
