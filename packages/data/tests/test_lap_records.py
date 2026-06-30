"""Unit tests for the pure helpers in jobs.pre_season.lap_records."""

from __future__ import annotations

from formation_data.jobs.pre_season import lap_records as lr


def test_parse_lap_time_minutes_and_seconds():
    assert abs(lr._parse_lap_time("1:27.097") - 87.097) < 1e-9
    assert abs(lr._parse_lap_time("0:59.999") - 59.999) < 1e-9


def test_parse_lap_time_seconds_only():
    assert lr._parse_lap_time("27.5") == 27.5


def test_parse_lap_time_rejects_garbage():
    assert lr._parse_lap_time("n/a") is None
    assert lr._parse_lap_time("1:ab") is None


def test_fastest_picks_min_and_adds_seconds():
    rows = [
        {"season": 2018, "race": "British GP", "driver": "Hamilton", "best_time": "1:25.892"},
        {"season": 2020, "race": "British GP", "driver": "Hamilton", "best_time": "1:24.303"},
        {"season": 2019, "race": "British GP", "driver": "Bottas", "best_time": "1:25.093"},
    ]
    best = lr._fastest(rows)
    assert best is not None
    assert best["driver"] == "Hamilton"
    assert best["season"] == 2020
    assert abs(best["seconds"] - 84.303) < 1e-9


def test_fastest_skips_unparseable_and_handles_empty():
    assert lr._fastest([]) is None
    assert lr._fastest([{"season": 2000, "race": "x", "driver": "y", "best_time": "??"}]) is None
