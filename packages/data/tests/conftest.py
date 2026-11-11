from __future__ import annotations

import pytest
from formation_sim.data import f1tv


@pytest.fixture(autouse=True)
def _no_real_f1tv_sign_in(monkeypatch):
    """Never let a test reach F1's sign-in: an empty fake session would otherwise make
    `f1tv.auth_problem()` try to sign in for real. Default to "signed in"; tests that
    exercise the signed-out path override it."""
    monkeypatch.setattr(f1tv, "auth_problem", lambda: None)
    monkeypatch.setattr(f1tv, "_known_failure", None)
