"""every strategy generation is kept as a run

Until now a weekend held one set of strategies per source: each run deleted the
previous one's rows, and `sim_race_stats` kept one stats blob per weekend, so once
postquali ran there was no record of what prelim had said.

This adds `strategy_runs`, one row per generation (source, phase, the sim's stats
blob, when it ran), points `strategies` at their run instead of carrying the weekend,
source and phase themselves, and drops `sim_race_stats` into the runs. Strategies and
stints now go when their run does (ON DELETE CASCADE). The `current_strategy_runs`
view picks the latest run per weekend and source, which is what the API shows.

Each weekend's existing rows become at most two runs: its historical strategies, and
its sim strategies together with its sim_race_stats row. The upgrade checks first that
each weekend's sim strategies came from one run and that it's the run sim_race_stats
describes; if any don't, it lists them and changes nothing.

Downgrading keeps only each weekend's current run per source, since the old tables
can hold no more than that.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-15 20:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from formation_data.migrate import MigrationError

revision: str = '0005'
down_revision: str | Sequence[str] | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PHASES = ("prelim", "postquali")

# Latest run first within each (weekend, source); id breaks a tie in generated_at.
_CURRENT_RUNS = """
    SELECT DISTINCT ON (race_weekend_id, source)
        id, race_weekend_id, source, phase, stats, generated_at
    FROM strategy_runs
    ORDER BY race_weekend_id, source, generated_at DESC, id DESC
"""


def _problems(bind) -> list[str]:
    """Rows that don't fit one run per (weekend, source)."""
    problems: list[str] = []
    sim_phase: dict[int, str] = {}
    for weekend_id, season, rnd, source, phases in bind.exec_driver_sql(
        "SELECT s.race_weekend_id, rw.season, rw.round_number, s.source, "
        "array_agg(DISTINCT s.phase) FROM strategies s "
        "JOIN race_weekends rw ON rw.id = s.race_weekend_id GROUP BY 1, 2, 3, 4"
    ):
        where = f"strategies {season} R{rnd}"
        if source == "historical":
            if phases != [None]:
                problems.append(f"{where}: historical rows with a phase {phases}")
        elif source == "sim":
            if len(phases) != 1 or phases[0] not in _PHASES:
                problems.append(f"{where}: sim rows from more than one run {phases}")
            else:
                sim_phase[weekend_id] = phases[0]
        else:
            problems.append(f"{where}: source {source!r}")
    for weekend_id, season, rnd, phase in bind.exec_driver_sql(
        "SELECT r.race_weekend_id, rw.season, rw.round_number, r.phase FROM sim_race_stats r "
        "JOIN race_weekends rw ON rw.id = r.race_weekend_id"
    ):
        where = f"sim_race_stats {season} R{rnd}"
        if phase not in _PHASES:
            problems.append(f"{where}: phase {phase!r}")
        elif sim_phase.get(weekend_id, phase) != phase:
            problems.append(
                f"{where}: says {phase}, but its sim strategies say {sim_phase[weekend_id]}"
            )
    return problems


