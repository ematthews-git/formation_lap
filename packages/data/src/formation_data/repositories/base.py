"""The shared upsert every job writes through."""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel
from sqlalchemy import Connection, Table, func
from sqlalchemy.dialects.postgresql import insert


# Columns the database owns. Excluded from upsert payloads so server defaults
# apply on insert; refreshed explicitly on conflict (ON CONFLICT DO UPDATE does
# not run SQLAlchemy `onupdate` hooks).
_SERVER_MANAGED_COLS = {"updated_at"}


def upsert(
    conn: Connection,
    table: Table,
    items: Iterable[BaseModel],
    conflict_cols: list[str],
    update_exclude: set[str] | None = None,
) -> int:
    """Upsert a batch of domain models into `table`, keyed on `conflict_cols`.

    Auto-id PKs and server-managed columns are excluded from the dump (not via
    `exclude_none` — that would also drop legitimately-None values once nullable
    columns exist, and multi-row inserts need homogeneous keys). On conflict,
    every other non-conflict column is replaced with the incoming row's value.

    `update_exclude` names columns to leave untouched on conflict — used when a
    hand-authored seed shares a table with columns another job populates (e.g.
    the circuits seed must not clobber `track_outline`). Those columns are still
    set on insert (to the incoming value, typically None), just not on update.

    Model fields that aren't columns of `table` are dropped: some read models carry
    fields joined in from another table (a RaceResult's season and round come from
    its race weekend), and those are never written here.
    """
    columns = set(table.c.keys())
    payload = [
        {
            k: v
            for k, v in item.model_dump(exclude={"id"} | _SERVER_MANAGED_COLS).items()
            if k in columns
        }
        for item in items
    ]
    if not payload:
        return 0
    stmt = insert(table).values(payload)
    preserve = _SERVER_MANAGED_COLS | (update_exclude or set())
    update_cols = [
        c.name
        for c in table.c
        if c.name not in conflict_cols
        and not c.primary_key
        and c.name not in preserve
    ]
    if update_cols:
        set_ = {col: stmt.excluded[col] for col in update_cols}
        if "updated_at" in table.c:
            set_["updated_at"] = func.now()
        stmt = stmt.on_conflict_do_update(index_elements=conflict_cols, set_=set_)
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=conflict_cols)
    return conn.execute(stmt).rowcount
