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

    items = [
        domain.RaceResult(
            circuit_id=circuit_id,
            season=season,
            round_number=round_number,
            position=int(r["position"]),
            driver_id=_surname_key(r["Driver"]["familyName"]),
            team=r["Constructor"]["name"],
        )
        for r in race["Results"]
    ]

    repositories.upsert(
        conn, schema.race_results, items, ["season", "round_number", "position"]
    )
    logger.info(
        "post_race.race_results.run season=%s round=%s circuit=%s results=%d",
        season,
        round_number,
        circuit_id,
        len(items),
    )


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
