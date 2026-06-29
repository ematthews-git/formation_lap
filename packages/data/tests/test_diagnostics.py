"""Unit tests for the undercut validation helpers — pure ranking math, no DB."""

from __future__ import annotations

import pytest

from formation_data.jobs.pre_season import diagnostics


def test_spearman_perfectly_aligned():
    computed = {"a": 1.0, "b": 2.0, "c": 3.0}
    reference = {"a": 10.0, "b": 20.0, "c": 30.0}
    assert diagnostics.spearman(computed, reference) == pytest.approx(1.0)


def test_spearman_perfectly_reversed():
    computed = {"a": 1.0, "b": 2.0, "c": 3.0}
    reference = {"a": 30.0, "b": 20.0, "c": 10.0}
    assert diagnostics.spearman(computed, reference) == pytest.approx(-1.0)


def test_spearman_handles_ties():
    computed = {"a": 1.0, "b": 1.0, "c": 3.0}
    reference = {"a": 5.0, "b": 5.0, "c": 9.0}
    assert diagnostics.spearman(computed, reference) == pytest.approx(1.0)


def test_spearman_none_when_too_few_shared():
    assert diagnostics.spearman({"a": 1.0}, {"a": 1.0}) is None


def _row(cid, undercut, deg, **kw):
    base = dict(
        circuit_id=cid, undercut_strength=undercut, overcut_strength=0.0,
        undercut_laptime_swing=undercut, tyre_deg_rate=deg, warmup_penalty=0.4,
        typical_stop_age=20.0, overtaking_difficulty=0.5, emp_swing=float("nan"),
        undercut_sample_size=0, swap_rate=None,
    )
    base.update(kw)
    return base


def test_format_table_includes_circuits_and_correlation():
    rows = [
        _row("monaco", 1.2, 0.05),
        _row("monza", 0.1, 0.03),
        _row("barcelona", 0.9, 0.07),
    ]
    table = diagnostics.format_table(rows)
    assert "monaco" in table and "monza" in table and "barcelona" in table
    assert "Spearman" in table
    # sorted by undercut_strength desc -> monaco appears before monza
    assert table.index("monaco") < table.index("monza")


def test_format_table_handles_missing_empirical_values():
    # swap_rate None and emp_swing NaN must render, not crash.
    table = diagnostics.format_table([_row("spa", 0.5, 0.10), _row("monza", 0.1, 0.03)])
    assert "spa" in table


def test_validation_report_flags_bad_degradation():
    ok = diagnostics.validation_report([_row("spa", 0.5, 0.10), _row("monza", 0.1, 0.03)])
    assert any("deg gate: all" in line for line in ok)
    bad = diagnostics.validation_report([_row("spa", 0.5, -0.01)])
    assert any("deg gate FAIL" in line and "spa" in line for line in bad)


def test_validation_report_flags_high_deg_overcut():
    # high deg but zero undercut (classed overcut) -> flagged
    rows = [_row("silverstone", 0.0, 0.09)]
    report = diagnostics.validation_report(rows)
    assert any("overcut gate FAIL" in line and "silverstone" in line for line in report)
