"""Post-race job — load race finishing order for the most recent round.

Cadence: T+1 (Monday after the race), once Jolpica has published results.

Source: sources.jolpica_client.get_race_results(season, round_number).
Upsert key: RaceResult UniqueConstraint(circuit_id, season, position).
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def run(session: Session, *, season: int, round_number: int) -> None:
    # TODO:
    #   rw = _get_race_weekend(session, season, round_number)
    #   results = jolpica_client.get_race_results(season, round_number)
    #   for r in results:
    #       stmt = insert(RaceResult).values(
    #           circuit_id=rw.circuit_id, season=season,
    #           position=int(r["position"]),
    #           driver_id=r["Driver"]["driverId"],
    #           team=r["Constructor"]["name"],
    #       ).on_conflict_do_update(
    #           index_elements=["circuit_id", "season", "position"],
    #           set_={"driver_id": ..., "team": ...},
    #       )
    #       session.execute(stmt)
    logger.info(
        "post_race.race_results.run season=%s round=%s (skeleton)", season, round_number
    )
