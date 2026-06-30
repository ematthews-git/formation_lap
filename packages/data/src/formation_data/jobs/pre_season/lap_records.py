"""Pre-season job — refresh the qualifying track record per circuit.

Cadence: yearly (slow — it paginates every qualifying result a circuit has on
record). Produces one LapRecord per circuit: the fastest qualifying lap ever
set there, via Jolpica's `/circuits/{id}/qualifying` endpoint (best of
Q3/Q2/Q1 across all seasons).

Note: this is the *qualifying* track record, not the race fastest lap — that's
the figure broadcasts quote as the outright lap record. The circuit's Jolpica
circuitId is `circuit.jolpica_id`.

Safety: a circuit with no qualifying data (new venue) or a failed/ rate-limited
Jolpica call is logged and skipped, so one bad circuit doesn't sink the batch.

Upsert key: LapRecord.circuit_id is unique.
"""

from __future__ import annotations

import logging

import httpx
from sqlalchemy import Connection

from formation_data import domain, repositories, schema
from formation_data.sources import jolpica_client

logger = logging.getLogger(__name__)


def run(conn: Connection) -> None:
    items: list[domain.LapRecord] = []
    for circuit in repositories.list_circuits(conn):
        try:
            rows = jolpica_client.get_qualifying_results(circuit.jolpica_id)
        except httpx.HTTPError as exc:
            logger.warning(
                "pre_season.lap_records: Jolpica qualifying fetch failed for %s "
                "(%s); skipping",
                circuit.circuit_id,
                exc,
            )
            continue

        record = _fastest(rows)
        if record is None:
            logger.warning(
                "pre_season.lap_records: no qualifying data for %s; skipping",
                circuit.circuit_id,
            )
            continue

        items.append(
            domain.LapRecord(
                circuit_id=circuit.circuit_id,
                driver=record["driver"],
                year=record["season"],
                lap_time_seconds=record["seconds"],
            )
        )
        logger.info(
            "pre_season.lap_records: %s record %.3fs %s (%s)",
            circuit.circuit_id,
            record["seconds"],
            record["driver"],
            record["season"],
        )

    repositories.upsert(conn, schema.lap_records, items, ["circuit_id"])
    logger.info("pre_season.lap_records.run circuits=%d", len(items))


def _parse_lap_time(text: str) -> float | None:
    """Parse an Ergast qualifying time ('1:27.097' or '27.097') to seconds."""
    try:
        if ":" in text:
            minutes, seconds = text.split(":")
            return int(minutes) * 60 + float(seconds)
        return float(text)
    except ValueError:
        return None


def _fastest(rows: list[dict]) -> dict | None:
    """The row with the smallest parsed lap time, with a `seconds` field added."""
    best: dict | None = None
    for row in rows:
        seconds = _parse_lap_time(row["best_time"])
        if seconds is None:
            continue
        if best is None or seconds < best["seconds"]:
            best = {**row, "seconds": seconds}
    return best
