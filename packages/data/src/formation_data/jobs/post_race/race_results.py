"""Post-race job — load race finishing order for a round.

Cadence: T+1 (Monday after the race), once Jolpica has published results.

Source: sources.jolpica_client.get_race(season, round_number).

The circuit is taken from the race's own Circuit.circuitId (mapped to our
circuit_id via jolpica_id), not from the round number — our hand-curated seed
calendar doesn't line up with Jolpica's real rounds. Races at a circuit we don't
seed (e.g. Bahrain/Jeddah) are skipped, since circuit_id is a FK.

driver_id is stored as the accent-stripped lowercase surname, matching the
drivers seed convention so results join cleanly to drivers.

Upsert key: RaceResult UniqueConstraint(season, round_number, position).
"""

from __future__ import annotations

import logging
import unicodedata

import httpx
from sqlalchemy import Connection

from formation_data import domain, repositories, schema

logger = logging.getLogger(__name__)


def run(conn: Connection, *, season: int, round_number: int) -> None:
    """Fetch and persist the finishing order for (season, round_number)."""
    from formation_data.sources import jolpica_client

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
            "post_race.race_results.run: circuit %s (round %s) is not seeded; "
            "skipping",
            race["Circuit"]["circuitId"],
            round_number,
        )
        return

    n = _persist_race(conn, circuit_id, season, race)
    logger.info(
        "post_race.race_results.run season=%s round=%s circuit=%s results=%d",
        season,
        round_number,
        circuit_id,
        n,
    )


def backfill(
    conn: Connection, *, seasons: list[int], circuit_ids: list[str] | None = None
) -> None:
    """Backfill results for the given seasons across circuits (all, or a subset).

    Fetches each circuit's race per season by circuit id, so it doesn't need the
    per-season round numbers. Used to populate the past-results archive. A
    circuit not raced in a season (or a failed fetch) is skipped.
    """
    from formation_data.sources import jolpica_client

    circuits = repositories.list_circuits(conn)
    if circuit_ids is not None:
        wanted = set(circuit_ids)
        circuits = [c for c in circuits if c.circuit_id in wanted]

    total = 0
    for circuit in circuits:
        for season in seasons:
            try:
                race = jolpica_client.get_circuit_race(season, circuit.jolpica_id)
            except httpx.HTTPError as exc:
                logger.warning(
                    "race_results.backfill: %s %s fetch failed (%s); skipping",
                    circuit.circuit_id,
                    season,
                    exc,
                )
                continue
            if race is None or not race.get("Results"):
                continue
            total += _persist_race(conn, circuit.circuit_id, season, race)

    logger.info(
        "race_results.backfill circuits=%d seasons=%s rows=%d",
        len(circuits),
        seasons,
        total,
    )


def _persist_race(conn: Connection, circuit_id: str, season: int, race: dict) -> int:
    """Upsert a race's finishing order; returns the number of rows."""
    items = [
        domain.RaceResult(
            circuit_id=circuit_id,
            season=season,
            round_number=int(race["round"]),
            position=int(r["position"]),
            driver_id=_surname_key(r["Driver"]["familyName"]),
            team=r["Constructor"]["name"],
        )
        for r in race["Results"]
    ]
    repositories.upsert(
        conn, schema.race_results, items, ["season", "round_number", "position"]
    )
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
