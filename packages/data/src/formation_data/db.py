"""Sync Engine + connection_scope for batch jobs and the API's to_thread shim.

Pure Core — no `Session`. Repositories accept a `Connection`; callers own the
transaction lifecycle via `connection_scope` (or the API equivalent).

Configuration is a single env var: `DATABASE_URL` (sync psycopg2 form). The
engine is created lazily on first use so importing this module has no side
effects and tests can point at a different database before connecting.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Connection, Engine, create_engine

DEFAULT_DATABASE_URL = "postgresql+psycopg2://formation:formation@localhost:5432/formation_lap"

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
