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

from sqlalchemy import Connection

logger = logging.getLogger(__name__)


def run(conn: Connection, *, season: int, round_number: int) -> None:
    # TODO:
    #   from formation_data import domain, repositories, schema
    #   from formation_data.sources import jolpica_client
    #   items = [domain.Standing(
    #       season=season, after_round=round_number, type="driver",
    #       position=int(r["position"]),
    #       name=f"{r['Driver']['givenName']} {r['Driver']['familyName']}",
    #       points=float(r["points"]),
    #   ) for r in jolpica_client.get_driver_standings(season, round_number)]
    #   items += [domain.Standing(
    #       season=season, after_round=round_number, type="constructor",
    #       position=int(r["position"]),
    #       name=r["Constructor"]["name"], points=float(r["points"]),
    #   ) for r in jolpica_client.get_constructor_standings(season, round_number)]
    #   repositories.upsert(
    #       conn, schema.standings, items, ["season", "after_round", "type", "position"],
    #   )
    logger.info(
        "post_race.standings.run season=%s round=%s (skeleton)", season, round_number
    )
