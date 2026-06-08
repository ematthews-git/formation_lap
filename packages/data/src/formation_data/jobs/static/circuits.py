"""Static job — seed the Circuit table from the hand-curated list.

Cadence: rare. Re-run only when the FIA calendar gains/loses a circuit, when sm_zones
are confirmed, or when track measurements change.

Source: formation_data.seeds.circuits.CIRCUITS (hand-curated; everything else is fetched).
Upsert key: Circuit.circuit_id (primary key).
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection

logger = logging.getLogger(__name__)


def run(conn: Connection) -> None:
    # TODO:
    #   from formation_data import repositories, schema
    #   from formation_data.seeds.circuits import CIRCUITS
    #   repositories.upsert(conn, schema.circuits, CIRCUITS, ["circuit_id"])
    logger.info("static.circuits.run (skeleton — would upsert 22 circuits)")
