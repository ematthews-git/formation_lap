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

from sqlalchemy import Connection
from formation_data import domain, repositories, schema
from formation_data.sources import fastf1_client

logger = logging.getLogger(__name__)

HISTORY_SEASONS = 3

# class CircuitStats(_Base):
#     id: int | None = None
#     circuit_id: str
#     season: int
#     sc_probability: int
#     red_flag_probability: int
#     pit_loss_normal: float
#     pit_loss_sc: float
#     pit_loss_vsc: float
#     undercut_strength: float
#     overcut_strength: float


def run(conn: Connection, *, season: int) -> None:
    # TODO:
    #   from formation_data import domain, repositories, schema
    #   from formation_data.sources import fastf1_client
    #   items = []
    #   for circuit in repositories.list_circuits(conn):
    #       sessions = [
    #           fastf1_client.get_race_session(season - n, _round_for(circuit, season - n))
    #           for n in range(1, HISTORY_SEASONS + 1)
    #       ]
    #       items.append(domain.CircuitStats(
    #           circuit_id=circuit.circuit_id, season=season,
    #           sc_probability=_safety_car_probability(sessions),
    #           red_flag_probability=_red_flag_probability(sessions),
    #           pit_loss_normal=..., pit_loss_sc=..., pit_loss_vsc=...,
    #           undercut_strength=..., overcut_strength=...,
    #       ))
    #   repositories.upsert(conn, schema.circuit_stats, items, ["circuit_id", "season"])
    logger.info(
        "pre_season.circuit_stats.run season=%s (skeleton — would aggregate %s prior seasons)",
        season,
        HISTORY_SEASONS,
    )


def _safety_car_probability(sessions):
    """Calculates the probability of a safety car based on all sessions given.

    Args:
        sessions (_type_): _description_
    """

    pass


def _red_flag_probability(sessions):
    pass


def _undercut_strength():
    pass


def _overcut_strength():
    pass
