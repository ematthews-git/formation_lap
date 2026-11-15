"""race_weekends: allow an unknown tyre allocation

A weekend's soft/medium/hard compounds come from the Pirelli nomination table, which
starts in 2021. Backfilling the 2020 calendar (so 2020 results have a race to point at,
see 0003) would otherwise have to invent an allocation. NULL now means "no nomination on
file" for a past season; current and future seasons still fall back to a default so a
new venue stays usable before Pirelli publishes.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-13 15:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0002'
down_revision: str | Sequence[str] | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = ("soft_compound", "medium_compound", "hard_compound")


def upgrade() -> None:
    for column in _COLUMNS:
        op.alter_column("race_weekends", column, existing_type=sa.String(length=5), nullable=True)


def downgrade() -> None:
    nulls = op.get_bind().exec_driver_sql(
        "SELECT count(*) FROM race_weekends WHERE soft_compound IS NULL "
        "OR medium_compound IS NULL OR hard_compound IS NULL"
    ).scalar_one()
    if nulls:
        raise RuntimeError(
            f"{nulls} race weekends have no tyre allocation, so the compound columns can't "
            "be made NOT NULL again. Fill or delete those rows first."
        )
    for column in _COLUMNS:
        op.alter_column("race_weekends", column, existing_type=sa.String(length=5), nullable=False)
