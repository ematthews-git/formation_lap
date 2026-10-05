"""Tests for the renumber-safe calendar reconcile (formation_data.calendar_sync).

`plan_calendar` is pure, so most of this runs without a database. The Sepang scenario below
is the real 2026 case: a race inserted at round 16 shifts every later round up by one.
"""

from __future__ import annotations

from datetime import date

import pytest

from formation_data.calendar_sync import (
    CalendarConflict,
    describe_plan,
    plan_calendar,
)
from formation_data.domain import RaceWeekend

_TAIL = ["singapore", "austin", "mexico_city", "sao_paulo", "las_vegas", "lusail", "abu_dhabi"]


def _wk(round_number: int, circuit_id: str, *, id: int | None = None, name: str | None = None,
        day: int = 1, season: int = 2026) -> RaceWeekend:
    return RaceWeekend(
        id=id,
        circuit_id=circuit_id,
        season=season,
        round_number=round_number,
        event_name=name or f"{circuit_id} GP",
        race_date=date(season, 10, day),
        is_sprint=False,
        soft_compound="C5",
        medium_compound="C4",
        hard_compound="C3",
    )


def _stored() -> list[RaceWeekend]:
    """The prod calendar before Sepang: baku R15, then the tail at R16..R22 (id = 100 + round)."""
    rows = [_wk(15, "baku", id=115)]
    rows += [_wk(16 + i, c, id=116 + i) for i, c in enumerate(_TAIL)]
    return rows


def _desired_with_sepang() -> list[RaceWeekend]:
    rows = [_wk(15, "baku")]
    rows.append(_wk(16, "sepang", name="Bahrain Grand Prix in Malaysia"))
    rows += [_wk(17 + i, c) for i, c in enumerate(_TAIL)]
    return rows


def test_mid_season_insert_renumbers_later_rounds_and_keeps_ids():
    plan = plan_calendar(_stored(), _desired_with_sepang())

    assert [w.circuit_id for w in plan.inserts] == ["sepang"]
    assert plan.inserts[0].round_number == 16
    assert plan.inserts[0].id is None  # a brand-new row

    # every circuit that was R16..R22 is now R17..R23 — and keeps its row id, which is what
    # keeps its sessions / strategies / sims attached to the right circuit
    moved = {c.old.circuit_id: (c.old.id, c.old.round_number, c.new.id, c.new.round_number)
             for c in plan.renumbered}
    assert moved["singapore"] == (116, 16, 116, 17)
    assert moved["abu_dhabi"] == (122, 22, 122, 23)
    assert len(moved) == len(_TAIL)
    assert "baku" not in moved  # round 15 is untouched
    assert plan.unchanged == 1 and not plan.orphans


def test_new_row_is_not_matched_to_the_row_it_displaces():
    # the failure mode this module exists to prevent: Sepang must NOT be paired with the
    # existing round-16 row (Singapore)
    plan = plan_calendar(_stored(), _desired_with_sepang())
    sepang = plan.inserts[0]
    singapore = next(c for c in plan.updates if c.new.circuit_id == "singapore")
    assert singapore.new.id == 116 and sepang.id is None


def test_already_applied_plan_is_a_noop():
    applied = [w.model_copy(update={"id": 200 + i}) for i, w in enumerate(_desired_with_sepang())]
    plan = plan_calendar(applied, _desired_with_sepang())
    assert plan.is_noop
    assert plan.unchanged == len(applied)


def test_field_only_change_is_an_update_without_renumber():
    desired = _stored()
    desired = [w.model_copy(update={"id": None, "event_name": "Renamed GP"}) if w.circuit_id == "baku"
               else w.model_copy(update={"id": None}) for w in desired]
    plan = plan_calendar(_stored(), desired)
    assert [c.new.circuit_id for c in plan.updates] == ["baku"]
    assert not plan.renumbered and not plan.inserts


def test_double_header_pairs_visits_in_round_order():
    stored = [_wk(1, "spielberg", id=1, day=5), _wk(2, "spielberg", id=2, day=12)]
    desired = [_wk(2, "spielberg", day=5), _wk(3, "spielberg", day=12)]  # both shift +1
    plan = plan_calendar(stored, desired)
    by_id = {c.old.id: c.new.round_number for c in plan.updates}
    assert by_id == {1: 2, 2: 3}


def test_removed_race_is_an_orphan_and_never_touched():
    stored = [_wk(1, "melbourne", id=1), _wk(2, "shanghai", id=2)]
    desired = [_wk(1, "melbourne")]
    plan = plan_calendar(stored, desired)
    assert [o.circuit_id for o in plan.orphans] == ["shanghai"]
    assert not plan.updates and not plan.inserts


def test_orphan_blocking_a_target_round_is_refused():
    # shanghai dropped off the schedule but still holds R2, which melbourne now wants
    stored = [_wk(1, "melbourne", id=1), _wk(2, "shanghai", id=2)]
    desired = [_wk(2, "melbourne")]
    with pytest.raises(CalendarConflict, match="shanghai"):
        plan_calendar(stored, desired)


def test_duplicate_desired_rounds_are_refused():
    with pytest.raises(CalendarConflict, match="repeats"):
        plan_calendar([], [_wk(1, "melbourne"), _wk(1, "shanghai")])


def test_mixed_seasons_are_rejected():
    with pytest.raises(ValueError):
        plan_calendar([_wk(1, "melbourne", season=2025)], [_wk(1, "melbourne", season=2026)])


def test_describe_plan_summarises_the_change():
    lines = describe_plan(plan_calendar(_stored(), _desired_with_sepang()))
    assert any(line.startswith("+ R16") and "sepang" in line for line in lines)
    assert any("singapore" in line and "round 16 -> 17" in line for line in lines)
    assert lines[-1] == "1 to insert, 7 to update (7 renumbered), 1 unchanged"
