"""Circuits, their lap records and per-circuit race stats."""

from __future__ import annotations

from sqlalchemy import Connection, func, select
from sqlalchemy.dialects.postgresql import insert

from formation_data import domain, schema


def upsert_circuit_race_stats(
    conn: Connection, circuit_id: str, season: int, stats: dict
) -> None:
    """Upsert the empirical race-analytics blob for a circuit (one row per circuit-season).

    Re-running for the same (circuit, season) replaces the blob — the whole feed is recomputed
    from the trailing window each run, so there's nothing to merge.
    """
    stmt = insert(schema.circuit_race_stats).values(
        circuit_id=circuit_id, season=season, stats=stats
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["circuit_id", "season"],
        set_={
            "stats": stmt.excluded.stats,
            "updated_at": func.now(),
        },
    )
    conn.execute(stmt)


def list_circuits(conn: Connection) -> list[domain.Circuit]:
    """Gets the list of circuits from database.

    Args:
        conn (Connection): Database connection.

    Returns:
        list[domain.Circuit]: List of circuits as domain dataclass.
    """
    rows = conn.execute(
        select(schema.circuits).order_by(schema.circuits.c.circuit_id)
    ).all()
    return [domain.Circuit.model_validate(row._mapping) for row in rows]


def get_circuit(conn: Connection, circuit_id: str) -> domain.Circuit | None:
    """Fetch a single circuit by its id, or None if it doesn't exist."""
    row = conn.execute(
        select(schema.circuits).where(schema.circuits.c.circuit_id == circuit_id)
    ).first()
    return domain.Circuit.model_validate(row._mapping) if row else None


def get_lap_record_for_circuit(
    conn: Connection, circuit_id: str
) -> domain.LapRecord | None:
    """Fetch the lap record for a circuit, with the holder's names, or None if not set."""
    lr, d = schema.lap_records, schema.drivers
    row = conn.execute(
        select(lr, d.c.given_name, d.c.family_name)
        .join(d, d.c.driver_id == lr.c.driver_id)
        .where(lr.c.circuit_id == circuit_id)
    ).first()
    return domain.LapRecord.model_validate(row._mapping) if row else None


def get_circuit_race_stats(
    conn: Connection, circuit_id: str, season: int
) -> domain.CircuitRaceStats | None:
    """The empirical race-analytics blob for a circuit in a given season, or None."""
    row = conn.execute(
        select(schema.circuit_race_stats).where(
            schema.circuit_race_stats.c.circuit_id == circuit_id,
            schema.circuit_race_stats.c.season == season,
        )
    ).first()
    return domain.CircuitRaceStats.model_validate(row._mapping) if row else None


def calendar_avg_finish_by_grid(conn: Connection, season: int) -> dict[str, float]:
    """Mean finish per grid slot pooled across every circuit's race stats for a season.

    Reads each circuit's ``stats.grid.avg_finish_by_grid`` (itself a per-circuit mean of
    finishes for that grid slot) and averages those across all circuits, giving the
    calendar-wide baseline used as the grey reference on the quali scatterplot. Grid slots
    missing from a circuit simply don't contribute to that slot's average. Returns ``{}``
    when no circuit has race stats for the season.
    """
    rows = conn.execute(
        select(schema.circuit_race_stats.c.stats).where(
            schema.circuit_race_stats.c.season == season
        )
    ).all()
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for (stats,) in rows:
        by_grid = ((stats or {}).get("grid") or {}).get("avg_finish_by_grid") or {}
        for slot, mean_finish in by_grid.items():
            if mean_finish is None:
                continue
            totals[slot] = totals.get(slot, 0.0) + float(mean_finish)
            counts[slot] = counts.get(slot, 0) + 1
    return {slot: round(totals[slot] / counts[slot], 3) for slot in totals}
