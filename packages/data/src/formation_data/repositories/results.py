"""Race results and championship standings."""

from __future__ import annotations

from sqlalchemy import Connection, and_, delete, exists, func, select

from formation_data import domain, schema
from formation_data.repositories.base import upsert


def replace_standings(
    conn: Connection,
    race_weekend_id: int,
    drivers: list[domain.DriverStanding],
    constructors: list[domain.ConstructorStanding],
) -> None:
    """Store the standings after one race, replacing whatever that race had before, so a
    driver dropped from a corrected table doesn't linger."""
    for table, items, key in (
        (schema.driver_standings, drivers, "driver_id"),
        (schema.constructor_standings, constructors, "team_id"),
    ):
        conn.execute(delete(table).where(table.c.race_weekend_id == race_weekend_id))
        upsert(conn, table, items, ["race_weekend_id", key])


def list_standings(
    conn: Connection,
    season: int,
    type: str,
    after_round: int | None = None,
) -> list[domain.Standing]:
    """Championship standings for a season and type ("driver"/"constructor").

    When `after_round` is omitted, returns the standings after the latest race that has
    them. Results are ordered by championship position.
    """
    rw = schema.race_weekends
    if type == "driver":
        table, d = schema.driver_standings, schema.drivers
        cols = (
            (d.c.given_name + " " + d.c.family_name).label("name"),
            table.c.driver_id,
        )
        joined = table.join(rw, rw.c.id == table.c.race_weekend_id).join(
            d, d.c.driver_id == table.c.driver_id
        )
    else:
        table, ts = schema.constructor_standings, schema.team_seasons
        cols = (ts.c.name, table.c.team_id)
        joined = table.join(rw, rw.c.id == table.c.race_weekend_id).join(
            ts, and_(ts.c.team_id == table.c.team_id, ts.c.season == rw.c.season)
        )
    if after_round is None:
        after_round = conn.execute(
            select(func.max(rw.c.round_number))
            .select_from(table.join(rw, rw.c.id == table.c.race_weekend_id))
            .where(rw.c.season == season)
        ).scalar()
        if after_round is None:
            return []
    rows = conn.execute(
        select(
            table.c.race_weekend_id,
            rw.c.season,
            rw.c.round_number.label("after_round"),
            table.c.position,
            table.c.points,
            *cols,
        )
        .select_from(joined)
        .where(rw.c.season == season, rw.c.round_number == after_round)
        .order_by(table.c.position)
    ).all()
    return [domain.Standing.model_validate({**row._mapping, "type": type}) for row in rows]


def _race_results_with_names():
    """SELECT race results with the weekend's circuit, season and round, the driver's
    names, and the team's name that season — the RaceResult read shape."""
    rr, rw, d, ts = (
        schema.race_results,
        schema.race_weekends,
        schema.drivers,
        schema.team_seasons,
    )
    return (
        select(
            rr,
            rw.c.circuit_id,
            rw.c.season,
            rw.c.round_number,
            d.c.given_name,
            d.c.family_name,
            d.c.code,
            ts.c.name.label("team"),
        )
        .join(rw, rw.c.id == rr.c.race_weekend_id)
        .join(d, d.c.driver_id == rr.c.driver_id)
        .join(ts, and_(ts.c.team_id == rr.c.team_id, ts.c.season == rw.c.season))
    )


def list_circuit_podiums(
    conn: Connection, circuit_id: str, limit: int = 5
) -> list[domain.RaceResult]:
    """Top-3 finishers for the most recent `limit` races at a circuit.

    Rows are ordered most-recent race first, then finishing position; the caller
    groups consecutive rows sharing (season, round_number) into one race. Returns
    fewer than `limit` races (or `[]`) when the circuit lacks that much history.
    """
    rr, rw = schema.race_results, schema.race_weekends
    weekend_ids = (
        conn.execute(
            select(rw.c.id)
            .where(
                rw.c.circuit_id == circuit_id,
                exists().where(rr.c.race_weekend_id == rw.c.id),
            )
            .order_by(rw.c.season.desc(), rw.c.round_number.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    if not weekend_ids:
        return []
    rows = conn.execute(
        _race_results_with_names()
        .where(rr.c.race_weekend_id.in_(weekend_ids), rr.c.position <= 3)
        .order_by(rw.c.season.desc(), rw.c.round_number.desc(), rr.c.position.asc())
    ).all()
    return [domain.RaceResult.model_validate(row._mapping) for row in rows]


def list_race_results(conn: Connection, season: int) -> list[domain.RaceResult]:
    """All race results for a season, ordered by round then finishing position."""
    rr, rw = schema.race_results, schema.race_weekends
    rows = conn.execute(
        _race_results_with_names()
        .where(rw.c.season == season)
        .order_by(rw.c.round_number, rr.c.position)
    ).all()
    return [domain.RaceResult.model_validate(row._mapping) for row in rows]
