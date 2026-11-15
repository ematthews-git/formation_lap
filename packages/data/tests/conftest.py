from __future__ import annotations

import os

import pytest
from formation_sim.data import f1tv
from sqlalchemy import make_url

from formation_data import db


@pytest.fixture(autouse=True)
def _no_real_f1tv_access_checks(monkeypatch):
    """Never let a test reach F1's sign-in or archive. An empty fake session would
    otherwise make `f1tv.access_problem()` try to sign in and probe the archive for
    real. Default to "signed in and reachable"; tests for the failure paths override
    it."""
    monkeypatch.setattr(f1tv, "auth_problem", lambda: None)
    monkeypatch.setattr(f1tv, "probe_archive", lambda season: 200)
    monkeypatch.setattr(f1tv, "_known_failure", None)
    monkeypatch.setattr(f1tv, "_checked_access", {})


@pytest.fixture
def engine(monkeypatch):
    """An engine on an emptied throwaway database (FORMATION_TEST_DATABASE_URL, whose name
    must contain "test"). Tests using it are marked to skip when the variable is unset."""
    url = os.environ["FORMATION_TEST_DATABASE_URL"]
    database = make_url(url).database or ""
    assert "test" in database, f"refusing to wipe {database!r}: its name must contain 'test'"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setattr(db, "_engine", None)
    eng = db.get_engine()
    with eng.begin() as conn:
        conn.exec_driver_sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    yield eng
    eng.dispose()
