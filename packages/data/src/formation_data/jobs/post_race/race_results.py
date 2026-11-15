"""Post-race job — load a race's finishing order.

Cadence: T+1 (Monday after the race), once Jolpica has published results.
Source: sources.jolpica_client.

Results are stored against the race's weekend. The weekend is found from the race's own
circuit (Jolpica's Circuit.circuitId, mapped through circuits.jolpica_id) and season, with
the round only telling a double-header's two visits apart, so a result never lands on the
wrong race if the stored calendar and Jolpica briefly disagree on numbering. Races at a
circuit we don't seed (no `circuits` row, so no weekend) are skipped.

driver_id is stored as the accent-stripped lowercase surname, matching the
drivers seed convention so results join cleanly to drivers.

Upsert key: race_results (race_weekend_id, position).
"""

from __future__ import annotations

import logging
import unicodedata

import httpx
from sqlalchemy import Connection

from formation_data import domain, repositories, schema
from formation_data.sources import jolpica_client

logger = logging.getLogger(__name__)


def run(conn: Connection, *, season: int, round_number: int) -> None:
    """Fetch and persist the finishing order for Jolpica's (season, round_number)."""
    try:
        race = jolpica_client.get_race(season, round_number)
    except httpx.HTTPError as exc:
        logger.error(
            "post_race.race_results.run: Jolpica fetch failed for %s R%s (%s)",
            season,
            round_number,
            exc,
        )
        return

    if race is None or not race.get("Results"):
        logger.warning(
            "post_race.race_results.run: no results for %s R%s; nothing written",
            season,
            round_number,
        )
        return

    circuit_id = _circuit_id_for(conn, race["Circuit"]["circuitId"])
    if circuit_id is None:
        logger.warning(
            "post_race.race_results.run: circuit %s (round %s) is not seeded; skipping",
            race["Circuit"]["circuitId"],
            round_number,
        )
        return

    weekend = repositories.resolve_race_weekend(
        conn, season=season, circuit_id=circuit_id, round_number=int(race["round"])
    )
    n = _persist_race(conn, weekend, race)
    logger.info(
        "post_race.race_results.run season=%s round=%s circuit=%s results=%d",
        season,
        round_number,
        circuit_id,
        n,
    )


def load_for_weekend(conn: Connection, weekend: domain.RaceWeekend) -> int | None:
    """Fetch and store one stored weekend's results.

    Returns Jolpica's (official) round for the race, which the standings job addresses
    it by, or None when the results aren't published yet. Raises httpx.HTTPError if
    Jolpica can't be reached.
    """
    circuit = repositories.get_circuit(conn, weekend.circuit_id)
    if circuit is None:
        logger.warning(
            "post_race.race_results: weekend %s R%s references unknown circuit %s; skipping",
            weekend.season,
            weekend.round_number,
            weekend.circuit_id,
        )
        return None
    races = jolpica_client.get_circuit_races(weekend.season, circuit.jolpica_id)
    race = _race_for_weekend(conn, races, weekend)
    if race is None or not race.get("Results"):
        return None
    _persist_race(conn, weekend, race)
    return int(race["round"])


def backfill(
    conn: Connection, *, seasons: list[int], circuit_ids: list[str] | None = None
) -> None:
    """Load results for every stored weekend in `seasons` (all circuits, or a subset).

    Walks the stored calendar, so each season needs `weekends refresh` first. A weekend
    whose results aren't published (or whose fetch fails) is skipped.
    """
    wanted = set(circuit_ids) if circuit_ids is not None else None
    loaded = 0
    for season in seasons:
        weekends = repositories.list_race_weekends(conn, season)
        if not weekends:
            logger.warning(
                "race_results.backfill: no calendar stored for %s; run "
                "`formation-data weekends refresh --season %s` first",
                season,
                season,
            )
        for weekend in weekends:
            if wanted is not None and weekend.circuit_id not in wanted:
                continue
            try:
                official_round = load_for_weekend(conn, weekend)
            except httpx.HTTPError as exc:
                logger.warning(
                    "race_results.backfill: %s %s fetch failed (%s); skipping",
                    weekend.circuit_id,
                    season,
                    exc,
                )
                continue
            if official_round is not None:
                loaded += 1
    logger.info("race_results.backfill seasons=%s weekends=%d", seasons, loaded)


def _race_for_weekend(
    conn: Connection, races: list[dict], weekend: domain.RaceWeekend
) -> dict | None:
    """The race, among every race at the weekend's circuit that season, that belongs to
    this weekend, using the same matching rule writers use (resolve_race_weekend).

    For a double-header where only one visit has results so far, the published race
    belongs to the other weekend, so this returns None rather than borrowing it."""
    for race in races:
        try:
            match = repositories.resolve_race_weekend(
                conn,
                season=weekend.season,
                circuit_id=weekend.circuit_id,
                round_number=int(race["round"]),
            )
        except repositories.RaceWeekendNotFound:
            continue
        if match.id == weekend.id:
            return race
    return None


def _persist_race(conn: Connection, weekend: domain.RaceWeekend, race: dict) -> int:
    """Upsert a race's finishing order against its weekend; returns the number of rows."""
    items = [
        domain.RaceResult(
            race_weekend_id=weekend.id,
            circuit_id=weekend.circuit_id,
            season=weekend.season,
            round_number=weekend.round_number,
            position=int(r["position"]),
            driver_id=_surname_key(r["Driver"]["familyName"]),
            team=r["Constructor"]["name"],
        )
        for r in race["Results"]
    ]
    repositories.upsert(conn, schema.race_results, items, ["race_weekend_id", "position"])
    return len(items)


def _circuit_id_for(conn: Connection, jolpica_id: str) -> str | None:
    """Map a Jolpica circuitId to our circuit_id, or None if not seeded."""
    for circuit in repositories.list_circuits(conn):
        if circuit.jolpica_id == jolpica_id:
            return circuit.circuit_id
    return None


def _surname_key(family_name: str) -> str:
    """Accent-stripped lowercase surname, matching the drivers seed driver_id."""
    stripped = "".join(
        c for c in unicodedata.normalize("NFKD", family_name) if not unicodedata.combining(c)
    )
    return stripped.lower()
