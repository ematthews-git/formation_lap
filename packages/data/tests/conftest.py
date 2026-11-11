from __future__ import annotations

import pytest
from formation_sim.data import f1tv


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
