"""Sync Engine + connection_scope for batch jobs and the API's to_thread shim.

Pure Core — no `Session`. Repositories accept a `Connection`; callers own the
transaction lifecycle via `connection_scope` (or the API equivalent).

Configuration is a single env var: `DATABASE_URL` (sync psycopg2 form). The
engine is created lazily on first use so importing this module has no side
effects and tests can point at a different database before connecting.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Connection, Engine, create_engine

DEFAULT_DATABASE_URL = "postgresql+psycopg2://formation:formation@localhost:5432/formation_lap"

logger = logging.getLogger(__name__)

_engine: Engine | None = None


def _database_url() -> str:
    # Canonical form is sync (psycopg2). Strip a stray async marker in case an
    # older .env still carries one.
    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    return url.replace("+asyncpg", "+psycopg2")


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(_database_url(), future=True)
    return _engine


@contextmanager
def connection_scope() -> Iterator[Connection]:
    """Yield a `Connection` in a transaction.

    Commits on clean exit, rolls back on exception. `engine.begin()` already
    handles both — this wrapper exists purely for the named-export ergonomic.
    """
    with get_engine().begin() as conn:
        yield conn


# Idempotent DDL that `create_all` can't express: adding columns to and swapping the
# unique key on the pre-existing `strategies` table. The DROP finds the old
# (race_weekend_id, label) unique constraint by its column set — not a guessed name —
# so it works whatever Postgres named it. No-ops on a fresh DB where create_all already
# built the new shape.
_STRATEGIES_UPGRADE_SQL = """
ALTER TABLE strategies ADD COLUMN IF NOT EXISTS source varchar NOT NULL DEFAULT 'historical';
ALTER TABLE strategies ADD COLUMN IF NOT EXISTS phase varchar;
ALTER TABLE strategies ADD COLUMN IF NOT EXISTS plausibility double precision;
ALTER TABLE strategies ADD COLUMN IF NOT EXISTS tier varchar;
DO $$
DECLARE old_con text;
BEGIN
  SELECT con.conname INTO old_con
  FROM pg_constraint con
  WHERE con.conrelid = 'strategies'::regclass AND con.contype = 'u'
    AND (SELECT array_agg(att.attname::text ORDER BY att.attname::text)
         FROM unnest(con.conkey) AS k
         JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = k)
        = ARRAY['label', 'race_weekend_id'];
  IF old_con IS NOT NULL THEN
    EXECUTE 'ALTER TABLE strategies DROP CONSTRAINT ' || quote_ident(old_con);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'uq_strategies_weekend_source_label'
      AND conrelid = 'strategies'::regclass
  ) THEN
    ALTER TABLE strategies
      ADD CONSTRAINT uq_strategies_weekend_source_label
      UNIQUE (race_weekend_id, source, label);
  END IF;
END $$;
"""


def upgrade() -> None:
    """Apply the schema to the configured database, idempotently.

    Runs `metadata.create_all` (creates any missing tables, e.g. `sim_race_stats`;
    leaves existing tables untouched) then the `strategies` column/constraint
    migration above. Safe to run repeatedly and on both fresh and existing databases.
    This is the project's schema-apply step in lieu of a migration tool.
    """
    from formation_data import schema

    engine = get_engine()
    schema.metadata.create_all(engine)
    with engine.begin() as conn:
        # exec_driver_sql passes the raw multi-statement script straight to psycopg2 with
        # no bind processing, so the DO block's characters aren't mistaken for parameters.
        conn.exec_driver_sql(_STRATEGIES_UPGRADE_SQL)
    logger.info("db.upgrade: schema applied (create_all + strategies migration)")
