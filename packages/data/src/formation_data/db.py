"""Sync Session factory for batch jobs.

Jobs are long-running and not request-scoped, so they use a plain sync engine
rather than the API's async one in `formation_api.database`.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_DATABASE_URL = "postgresql+psycopg2://formation:formation@localhost:5432/formation_lap"


def _database_url() -> str:
    # The API stores its URL as postgresql+asyncpg; jobs need a sync driver.
    # Honour DATABASE_URL when set, otherwise fall back to local docker-compose creds.
    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    return url.replace("+asyncpg", "+psycopg2")


engine = create_engine(_database_url(), future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Yield a session, committing on success and rolling back on error."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
