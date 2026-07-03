"""Post-race job — refresh driver + constructor standings after a round.

Cadence: T+1 (`run`). `backfill` loads completed *past* seasons' final standings
in one pass — used to populate the "last season" reference the frontend shows
next to the current championship.

Source:
- sources.jolpica_client.get_driver_standings(season, round_number)
- sources.jolpica_client.get_constructor_standings(season, round_number)
- sources.jolpica_client.get_final_standings(season)   (backfill)

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


def _standing_items(
    season: int, after_round: int, drivers: list[dict], constructors: list[dict]
) -> list[domain.Standing]:
    """Flatten Jolpica driver + constructor standings into Standing rows."""
    items = [
        domain.Standing(
            season=season,
            after_round=after_round,
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
            after_round=after_round,
            type="constructor",
            position=int(r["position"]),
            name=r["Constructor"]["name"],
            points=float(r["points"]),
        )
        for r in constructors
    ]
    return items


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

    items = _standing_items(season, round_number, drivers, constructors)
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


def backfill(conn: Connection, *, seasons: list[int]) -> None:
    """Load each season's *final* standings (driver + constructor).

    For the "last season" reference panel: fetches the round-less (final)
    standings for each season and stores them keyed on the season's actual final
    round. Idempotent — safe to re-run. A season with no standings yet (or a
    failed fetch) is logged and skipped so one bad season doesn't sink the batch.
    """
    for season in seasons:
        try:
            final_round, drivers, constructors = jolpica_client.get_final_standings(
                season
            )
        except httpx.HTTPError as exc:
            logger.error(
                "post_race.standings.backfill: Jolpica fetch failed for %s (%s)",
                season,
                exc,
            )
            continue

        if final_round is None or (not drivers and not constructors):
            logger.warning(
                "post_race.standings.backfill: no final standings for %s; skipping",
                season,
            )
            continue

        items = _standing_items(season, final_round, drivers, constructors)
        repositories.upsert(
            conn,
            schema.standings,
            items,
            ["season", "after_round", "type", "position"],
        )
        logger.info(
            "post_race.standings.backfill season=%s final_round=%s drivers=%d "
            "constructors=%d",
            season,
            final_round,
            len(drivers),
            len(constructors),
        )
