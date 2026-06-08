"""Post-race job — load race finishing order for the most recent round.

Cadence: T+1 (Monday after the race), once Jolpica has published results.

Source: sources.jolpica_client.get_race_results(season, round_number).
Upsert key: RaceResult UniqueConstraint(circuit_id, season, position).
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection

logger = logging.getLogger(__name__)


def run(conn: Connection, *, season: int, round_number: int) -> None:
    # TODO:
    #   from formation_data import domain, repositories, schema
    #   from formation_data.sources import jolpica_client
    #   rw = repositories.get_race_weekend(conn, season, round_number)
    #   raw = jolpica_client.get_race_results(season, round_number)
    #   items = [domain.RaceResult(
    #       circuit_id=rw.circuit_id, season=season,
    #       position=int(r["position"]),
    #       driver_id=r["Driver"]["driverId"],
    #       team=r["Constructor"]["name"],
    #   ) for r in raw]
    #   repositories.upsert(
    #       conn, schema.race_results, items, ["circuit_id", "season", "position"],
    #   )
    logger.info(
        "post_race.race_results.run season=%s round=%s (skeleton)", season, round_number
    )
