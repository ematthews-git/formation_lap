"""Tests for the compound-nomination bridge (formation_data.nominations).

Reads the real shared table (formation_sim/config/nominations.yaml) — no DB or
network. Guards the two non-trivial behaviours: cross-season venue-rename aliasing and
the fallback for circuits with no nomination.
"""

from __future__ import annotations

from formation_data.nominations import compounds_for


def test_returns_soft_medium_hard_codes():
    # Barcelona 2026 is nominated [hard, medium, soft] = [2, 3, 4] in the yaml.
    assert compounds_for(2026, "Barcelona") == ("C4", "C3", "C2")


def test_resolves_renamed_venue_via_alias():
    # circuits seed stores the 2026 names; the yaml keys the pre-rename spellings.
    assert compounds_for(2026, "Miami Gardens") == compounds_for(2026, "Miami")
    assert compounds_for(2026, "Yas Marina") == compounds_for(2026, "Yas Island")
    assert compounds_for(2026, "Monte Carlo") == ("C5", "C4", "C3")


def test_preserves_skip_nomination_gaps():
    # Austin 2026 is a non-adjacent "skip" nomination [1, 3, 4] — the detail a flat
    # default (C3/C4/C5) cannot express.
    assert compounds_for(2026, "Austin") == ("C4", "C3", "C1")


def test_unnominated_circuit_returns_none():
    # New Madrid venue has no history / no nomination entry.
    assert compounds_for(2026, "Madrid") is None


def test_missing_season_returns_none():
    assert compounds_for(1999, "Monza") is None
