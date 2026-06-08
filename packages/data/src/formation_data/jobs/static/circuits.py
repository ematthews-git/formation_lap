"""Static job — seed the Circuit table from the hand-curated list.

Cadence: rare. Re-run only when the FIA calendar gains/loses a circuit, when sm_zones
are confirmed, or when track measurements change.

Source: formation_data.seeds.circuits.CIRCUITS (hand-curated; everything else is fetched).
Upsert key: Circuit.circuit_id (primary key).
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def run(session: Session) -> None:
    # TODO:
    #   from formation_data.seeds.circuits import CIRCUITS
    #   for c in CIRCUITS:
    #       stmt = insert(Circuit).values(...).on_conflict_do_update(
    #           index_elements=["circuit_id"],
    #           set_={"event_name": ..., "country": ..., ...},
    #       )
    #       session.execute(stmt)
    logger.info("static.circuits.run (skeleton — would upsert 22 circuits)")
