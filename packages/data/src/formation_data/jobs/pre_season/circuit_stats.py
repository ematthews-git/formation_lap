"""Pre-season job — recompute CircuitStats for the upcoming season.

Cadence: yearly. Runs after the prior season has fully settled. Reads several closed seasons
of FastF1 data and produces one CircuitStats row per circuit, keyed by the *upcoming* season.

Inputs (per circuit, aggregated over the last N closed seasons — default 3):
- sc_probability       : fraction of races that had at least one safety car (FastF1 race control messages)
- red_flag_probability : fraction of races that had a red flag (FastF1 race control messages)
- pit_loss_normal      : median time lost in green-flag pit stops (out-lap delta from FastF1 laps)
- pit_loss_sc          : median pit loss during SC laps
- pit_loss_vsc         : median pit loss during VSC laps
- undercut_strength    : mean position delta gained by undercutters in the first stop window
- overcut_strength     : same, mean delta for overcutters

Upsert key: CircuitStats UniqueConstraint(circuit_id, season).
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

HISTORY_SEASONS = 3


def run(session: Session, *, season: int) -> None:
    # TODO:
    #   for circuit in session.scalars(select(Circuit)):
    #       sessions = [
    #           fastf1_client.get_race_session(season - n, _round_for(circuit, season - n))
    #           for n in range(1, HISTORY_SEASONS + 1)
    #       ]
    #       sc_prob = _safety_car_probability(sessions)
    #       rf_prob = _red_flag_probability(sessions)
    #       pit_normal, pit_sc, pit_vsc = _pit_losses(sessions)
    #       undercut, overcut = _undercut_overcut(sessions)
    #       stmt = insert(CircuitStats).values(
    #           circuit_id=circuit.circuit_id, season=season,
    #           sc_probability=sc_prob, red_flag_probability=rf_prob,
    #           pit_loss_normal=pit_normal, pit_loss_sc=pit_sc, pit_loss_vsc=pit_vsc,
    #           undercut_strength=undercut, overcut_strength=overcut,
    #       ).on_conflict_do_update(
    #           index_elements=["circuit_id", "season"],
    #           set_={"sc_probability": sc_prob, "red_flag_probability": rf_prob, ...},
    #       )
    #       session.execute(stmt)
    logger.info(
        "pre_season.circuit_stats.run season=%s (skeleton — would aggregate %s prior seasons)",
        season, HISTORY_SEASONS,
    )
