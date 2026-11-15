"""race history references race_weekends instead of copying season and round

race_results, race_traces and race_overtakes each stored their own circuit_id, season
and round_number and were matched to the calendar and to each other on those values.
The copies drifted when a mid-season insertion renumbered the calendar, and code had to
work around it (matching results on circuit and season because the round "isn't a safe
join key"). Each row now references its race's `race_weekends.id`, and season, round and
circuit live only on the weekend, so a renumber changes one row.

Every row is matched to a weekend on season and circuit, using the round only to tell a
double-header's two visits apart (the round alone has drifted before). That needs every
season the tables hold to be in race_weekends: if any row has no weekend, the upgrade
stops, lists the seasons, and changes nothing.

derived_artifacts keeps its (year, round_number) key: it's the simulator's cache of
FastF1 frames, addressed in FastF1's own terms, and it covers races at venues with no
`circuits` row (so no weekend) that the simulator still learns from.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-13 15:05:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from formation_data.migrate import MigrationError

revision: str = '0003'
down_revision: str | Sequence[str] | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# table -> the unique key that included season and round, and the one that replaces it
_TABLES = {
    "race_results": (["season", "round_number", "position"], ["race_weekend_id", "position"]),
    "race_traces": (["season", "round_number"], ["race_weekend_id"]),
    "race_overtakes": (["season", "round_number"], ["race_weekend_id"]),
}


def _key_name(table: str, columns: list[str]) -> str:
    # schema.NAMING_CONVENTION's "uq" pattern, which is also what Postgres named the old keys.
    return f"{table}_{'_'.join(columns)}_key"


def upgrade() -> None:
    bind = op.get_bind()
    for table in _TABLES:
        op.add_column(table, sa.Column("race_weekend_id", sa.Integer(), nullable=True))
        # Season + circuit identify the race; the round only breaks a double-header tie,
        # which is the one case where (season, circuit) matches more than one weekend.
        bind.exec_driver_sql(f"""
            UPDATE {table} t SET race_weekend_id = rw.id
            FROM race_weekends rw
            WHERE rw.season = t.season AND rw.circuit_id = t.circuit_id
              AND (rw.round_number = t.round_number
                   OR NOT EXISTS (SELECT 1 FROM race_weekends other
                                  WHERE other.season = rw.season
                                    AND other.circuit_id = rw.circuit_id
                                    AND other.id <> rw.id))
        """)

    unmatched = []
    for table in _TABLES:
        for season, n in bind.exec_driver_sql(
            f"SELECT season, count(*) FROM {table} WHERE race_weekend_id IS NULL "
            "GROUP BY season ORDER BY season"
        ):
            unmatched.append((table, season, n))
    if unmatched:
        seasons = sorted({season for _, season, _ in unmatched})
        listed = "\n".join(f"  {table}: {n} rows from {season}" for table, season, n in unmatched)
        raise MigrationError(
            "Some race history has no race weekend to point at, so 0003 wasn't applied and "
            f"nothing changed:\n{listed}\n"
            "Load those seasons' calendars, then upgrade again:\n"
            "  formation-data db upgrade --to 0002\n"
            + "".join(f"  formation-data weekends refresh --season {s}\n" for s in seasons)
            + "  formation-data db upgrade"
        )

    for table, (old_key, new_key) in _TABLES.items():
        op.drop_constraint(_key_name(table, old_key), table, type_="unique")
        op.drop_constraint(f"{table}_circuit_id_fkey", table, type_="foreignkey")
        op.drop_column(table, "circuit_id")
        op.drop_column(table, "season")
        op.drop_column(table, "round_number")
        op.alter_column(table, "race_weekend_id", existing_type=sa.Integer(), nullable=False)
        op.create_foreign_key(
            f"{table}_race_weekend_id_fkey", table, "race_weekends", ["race_weekend_id"], ["id"]
        )
        op.create_unique_constraint(_key_name(table, new_key), table, new_key)


def downgrade() -> None:
    bind = op.get_bind()
    for table, (old_key, new_key) in _TABLES.items():
        op.add_column(table, sa.Column("circuit_id", sa.String(length=50), nullable=True))
        op.add_column(table, sa.Column("season", sa.Integer(), nullable=True))
        op.add_column(table, sa.Column("round_number", sa.Integer(), nullable=True))
        bind.exec_driver_sql(f"""
            UPDATE {table} t
            SET circuit_id = rw.circuit_id, season = rw.season, round_number = rw.round_number
            FROM race_weekends rw WHERE rw.id = t.race_weekend_id
        """)
        for column in ("circuit_id", "season", "round_number"):
            op.alter_column(table, column, nullable=False)
        op.drop_constraint(_key_name(table, new_key), table, type_="unique")
        op.drop_constraint(f"{table}_race_weekend_id_fkey", table, type_="foreignkey")
        op.drop_column(table, "race_weekend_id")
        op.create_foreign_key(
            f"{table}_circuit_id_fkey", table, "circuits", ["circuit_id"], ["circuit_id"]
        )
        op.create_unique_constraint(_key_name(table, old_key), table, old_key)
