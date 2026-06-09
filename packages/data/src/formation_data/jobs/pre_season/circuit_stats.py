"""Pre-season job — recompute CircuitStats for the upcoming season.

Cadence: yearly. Runs after the prior season has fully settled. Reads several closed seasons
of FastF1 data and produces one CircuitStats row per circuit, keyed by the *upcoming* season.

Upsert key: CircuitStats UniqueConstraint(circuit_id, season).
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection
from formation_data import domain, repositories, schema
from formation_data.sources import fastf1_client

logger = logging.getLogger(__name__)

HISTORY_SEASONS = 5

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


def _safety_car_probability(sessions) -> float:
    """Proportion of sessions which had at least one SC deployment.

    Recommend 5 race sessions.

    Args:
        sessions (fastF1 session): A race session from fastF1.
    """
    count = 0

    for session in sessions:
        rc = session.race_control_messages
        sc_messages = rc[
            rc["Message"].str.contains("SAFETY CAR", na=False)
            & rc["Status"].str.contains("DEPLOYED", na=False)
        ]
        if len(sc_messages) != 0:
            count += 1

    return count / len(sessions)


def _red_flag_probability(sessions) -> float:
    """Proportion of sessions which had at least one Red flag.

    Recommend 5 race sessions.

    Args:
        sessions (Fastf1 session): A race session from fastf1.
    """

    count = 0

    for session in sessions:
        rc = session.race_control_messages
        print(rc)

        red = rc[rc["Message"] == "RED FLAG"]
        if len(red) != 0:
            count += 1

    return count / len(sessions)


def _undercut_strength():
    pass


def _overcut_strength():
    pass
