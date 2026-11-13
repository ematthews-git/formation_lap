"""Migrations build exactly what schema.py declares, and adopt pre-Alembic databases safely.

The database tests need a throwaway Postgres: set FORMATION_TEST_DATABASE_URL to a
database whose name contains "test" (CI provides one). Its public schema is dropped and
recreated before each test. Without the variable they're skipped.

    docker exec formation_lap_db createdb -U formation formation_lap_test
    FORMATION_TEST_DATABASE_URL=postgresql+psycopg2://formation:formation@localhost:5432/formation_lap_test \\
        uv run pytest packages/data/tests/test_migrations.py
"""

from __future__ import annotations

import os
import re

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, make_url

from formation_data import db, migrate, schema

TEST_URL = os.environ.get("FORMATION_TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not TEST_URL, reason="FORMATION_TEST_DATABASE_URL not set")


def test_revisions_form_one_line_with_ids_matching_filenames():
    script = ScriptDirectory.from_config(migrate.config())
    assert len(script.get_heads()) == 1, "two revisions share a parent; merge or rebase one"
    revisions = list(script.walk_revisions())  # newest first
    for n, rev in enumerate(reversed(revisions), start=1):
        assert rev.revision == f"{n:04d}"
        assert re.match(rf"{rev.revision}_\w+\.py$", os.path.basename(rev.path))
    assert revisions[-1].revision == migrate.BASELINE_REVISION


@pytest.fixture
def engine(monkeypatch):
    database = make_url(TEST_URL).database or ""
    assert "test" in database, f"refusing to wipe {database!r}: its name must contain 'test'"
    monkeypatch.setenv("DATABASE_URL", TEST_URL)
    monkeypatch.setattr(db, "_engine", None)
    eng = db.get_engine()
    with eng.begin() as conn:
        conn.exec_driver_sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    yield eng
    eng.dispose()


def _tables(eng) -> set[str]:
    with eng.connect() as conn:
        return set(inspect(conn).get_table_names())


def _version(eng) -> str | None:
    with eng.connect() as conn:
        return migrate.current_revision(conn)


@needs_db
def test_upgrade_from_empty_matches_schema_py(engine):
    assert migrate.upgrade() == (None, migrate.head_revision())
    assert migrate.check() == []
    assert _tables(engine) == set(schema.metadata.tables) | {"alembic_version"}


@needs_db
def test_downgrade_to_base_and_back(engine):
    migrate.upgrade()
    migrate.downgrade("base")
    assert _tables(engine) == {"alembic_version"}
    migrate.upgrade()
    assert migrate.check() == []


@needs_db
def test_upgrade_is_a_no_op_when_current(engine):
    _, head = migrate.upgrade()
    assert migrate.upgrade() == (head, head)


def _build_pre_alembic_database(eng, *extra_sql: str) -> None:
    """A database as the old `db upgrade` left it, before the strategies patch."""
    schema.metadata.create_all(eng)
    with eng.begin() as conn:
        conn.exec_driver_sql("DROP TABLE race_overtakes")
        conn.exec_driver_sql(
            "ALTER TABLE strategies DROP CONSTRAINT uq_strategies_weekend_source_label, "
            "DROP COLUMN source, DROP COLUMN phase, DROP COLUMN plausibility, "
            "DROP COLUMN tier, ADD CONSTRAINT strategies_race_weekend_id_label_key "
            "UNIQUE (race_weekend_id, label)"
        )
        conn.exec_driver_sql(
            "ALTER TABLE circuit_stats ADD COLUMN pit_loss_normal float NOT NULL, "
            "ADD COLUMN undercut_strength float NOT NULL"
        )
        conn.exec_driver_sql("ALTER TABLE circuits ALTER COLUMN track_outline TYPE varchar")
        for sql in extra_sql:
            conn.exec_driver_sql(sql)


def _circuit_stats_columns(eng) -> set[str]:
    with eng.connect() as conn:
        return {c["name"] for c in inspect(conn).get_columns("circuit_stats")}


adoption = pytest.mark.skipif(
    migrate.head_revision() != migrate.BASELINE_REVISION,
    reason="adopting pre-Alembic databases is only supported until the first revision after 0001",
)


@needs_db
@adoption
def test_adopts_a_pre_alembic_database(engine):
    _build_pre_alembic_database(engine)
    migrate.upgrade()
    assert _version(engine) == migrate.BASELINE_REVISION
    assert migrate.check() == []
    assert "pit_loss_normal" not in _circuit_stats_columns(engine)


@needs_db
@adoption
def test_refuses_and_rolls_back_a_drifted_database(engine):
    _build_pre_alembic_database(engine, "ALTER TABLE race_results ADD COLUMN grid int")
    with pytest.raises(migrate.MigrationError, match="race_results"):
        migrate.upgrade()
    assert _version(engine) is None
    assert "race_overtakes" not in _tables(engine)  # the fix-ups were rolled back too
    assert "pit_loss_normal" in _circuit_stats_columns(engine)
