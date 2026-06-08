"""Sync Engine + connection_scope for batch jobs and the API's to_thread shim.

Pure Core — no `Session`. Repositories accept a `Connection`; callers own the
transaction lifecycle via `connection_scope` (or the API equivalent).
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Connection, create_engine

DEFAULT_DATABASE_URL = "postgresql+psycopg2://formation:formation@localhost:5432/formation_lap"


def _database_url() -> str:
    # The API stores its URL as postgresql+asyncpg for FastAPI/asyncpg; the data
    # package always wants a sync driver. Strip the async marker if present.
    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    return url.replace("+asyncpg", "+psycopg2")


engine = create_engine(_database_url(), future=True)


@contextmanager
def connection_scope() -> Iterator[Connection]:
    """Yield a `Connection` in a transaction.

    Commits on clean exit, rolls back on exception. `engine.begin()` already
    handles both — this wrapper exists purely for the named-export ergonomic.
    """
    with engine.begin() as conn:
        yield conn