def upgrade() -> None:
    bind = op.get_bind()
    problems = _problems(bind)
    if problems:
        listed = "\n".join(f"  {p}" for p in sorted(problems))
        raise MigrationError(
            "Some strategies don't fit one run per weekend and source, so 0005 wasn't "
            f"applied and nothing changed:\n{listed}\n"
            "Delete those weekends' strategies (and stints) and sim_race_stats rows, run "
            "`formation-data db upgrade`, then generate them again."
        )

    op.create_table(
        "strategy_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("race_weekend_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("phase", sa.String(), nullable=True),
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(source = 'historical' AND phase IS NULL) OR "
            "(source = 'sim' AND phase IS NOT NULL AND phase IN ('prelim', 'postquali'))",
            name=op.f("strategy_runs_source_phase_check"),
        ),
        sa.ForeignKeyConstraint(
            ["race_weekend_id"],
            ["race_weekends.id"],
            name=op.f("strategy_runs_race_weekend_id_fkey"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("strategy_runs_pkey")),
    )
    # One run per weekend and source. A run took its strategies' timestamp, or the sim
    # stats' (the two were written in one transaction, so they agree).
    bind.exec_driver_sql(
        """
        INSERT INTO strategy_runs (race_weekend_id, source, phase, stats, generated_at)
        SELECT race_weekend_id, source, phase, stats, generated_at FROM (
            SELECT race_weekend_id, 'historical' AS source, NULL AS phase,
                   NULL::jsonb AS stats, max(updated_at) AS generated_at
            FROM strategies WHERE source = 'historical' GROUP BY race_weekend_id
            UNION ALL
            SELECT race_weekend_id, 'sim', phase, stats, generated_at FROM sim_race_stats
            UNION ALL
            SELECT s.race_weekend_id, 'sim', min(s.phase), NULL, max(s.updated_at)
            FROM strategies s
            WHERE s.source = 'sim' AND NOT EXISTS (
                SELECT 1 FROM sim_race_stats r WHERE r.race_weekend_id = s.race_weekend_id
            )
            GROUP BY s.race_weekend_id
        ) runs
        ORDER BY generated_at, race_weekend_id, source
        """
    )

    op.add_column("strategies", sa.Column("run_id", sa.Integer(), nullable=True))
    bind.exec_driver_sql(
        "UPDATE strategies s SET run_id = r.id FROM strategy_runs r "
        "WHERE r.race_weekend_id = s.race_weekend_id AND r.source = s.source"
    )
    op.alter_column("strategies", "run_id", existing_type=sa.Integer(), nullable=False)
    op.drop_constraint("uq_strategies_weekend_source_label", "strategies", type_="unique")
    op.drop_constraint("strategies_race_weekend_id_fkey", "strategies", type_="foreignkey")
    for col in ("race_weekend_id", "source", "phase", "updated_at"):
        op.drop_column("strategies", col)
    op.create_foreign_key(
        "strategies_run_id_fkey",
        "strategies",
        "strategy_runs",
        ["run_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "strategies_run_id_label_key", "strategies", ["run_id", "label"]
    )

    op.drop_constraint("strategy_stints_strategy_id_fkey", "strategy_stints", type_="foreignkey")
    op.create_foreign_key(
        "strategy_stints_strategy_id_fkey",
        "strategy_stints",
        "strategies",
        ["strategy_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_table("sim_race_stats")
    op.execute(f"CREATE VIEW current_strategy_runs AS {_CURRENT_RUNS}")


def downgrade() -> None:
    bind = op.get_bind()
    op.execute("DROP VIEW current_strategy_runs")
    # The old tables hold one set per weekend and source: keep each one's current run.
    # Its strategies and stints go with the others (ON DELETE CASCADE).
    bind.exec_driver_sql(
        f"DELETE FROM strategy_runs WHERE id NOT IN (SELECT id FROM ({_CURRENT_RUNS}) cur)"
    )

    op.create_table(
        "sim_race_stats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("race_weekend_id", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["race_weekend_id"],
            ["race_weekends.id"],
            name=op.f("sim_race_stats_race_weekend_id_fkey"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("sim_race_stats_pkey")),
        sa.UniqueConstraint("race_weekend_id", name=op.f("sim_race_stats_race_weekend_id_key")),
    )
    bind.exec_driver_sql(
        "INSERT INTO sim_race_stats (race_weekend_id, phase, generated_at, stats) "
        "SELECT race_weekend_id, phase, generated_at, stats FROM strategy_runs "
        "WHERE source = 'sim' AND stats IS NOT NULL ORDER BY generated_at"
    )

    op.drop_constraint("strategy_stints_strategy_id_fkey", "strategy_stints", type_="foreignkey")
    op.create_foreign_key(
        "strategy_stints_strategy_id_fkey",
        "strategy_stints",
        "strategies",
        ["strategy_id"],
        ["id"],
    )

    op.add_column("strategies", sa.Column("race_weekend_id", sa.Integer(), nullable=True))
    op.add_column(
        "strategies",
        sa.Column("source", sa.String(), server_default="historical", nullable=False),
    )
    op.add_column("strategies", sa.Column("phase", sa.String(), nullable=True))
    op.add_column(
        "strategies",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    bind.exec_driver_sql(
        "UPDATE strategies s SET race_weekend_id = r.race_weekend_id, source = r.source, "
        "phase = r.phase, updated_at = r.generated_at FROM strategy_runs r WHERE r.id = s.run_id"
    )
    op.alter_column("strategies", "race_weekend_id", existing_type=sa.Integer(), nullable=False)
    op.drop_constraint("strategies_run_id_label_key", "strategies", type_="unique")
    op.drop_constraint("strategies_run_id_fkey", "strategies", type_="foreignkey")
    op.drop_column("strategies", "run_id")
    op.create_foreign_key(
        "strategies_race_weekend_id_fkey",
        "strategies",
        "race_weekends",
        ["race_weekend_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_strategies_weekend_source_label",
        "strategies",
        ["race_weekend_id", "source", "label"],
    )
    op.drop_table("strategy_runs")
