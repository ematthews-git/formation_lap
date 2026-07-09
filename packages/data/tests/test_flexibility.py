"""Unit tests for the pure strategy-flexibility math in formation_data.flexibility.

No database — the ranking that lives in the repository layer is exercised elsewhere;
here we pin the effective-count / score / rank primitives it composes.
"""

from __future__ import annotations

import math

import pytest

from formation_data import flexibility


# --- effective_count ---


def test_effective_count_single_option_is_one():
    assert flexibility.effective_count([1.0]) == pytest.approx(1.0)
    # a lone positive weight among zeros still resolves to one option
    assert flexibility.effective_count([0.0, 3.0, 0.0]) == pytest.approx(1.0)


def test_effective_count_even_split_equals_option_count():
    assert flexibility.effective_count([0.5, 0.5]) == pytest.approx(2.0)
    assert flexibility.effective_count([1, 1, 1, 1]) == pytest.approx(4.0)


def test_effective_count_is_scale_invariant():
    assert flexibility.effective_count([2.0, 2.0]) == pytest.approx(
        flexibility.effective_count([0.1, 0.1])
    )


def test_effective_count_skewed_between_one_and_n():
    eff = flexibility.effective_count([0.9, 0.1])
    assert 1.0 < eff < 2.0


def test_effective_count_ignores_none_and_nonpositive():
    assert flexibility.effective_count([None, 0.5, -1.0, 0.5]) == pytest.approx(2.0)


def test_effective_count_no_mass_is_none():
    assert flexibility.effective_count([]) is None
    assert flexibility.effective_count([0.0, None, -2.0]) is None


# --- flexibility_score ---


def test_flexibility_score_geometric_mean_of_effective_counts():
    # stops: even 2-way (eff 2); sequences: even 4-way (eff 4) -> sqrt(8)
    score = flexibility.flexibility_score({"1": 0.5, "2": 0.5}, [1, 1, 1, 1])
    assert score == pytest.approx(math.sqrt(8.0))


def test_flexibility_score_rigid_track_near_one():
    # a single stop count and one dominant sequence -> barely above 1
    score = flexibility.flexibility_score({"1": 1.0}, [0.95, 0.05])
    assert score is not None
    assert score < 1.2


def test_flexibility_score_flexible_beats_rigid():
    rigid = flexibility.flexibility_score({"1": 0.9, "2": 0.1}, [0.9, 0.1])
    flexible = flexibility.flexibility_score(
        {"1": 0.5, "2": 0.5}, [0.4, 0.3, 0.3]
    )
    assert flexible > rigid


def test_flexibility_score_missing_ingredient_is_none():
    assert flexibility.flexibility_score(None, [0.5, 0.5]) is None
    assert flexibility.flexibility_score({}, [0.5, 0.5]) is None
    assert flexibility.flexibility_score({"1": 0.5, "2": 0.5}, []) is None


# --- rank_of ---


def test_rank_of_highest_score_is_rank_one():
    out = flexibility.rank_of(9.0, [9.0, 4.0, 1.0])
    assert (out["rank"], out["of"]) == (1, 3)
    assert out["score"] == pytest.approx(9.0)


def test_rank_of_lowest_score_is_last():
    out = flexibility.rank_of(1.0, [9.0, 4.0, 1.0])
    assert (out["rank"], out["of"]) == (3, 3)


def test_rank_of_ties_share_better_rank():
    # two circuits tie above; the tied score takes the better (lower) rank
    out = flexibility.rank_of(4.0, [9.0, 4.0, 4.0, 1.0])
    assert (out["rank"], out["of"]) == (2, 4)


def test_rank_of_singleton_is_rank_one_of_one():
    out = flexibility.rank_of(3.5, [3.5])
    assert (out["rank"], out["of"]) == (1, 1)
