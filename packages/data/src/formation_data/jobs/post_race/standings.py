"""Post-race job: refresh driver and constructor standings after a round.

Cadence: T+1 (`run`). `backfill` loads completed *past* seasons' final standings
in one pass, used for the "last season" reference the frontend shows next to the
current championship.

Source:
- sources.jolpica_client.get_driver_standings(season, round_number)
- sources.jolpica_client.get_constructor_standings(season, round_number)
- sources.jolpica_client.get_final_standings(season)   (backfill)

Standings are stored against the race weekend they follow. Drivers are stored by
Jolpica's driverId (added to `drivers` if new) and teams by resolving Jolpica's
constructorId through team_seasons; an unknown constructor raises TeamNotFound.

Each load replaces that weekend's standings (repositories.replace_standings).
"""

from __future__ import annotations

import logging

import httpx
from sqlalchemy import Connection

from formation_data import domain, repositories
from formation_data.sources import jolpica_client

logger = logging.getLogger(__name__)


def _store(
    conn: Connection,
    weekend: domain.RaceWeekend,
    drivers: list[dict],
    constructors: list[dict],
) -> None:
    """Resolve Jolpica's standings rows to drivers and teams and store them for `weekend`."""
    people = [jolpica_client.to_driver(r["Driver"]) for r in drivers]
    repositories.upsert_drivers(conn, people)
    driver_rows = [
        domain.DriverStanding(
            race_weekend_id=weekend.id,
            driver_id=person.driver_id,
            position=int(r["position"]),
            points=float(r["points"]),
        )
        for r, person in zip(drivers, people, strict=True)
    ]
    constructor_rows = [
        domain.ConstructorStanding(
            race_weekend_id=weekend.id,
            team_id=repositories.team_for_jolpica(
                conn, weekend.season, r["Constructor"]["constructorId"]
            ).team_id,
            position=int(r["position"]),
            points=float(r["points"]),
        )
        for r in constructors
    ]
    repositories.replace_standings(conn, weekend.id, driver_rows, constructor_rows)


def _weekend(conn: Connection, season: int, round_number: int) -> domain.RaceWeekend:
    weekend = repositories.get_race_weekend(conn, season, round_number)
    if weekend is None:
        raise repositories.RaceWeekendNotFound(
            f"No race weekend for {season} round {round_number}. Load that season's "
            f"calendar with `formation-data weekends refresh --season {season}`."
        )
    return weekend


def load_for_weekend(conn: Connection, weekend: domain.RaceWeekend, official_round: int) -> None:
    """Fetch and store the standings after `weekend`'s race, which Jolpica numbers
    `official_round` (the post-race flow reads it off the race's results)."""
    try:
        drivers = jolpica_client.get_driver_standings(weekend.season, official_round)
        constructors = jolpica_client.get_constructor_standings(weekend.season, official_round)
    except httpx.HTTPError as exc:
        logger.error(
            "post_race.standings: Jolpica fetch failed for %s R%s (%s)",
            weekend.season,
            official_round,
            exc,
        )
        return

    if not drivers and not constructors:
        logger.warning(
            "post_race.standings: no standings for %s R%s; nothing written",
            weekend.season,
            official_round,
        )
        return

    _store(conn, weekend, drivers, constructors)
    logger.info(
        "post_race.standings season=%s round=%s drivers=%d constructors=%d",
        weekend.season,
        official_round,
        len(drivers),
        len(constructors),
    )


def run(conn: Connection, *, season: int, round_number: int) -> None:
    """Fetch and persist driver and constructor standings after a round.

    Raises RaceWeekendNotFound if the stored calendar has no such round."""
    load_for_weekend(conn, _weekend(conn, season, round_number), round_number)


def backfill(conn: Connection, *, seasons: list[int]) -> None:
    """Load each season's *final* standings (driver and constructor).

    For the "last season" reference panel: fetches the round-less (final) standings for
    each season and stores them against the season's final race weekend. Idempotent. A
    season with no standings yet, no stored calendar, or a failed fetch is logged and
    skipped so one bad season doesn't sink the batch.
    """
    for season in seasons:
        try:
            final_round, drivers, constructors = jolpica_client.get_final_standings(season)
        except httpx.HTTPError as exc:
            logger.error(
                "post_race.standings.backfill: Jolpica fetch failed for %s (%s)", season, exc
            )
            continue

        if final_round is None or (not drivers and not constructors):
            logger.warning(
                "post_race.standings.backfill: no final standings for %s; skipping", season
            )
            continue

        try:
            weekend = _weekend(conn, season, final_round)
        except repositories.RaceWeekendNotFound as exc:
            logger.warning("post_race.standings.backfill: %s Skipping %s.", exc, season)
            continue

        _store(conn, weekend, drivers, constructors)
        logger.info(
            "post_race.standings.backfill season=%s final_round=%s drivers=%d "
            "constructors=%d",
            season,
            final_round,
            len(drivers),
            len(constructors),
        )
