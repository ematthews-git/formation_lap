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

import httpx
from sqlalchemy import Connection

from formation_data import domain, repositories, schema
from formation_data.sources import jolpica_client

logger = logging.getLogger(__name__)


def run(conn: Connection, *, season: int, round_number: int) -> None:
    """Fetch and persist driver + constructor standings after a round."""
    try:
        drivers = jolpica_client.get_driver_standings(season, round_number)
        constructors = jolpica_client.get_constructor_standings(season, round_number)
    except httpx.HTTPError as exc:
        logger.error(
            "post_race.standings.run: Jolpica fetch failed for %s R%s (%s)",
            season,
            round_number,
            exc,
        )
        return

    if not drivers and not constructors:
        logger.warning(
            "post_race.standings.run: no standings for %s R%s; nothing written",
            season,
            round_number,
        )
        return

    items = [
        domain.Standing(
            season=season,
            after_round=round_number,
            type="driver",
            position=int(r["position"]),
            name=f"{r['Driver']['givenName']} {r['Driver']['familyName']}",
            points=float(r["points"]),
        )
        for r in drivers
    ]
    items += [
        domain.Standing(
            season=season,
            after_round=round_number,
            type="constructor",
            position=int(r["position"]),
            name=r["Constructor"]["name"],
            points=float(r["points"]),
        )
        for r in constructors
    ]

    repositories.upsert(
        conn, schema.standings, items, ["season", "after_round", "type", "position"]
    )
    logger.info(
        "post_race.standings.run season=%s round=%s drivers=%d constructors=%d",
        season,
        round_number,
        len(drivers),
        len(constructors),
    )
