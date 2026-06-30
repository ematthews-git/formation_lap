"""Repository layer — generic upsert + table-specific reads.

Every job writes rows the same way: build a list of domain models, then upsert
keyed on a unique constraint. The single `upsert()` helper covers all 9 tables.

Reads with real logic (filter by date, lookup by composite key) get their own
small functions below — there are only a handful, so keeping them here beats
spreading them across per-table modules.

The one bundled operation is `upsert_strategy_with_stints`, because a strategy
row's auto-id has to land before its child stints can be inserted.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date, timedelta

from pydantic import BaseModel
from sqlalchemy import Connection, Table, func, select
from sqlalchemy.dialects.postgresql import insert

from formation_data import domain, schema

logger = logging.getLogger(__name__)

# Columns the database owns. Excluded from upsert payloads so server defaults
# apply on insert; refreshed explicitly on conflict (ON CONFLICT DO UPDATE does
# not run SQLAlchemy `onupdate` hooks).
_SERVER_MANAGED_COLS = {"updated_at"}


# --- write ---


def upsert(
    conn: Connection,
    table: Table,
    items: Iterable[BaseModel],
    conflict_cols: list[str],
) -> int:
    """Upsert a batch of domain models into `table`, keyed on `conflict_cols`.

    Auto-id PKs and server-managed columns are excluded from the dump (not via
    `exclude_none` — that would also drop legitimately-None values once nullable
    columns exist, and multi-row inserts need homogeneous keys). On conflict,
    every other non-conflict column is replaced with the incoming row's value.
    """
    payload = [
        item.model_dump(exclude={"id"} | _SERVER_MANAGED_COLS) for item in items
    ]  # union op
    if not payload:
        return 0
    stmt = insert(table).values(payload)
    update_cols = [
        c.name
        for c in table.c
        if c.name not in conflict_cols
        and not c.primary_key
        and c.name not in _SERVER_MANAGED_COLS
    ]
    if update_cols:
        set_ = {col: stmt.excluded[col] for col in update_cols}
        if "updated_at" in table.c:
            set_["updated_at"] = func.now()
        stmt = stmt.on_conflict_do_update(index_elements=conflict_cols, set_=set_)
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=conflict_cols)
    return conn.execute(stmt).rowcount


def upsert_strategy_with_stints(
    conn: Connection, strategy: domain.Strategy, stints: list[domain.StrategyStint]
) -> int:
    """Upsert a Strategy and its stints atomically; returns the strategy id.

    Skeleton — needs the RETURNING-style two-step that swaps the new strategy_id
    into each stint before its own upsert.
    """
    # TODO:
    #   strat_stmt = insert(schema.strategies).values(strategy.model_dump(exclude_none=True))
    #   strat_stmt = strat_stmt.on_conflict_do_update(
    #       index_elements=["race_weekend_id", "label"],
    #       set_={"is_base": strat_stmt.excluded.is_base,
    #             "num_stops": strat_stmt.excluded.num_stops},
    #   ).returning(schema.strategies.c.id)
    #   strategy_id = conn.execute(strat_stmt).scalar_one()
    #   for s in stints:
    #       s.strategy_id = strategy_id
    #   upsert(conn, schema.strategy_stints, stints, ["strategy_id", "stint_order"])
    #   return strategy_id
    logger.info(
        "repositories.upsert_strategy_with_stints label=%s stints=%d (skeleton)",
        strategy.label,
        len(stints),
    )
    return 0


# --- read ---


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


def list_race_weekends(conn: Connection, season: int) -> list[domain.RaceWeekend]:
    """All race weekends for a season, in calendar (round) order."""
    rows = conn.execute(
        select(schema.race_weekends)
        .where(schema.race_weekends.c.season == season)
        .order_by(schema.race_weekends.c.round_number)
    ).all()
    return [domain.RaceWeekend.model_validate(row._mapping) for row in rows]


def get_race_weekend(
    conn: Connection, season: int, round_number: int
) -> domain.RaceWeekend | None:
    """Fetch a single race weekend by (season, round_number), or None."""
    row = conn.execute(
        select(schema.race_weekends).where(
            schema.race_weekends.c.season == season,
            schema.race_weekends.c.round_number == round_number,
        )
    ).first()
    return domain.RaceWeekend.model_validate(row._mapping) if row else None


def list_drivers(conn: Connection, season: int) -> list[domain.Driver]:
    """All drivers for a season, ordered by name."""
    rows = conn.execute(
        select(schema.drivers)
        .where(schema.drivers.c.season == season)
        .order_by(schema.drivers.c.full_name)
    ).all()
    return [domain.Driver.model_validate(row._mapping) for row in rows]


def list_standings(
    conn: Connection,
    season: int,
    type: str,
    after_round: int | None = None,
) -> list[domain.Standing]:
    """Championship standings for a season and type ("driver"/"constructor").

    When `after_round` is omitted, returns the most recent round available for
    that season+type. Results are ordered by championship position.
    """
    table = schema.standings
    if after_round is None:
        after_round = conn.execute(
            select(func.max(table.c.after_round)).where(
                table.c.season == season, table.c.type == type
            )
        ).scalar()
        if after_round is None:
            return []
    rows = conn.execute(
        select(table)
        .where(
            table.c.season == season,
            table.c.type == type,
            table.c.after_round == after_round,
        )
        .order_by(table.c.position)
    ).all()
    return [domain.Standing.model_validate(row._mapping) for row in rows]


def next_race_weekend_within(
    conn: Connection, today: date, window: timedelta
) -> domain.RaceWeekend | None:
    # TODO:
    #   stmt = (select(schema.race_weekends)
    #           .where(schema.race_weekends.c.race_date >= today)
    #           .where(schema.race_weekends.c.race_date <= today + window)
    #           .order_by(schema.race_weekends.c.race_date.asc())
    #           .limit(1))
    logger.info(
        "repositories.next_race_weekend_within today=%s window=%s (skeleton)",
        today,
        window,
    )
    return None


def most_recent_race_weekend_before(
    conn: Connection, today: date
) -> domain.RaceWeekend | None:
    # TODO: order_by(race_date.desc()).limit(1) where race_date < today
    logger.info(
        "repositories.most_recent_race_weekend_before today=%s (skeleton)", today
    )
    return None


def get_lap_record_for_circuit(
    conn: Connection, circuit_id: str
) -> domain.LapRecord | None:
    """Fetch the lap record for a circuit, or None if not set."""
    row = conn.execute(
        select(schema.lap_records).where(
            schema.lap_records.c.circuit_id == circuit_id
        )
    ).first()
    return domain.LapRecord.model_validate(row._mapping) if row else None


def get_circuit_stats(
    conn: Connection, circuit_id: str, season: int
) -> domain.CircuitStats | None:
    """Fetch the stats row for a circuit in a given season, or None."""
    row = conn.execute(
        select(schema.circuit_stats).where(
            schema.circuit_stats.c.circuit_id == circuit_id,
            schema.circuit_stats.c.season == season,
        )
    ).first()
    return domain.CircuitStats.model_validate(row._mapping) if row else None
