"""Unit tests for the pure helpers in jobs.pre_season.circuit_stats.

No database or FastF1 network access — sessions are faked with plain objects
carrying the attributes the helpers read (race_control_messages).

The pace/undercut helpers moved to their own modules; see test_pace_model.py,
test_pace_metrics.py and test_undercut.py.
"""

from __future__ import annotations

import pandas as pd
import pytest

from formation_data.jobs.pre_season import circuit_stats


class FakeSession:
    def __init__(self, race_control_messages=None, laps=None):
        self.race_control_messages = race_control_messages
        self.laps = laps


def _rc(rows: list[tuple[str, str]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["Message", "Status"])


# --- _safety_car_probability ---


def test_sc_counts_full_safety_car():
    session = FakeSession(_rc([("SAFETY CAR DEPLOYED", "DEPLOYED")]))
    assert circuit_stats._safety_car_probability([session]) == 100


def test_sc_excludes_virtual_safety_car():
    session = FakeSession(_rc([("VIRTUAL SAFETY CAR DEPLOYED", "DEPLOYED")]))
    assert circuit_stats._safety_car_probability([session]) == 0


def test_sc_requires_deployed_status():
    session = FakeSession(_rc([("SAFETY CAR IN THIS LAP", "ENDING")]))
    assert circuit_stats._safety_car_probability([session]) == 0


def test_sc_returns_int_percent():
    with_sc = FakeSession(_rc([("SAFETY CAR DEPLOYED", "DEPLOYED")]))
    without = FakeSession(_rc([("YELLOW FLAG", "")]))
    assert circuit_stats._safety_car_probability([with_sc, without]) == 50
    assert circuit_stats._safety_car_probability([with_sc, without, without]) == 33


def test_sc_rejects_empty_sessions():
    with pytest.raises(ValueError):
        circuit_stats._safety_car_probability([])


# --- _red_flag_probability ---


def test_red_flag_counted():
    session = FakeSession(_rc([("RED FLAG", "")]))
    assert circuit_stats._red_flag_probability([session]) == 100


def test_red_flag_matches_within_longer_message():
    session = FakeSession(_rc([("RED FLAG DEPLOYED FOR DEBRIS", "")]))
    assert circuit_stats._red_flag_probability([session]) == 100


def test_red_flag_absent():
    session = FakeSession(_rc([("CHEQUERED FLAG", "")]))
    assert circuit_stats._red_flag_probability([session]) == 0


def test_red_flag_rejects_empty_sessions():
    with pytest.raises(ValueError):
        circuit_stats._red_flag_probability([])


# --- _condition_of ---


def test_condition_of_buckets_by_severity():
    assert circuit_stats._condition_of("1", "1") == "normal"
    assert circuit_stats._condition_of("4", "1") == "sc"  # SC dominates
    assert circuit_stats._condition_of("1", "6") == "vsc"
    assert circuit_stats._condition_of("5", "1") is None  # red flag dropped
