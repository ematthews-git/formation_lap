"""Post-race job — refresh driver + constructor standings after a round.

Cadence: T+1.

Source:
- sources.jolpica_client.get_driver_standings(season, round_number)
- sources.jolpica_client.get_constructor_standings(season, round_number)

Each upstream row produces one Standing row. `type` is "driver" or "constructor".
Upsert key: Standing UniqueConstraint(season, after_round, type, position).
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def run(session: Session, *, season: int, round_number: int) -> None:
    # TODO:
    #   for row in jolpica_client.get_driver_standings(season, round_number):
    #       _upsert_standing(session, season, round_number, "driver",
    #                        position=int(row["position"]),
    #                        name=f"{row['Driver']['givenName']} {row['Driver']['familyName']}",
    #                        points=float(row["points"]))
    #   for row in jolpica_client.get_constructor_standings(season, round_number):
    #       _upsert_standing(session, season, round_number, "constructor",
    #                        position=int(row["position"]),
    #                        name=row["Constructor"]["name"],
    #                        points=float(row["points"]))
    logger.info(
        "post_race.standings.run season=%s round=%s (skeleton)", season, round_number
    )
