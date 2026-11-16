"""Per-race blobs computed from FastF1: lap traces, overtakes and derived tables."""

from __future__ import annotations

from sqlalchemy import Connection, Table, func, select
from sqlalchemy.dialects.postgresql import insert

from formation_data import domain, schema
from formation_data.repositories.drivers_teams import fastf1_team_ids


def upsert_race_trace(conn: Connection, race_weekend_id: int, trace: dict) -> None:
    """Upsert one race's lap-by-lap trace blob (one row per race weekend).

    Re-running for the same race replaces the blob — it's recomputed wholesale from the
    FastF1 session, so there's nothing to merge.
    """
    stmt = insert(schema.race_traces).values(race_weekend_id=race_weekend_id, trace=trace)
    stmt = stmt.on_conflict_do_update(
        index_elements=["race_weekend_id"],
        set_={"trace": stmt.excluded.trace, "updated_at": func.now()},
    )
    conn.execute(stmt)


def upsert_race_overtakes(conn: Connection, race_weekend_id: int, overtakes: dict) -> None:
    """Upsert one race's classified overtake blob (one row per race weekend).

    Re-running replaces the blob wholesale — it is recomputed from the FastF1 session, so
    there is nothing to merge.
    """
    stmt = insert(schema.race_overtakes).values(
        race_weekend_id=race_weekend_id, overtakes=overtakes
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["race_weekend_id"],
        set_={"overtakes": stmt.excluded.overtakes, "updated_at": func.now()},
    )
    conn.execute(stmt)


def upsert_derived_artifact(
    conn: Connection,
    *,
    kind: str,
    season: int,
    round_number: int,
    data: bytes,
    data_format: str = "parquet",
) -> None:
    """Upsert one serialized per-race derived table (one row per kind+season+round).

    Re-dumping a race replaces its blob — the frame is regenerated wholesale, nothing to merge.
    """
    stmt = insert(schema.derived_artifacts).values(
        kind=kind,
        season=season,
        round_number=round_number,
        data=data,
        data_format=data_format,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["kind", "season", "round_number"],
        set_={
            "data": stmt.excluded.data,
            "data_format": stmt.excluded.data_format,
            "updated_at": func.now(),
        },
    )
    conn.execute(stmt)


def get_derived_artifact(
    conn: Connection, *, kind: str, season: int, round_number: int
) -> domain.DerivedArtifact | None:
    """The serialized derived table for (kind, season, round), or None if not stored."""
    row = conn.execute(
        select(schema.derived_artifacts).where(
            schema.derived_artifacts.c.kind == kind,
            schema.derived_artifacts.c.season == season,
            schema.derived_artifacts.c.round_number == round_number,
        )
    ).first()
    return domain.DerivedArtifact.model_validate(row._mapping) if row else None


def _with_weekend(table: Table):
    """SELECT every column of a race-history table plus its weekend's circuit_id, season
    and round_number, which the read models (RaceTrace, RaceOvertakes) carry."""
    rw = schema.race_weekends
    return select(table, rw.c.circuit_id, rw.c.season, rw.c.round_number).join(
        rw, rw.c.id == table.c.race_weekend_id
    )


def list_race_traces_for_circuit(
    conn: Connection, circuit_id: str, limit: int = 5
) -> list[domain.RaceTrace]:
    """The most recent race traces for a circuit, newest first.

    Each driver in a trace carries the FastF1 team name it was built with; `team_id` is
    added here from team_seasons (None for a name that isn't on file), so the frontend
    colours by team without matching names.
    """
    rw = schema.race_weekends
    rows = conn.execute(
        _with_weekend(schema.race_traces)
        .where(rw.c.circuit_id == circuit_id)
        .order_by(rw.c.season.desc(), rw.c.round_number.desc())
        .limit(limit)
    ).all()
    traces = [domain.RaceTrace.model_validate(row._mapping) for row in rows]
    team_ids = fastf1_team_ids(conn, {t.season for t in traces})
    for t in traces:
        for driver in t.trace.get("drivers") or []:
            driver["team_id"] = team_ids.get((t.season, driver.get("team")))
    return traces


def get_race_overtakes(
    conn: Connection, season: int, round_number: int
) -> domain.RaceOvertakes | None:
    """One race's classified overtake blob, or None."""
    rw = schema.race_weekends
    row = conn.execute(
        _with_weekend(schema.race_overtakes).where(
            rw.c.season == season, rw.c.round_number == round_number
        )
    ).first()
    return domain.RaceOvertakes.model_validate(row._mapping) if row else None


def list_race_overtakes_for_circuit(
    conn: Connection, circuit_id: str, limit: int = 5
) -> list[domain.RaceOvertakes]:
    """The most recent overtake blobs for a circuit, newest first."""
    rw = schema.race_weekends
    rows = conn.execute(
        _with_weekend(schema.race_overtakes)
        .where(rw.c.circuit_id == circuit_id)
        .order_by(rw.c.season.desc(), rw.c.round_number.desc())
        .limit(limit)
    ).all()
    return [domain.RaceOvertakes.model_validate(row._mapping) for row in rows]
