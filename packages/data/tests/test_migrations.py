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


@needs_db
def test_refuses_a_database_built_before_migrations(engine):
    schema.metadata.create_all(engine)
    with pytest.raises(migrate.MigrationError, match="before migrations"):
        migrate.upgrade()
    assert _version(engine) is None


# --- 0003: race history references race_weekends -------------------------------------


def _exec(eng, *statements: str) -> None:
    with eng.begin() as conn:
        for sql in statements:
            conn.exec_driver_sql(sql)


def _circuit(circuit_id: str) -> str:
    return (
        "INSERT INTO circuits (circuit_id, country, track_length_km, num_corners, num_laps, "
        "sm_zones, jolpica_id, fastf1_location, lat, lon) VALUES "
        f"('{circuit_id}', 'X', 5.0, 10, 50, 2, '{circuit_id}', '{circuit_id}', 0, 0)"
    )


def _weekend(circuit_id: str, season: int, rnd: int) -> str:
    return (
        "INSERT INTO race_weekends (circuit_id, season, round_number, event_name, race_date, "
        f"is_sprint) VALUES ('{circuit_id}', {season}, {rnd}, 'GP', '{season}-07-0{rnd % 9 + 1}', false)"
    )


@needs_db
def test_0003_points_history_at_the_right_weekend(engine):
    migrate.upgrade("0002")
    _exec(
        engine,
        _circuit("spielberg"),
        _circuit("singapore"),
        # a 2020 double-header, and a 2026 calendar whose stored round (16) lags the
        # official one the results were written under (17)
        _weekend("spielberg", 2020, 1),
        _weekend("spielberg", 2020, 2),
        _weekend("singapore", 2026, 16),
        "INSERT INTO race_results (circuit_id, season, round_number, position, driver_id, team) "
        "VALUES ('spielberg', 2020, 2, 1, 'hamilton', 'Mercedes'), "
        "('spielberg', 2020, 1, 1, 'bottas', 'Mercedes'), "
        "('singapore', 2026, 17, 1, 'norris', 'McLaren')",
        "INSERT INTO race_traces (circuit_id, season, round_number, trace) "
        "VALUES ('spielberg', 2020, 2, '{}')",
        "INSERT INTO race_overtakes (circuit_id, season, round_number, overtakes) "
        "VALUES ('singapore', 2026, 17, '{}')",
    )
    migrate.upgrade()
    assert migrate.check() == []
    with engine.connect() as conn:
        winners = dict(
            conn.exec_driver_sql("""
                SELECT rw.season || ' R' || rw.round_number, rr.driver_id
                FROM race_results rr JOIN race_weekends rw ON rw.id = rr.race_weekend_id
            """).all()
        )
    assert winners == {"2020 R1": "bottas", "2020 R2": "hamilton", "2026 R16": "norris"}

    # ...and back: the copies come back from the weekend each row points at.
    migrate.downgrade("0002")
    with engine.connect() as conn:
        rows = conn.exec_driver_sql(
            "SELECT season, round_number, circuit_id, driver_id FROM race_results ORDER BY 1, 2"
        ).all()
    assert [tuple(r) for r in rows] == [
        (2020, 1, "spielberg", "bottas"),
        (2020, 2, "spielberg", "hamilton"),
        (2026, 16, "singapore", "norris"),
    ]


@needs_db
def test_0003_refuses_history_with_no_weekend(engine):
    migrate.upgrade("0002")
    _exec(
        engine,
        _circuit("monza"),
        _weekend("monza", 2026, 16),
        "INSERT INTO race_results (circuit_id, season, round_number, position, driver_id, team) "
        "VALUES ('monza', 2020, 8, 1, 'gasly', 'AlphaTauri')",
    )
    with pytest.raises(migrate.MigrationError, match="weekends refresh --season 2020"):
        migrate.upgrade()
    assert _version(engine) == "0002"
    assert "season" in {c["name"] for c in inspect(engine).get_columns("race_results")}


@needs_db
def test_resolve_race_weekend(engine):
    from formation_data import repositories

    migrate.upgrade()
    _exec(
        engine,
        _circuit("silverstone"),
        _circuit("monza"),
        _weekend("silverstone", 2020, 4),
        _weekend("silverstone", 2020, 5),
        _weekend("monza", 2026, 16),
    )
    with engine.connect() as conn:

        def resolve(circuit_id, season, rnd):
            return repositories.resolve_race_weekend(
                conn, season=season, circuit_id=circuit_id, round_number=rnd
            ).round_number

        assert resolve("silverstone", 2020, 5) == 5  # double-header: the round decides
        assert resolve("monza", 2026, 17) == 16  # one visit: a lagging round still matches
        with pytest.raises(repositories.RaceWeekendNotFound, match="none is round 6"):
            resolve("silverstone", 2020, 6)
        with pytest.raises(repositories.RaceWeekendNotFound, match="--season 2021"):
            resolve("monza", 2021, 14)
