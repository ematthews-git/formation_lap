"""Tests for the calendar jobs' pure pieces (no DB, no network):

- jobs.pre_season.race_weekends._local_race_date — Jolpica's UTC date vs FastF1's local date
- the hand-curated 2026 seed — internal consistency, so a mis-typed round can't slip in
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pandas as pd

from formation_data.jobs.pre_season import race_weekends as refresh
from formation_data.jobs.static import circuits as circuit_seed
from formation_data.jobs.static import race_weekends as seed
from formation_data.nominations import compounds_for


def _circuit(location: str, circuit_id: str = "x"):
    return SimpleNamespace(circuit_id=circuit_id, fastf1_location=location)


def _event(location: str, d: date):
    return SimpleNamespace(Location=location, EventDate=pd.Timestamp(d))


# --- local race date ---


def test_fastf1_local_date_wins_over_jolpica_utc_date():
    # Las Vegas: race starts 04:00Z on the 22nd = Saturday evening local on the 21st
    race = {"round": "21", "date": "2026-11-22"}
    got = refresh._local_race_date(
        race, _circuit("Las Vegas", "las_vegas"), _event("Las Vegas", date(2026, 11, 21))
    )
    assert got == date(2026, 11, 21)


def test_falls_back_to_jolpica_without_fastf1():
    race = {"round": "16", "date": "2026-10-04"}
    assert refresh._local_race_date(race, _circuit("Kuala Lumpur"), None) == date(2026, 10, 4)


def test_ignores_fastf1_when_it_is_a_different_circuit():
    # FastF1 hasn't caught up with a renumbering: its round 16 is still Marina Bay
    race = {"round": "16", "date": "2026-10-04"}
    got = refresh._local_race_date(
        race, _circuit("Kuala Lumpur"), _event("Marina Bay", date(2026, 10, 11))
    )
    assert got == date(2026, 10, 4)


def test_ignores_fastf1_date_more_than_a_day_off():
    race = {"round": "16", "date": "2026-10-04"}
    got = refresh._local_race_date(
        race, _circuit("Kuala Lumpur"), _event("Kuala Lumpur", date(2026, 10, 11))
    )
    assert got == date(2026, 10, 4)


def test_renamed_venue_matches_via_alias():
    # circuits seed stores "Miami Gardens"; an older FastF1 schedule says "Miami"
    race = {"round": "4", "date": "2026-05-03"}
    got = refresh._local_race_date(
        race, _circuit("Miami Gardens", "miami"), _event("Miami", date(2026, 5, 3))
    )
    assert got == date(2026, 5, 3)


# --- the hand-curated seed ---


def test_2026_seed_rounds_are_contiguous_and_unique():
    rounds = [row[0] for row in seed._CALENDAR_2026]
    assert rounds == list(range(1, len(rounds) + 1))


def test_2026_seed_circuits_are_all_seeded_and_unique():
    seeded = {c.circuit_id for c in circuit_seed.CIRCUITS}
    used = [row[1] for row in seed._CALENDAR_2026]
    assert set(used) <= seeded
    assert len(used) == len(set(used))  # no double-header in 2026


def test_2026_seed_is_chronological():
    dates = [row[3] for row in seed._CALENDAR_2026]
    assert dates == sorted(dates)


def test_seed_has_sepang_at_round_16_with_jolpica_name():
    row = next(r for r in seed._CALENDAR_2026 if r[1] == "sepang")
    assert row[0] == 16 and row[2] == "Bahrain Grand Prix in Malaysia"
    assert row[3] == date(2026, 10, 4)
    # Singapore moved up behind it
    assert next(r for r in seed._CALENDAR_2026 if r[1] == "singapore")[0] == 17


def test_sepang_circuit_row():
    c = next(c for c in circuit_seed.CIRCUITS if c.circuit_id == "sepang")
    assert (c.jolpica_id, c.fastf1_location) == ("sepang", "Kuala Lumpur")
    assert (c.num_corners, c.num_laps, c.sm_zones) == (15, 56, 4)


def test_cross_source_keys_are_unique_across_circuits():
    for attr in ("circuit_id", "jolpica_id", "fastf1_location"):
        vals = [getattr(c, attr) for c in circuit_seed.CIRCUITS]
        assert len(vals) == len(set(vals)), attr


def test_sepang_has_a_pirelli_nomination():
    # C2/C3/C4 = hard/medium/soft -> (soft, medium, hard)
    assert compounds_for(2026, "Kuala Lumpur") == ("C4", "C3", "C2")
