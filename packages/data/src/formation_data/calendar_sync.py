"""Reconcile a season's `race_weekends` rows against a desired calendar — renumber-safe.

Why this exists: `race_weekends` is keyed on (season, round_number), and the round number
is not just a label. The simulator and the FastF1 session lookups address a weekend by
FastF1's round number, and `sessions`, `strategies`, `weather_forecasts` and
`sim_race_stats` all hang off the weekend's surrogate `id`. When a race is added
mid-season (2026: "Bahrain Grand Prix in Malaysia" slotted in as round 16), every later
round shifts by one. A blind upsert on (season, round_number) would overwrite the old
round-16 row *in place* — keeping its `id`, so Singapore's sessions and strategies would
end up attached to Sepang.

So instead a weekend's identity here is its circuit (`circuit_id`, in calendar order when
a circuit appears twice in a season), and a changed round number is applied as an update
to the existing row. The row keeps its `id`, and everything attached to it follows.

Shared by both entry points that write the calendar:
- jobs.pre_season.race_weekends  (`weekends refresh` — Jolpica + FastF1)
- jobs.static.race_weekends      (`weekends seed`    — hand-curated list)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import Connection, exists, insert, select, update

from formation_data import repositories, schema
from formation_data.domain import Circuit, RaceWeekend
from formation_data.nominations import compounds_for

logger = logging.getLogger(__name__)

# Fallback allocation for circuits absent from the shared nomination table (a brand-new
# venue with no entry yet). (soft, medium, hard) — softer = higher C number.
DEFAULT_COMPOUNDS = ("C5", "C4", "C3")


class CalendarConflict(RuntimeError):
    """The desired calendar can't be applied safely without a manual decision."""


def compounds_for_weekend(season: int, circuit: Circuit) -> tuple[str, str, str]:
    """(soft, medium, hard) for a weekend: the Pirelli nomination for the circuit's
    `fastf1_location`, or `DEFAULT_COMPOUNDS` (with a warning) when none is on file."""
    compounds = compounds_for(season, circuit.fastf1_location)
    if compounds is None:
        logger.warning(
            "calendar: no Pirelli nomination for %r (%s) in %s; using default %s — add "
            "it to formation_sim/config/nominations.yaml",
            circuit.fastf1_location,
            circuit.circuit_id,
            season,
            DEFAULT_COMPOUNDS,
        )
        return DEFAULT_COMPOUNDS
    return compounds


@dataclass(frozen=True)
class WeekendChange:
    """An existing weekend and the values it should end up with (same `id`)."""

    old: RaceWeekend
    new: RaceWeekend

    @property
    def renumbered(self) -> bool:
        return self.old.round_number != self.new.round_number

    @property
    def modified(self) -> bool:
        return _fields(self.old) != _fields(self.new)


@dataclass
class CalendarPlan:
    season: int
    inserts: list[RaceWeekend] = field(default_factory=list)
    updates: list[WeekendChange] = field(default_factory=list)  # only rows that change
    orphans: list[RaceWeekend] = field(default_factory=list)  # in the DB, not in the schedule
    unchanged: int = 0

    @property
    def renumbered(self) -> list[WeekendChange]:
        return [c for c in self.updates if c.renumbered]

    @property
    def is_noop(self) -> bool:
        return not self.inserts and not self.updates


def _fields(rw: RaceWeekend) -> dict:
    return rw.model_dump(exclude={"id"})


def plan_calendar(existing: list[RaceWeekend], desired: list[RaceWeekend]) -> CalendarPlan:
    """Diff the stored weekends against the desired calendar. Pure — no I/O.

    Existing and desired weekends are paired by circuit (k-th visit with k-th visit, in
    round order, for the rare double-header). Unpaired desired weekends are inserts;
    unpaired existing weekends are "orphans" (a race that dropped off the schedule) and
    are never deleted or renumbered here.

    Raises `CalendarConflict` if two desired weekends claim the same round, or if a
    desired round is already held by an orphan — a cancelled race that still has a row
    needs a human decision, not a guess.
    """
    seasons = {rw.season for rw in existing} | {rw.season for rw in desired}
    if len(seasons) > 1:
        raise ValueError(f"plan_calendar handles one season at a time, got {sorted(seasons)}")
    season = next(iter(seasons), 0)

    rounds = [rw.round_number for rw in desired]
    dupes = sorted({r for r in rounds if rounds.count(r) > 1})
    if dupes:
        raise CalendarConflict(f"desired calendar repeats round(s) {dupes}")

    by_circuit: dict[str, list[RaceWeekend]] = defaultdict(list)
    for rw in sorted(existing, key=lambda w: w.round_number):
        by_circuit[rw.circuit_id].append(rw)

    plan = CalendarPlan(season=season)
    for want in sorted(desired, key=lambda w: w.round_number):
        queue = by_circuit.get(want.circuit_id)
        if not queue:
            plan.inserts.append(want)
            continue
        have = queue.pop(0)
        change = WeekendChange(old=have, new=want.model_copy(update={"id": have.id}))
        if change.modified:
            plan.updates.append(change)
        else:
            plan.unchanged += 1

    plan.orphans = sorted(
        (rw for queue in by_circuit.values() for rw in queue), key=lambda w: w.round_number
    )
    clash = [o for o in plan.orphans if o.round_number in set(rounds)]
    if clash:
        raise CalendarConflict(
            "weekend(s) in the DB are not on the schedule but occupy a round the schedule "
            "assigns elsewhere: "
            + ", ".join(f"R{o.round_number} {o.circuit_id}" for o in clash)
            + ". Resolve by hand (delete or renumber them), then re-run."
        )
    return plan


# Tables keyed on the *official* round number at write time, as (table, season col, round col).
# If a weekend's round changes while rows already exist under its old round, those rows would
# silently describe a different race afterwards — so reconcile refuses rather than guess.
_ROUND_KEYED = (
    ("race_results", "season", "round_number"),
    ("race_traces", "season", "round_number"),
    ("race_overtakes", "season", "round_number"),
    ("standings", "season", "after_round"),
    ("derived_artifacts", "year", "round_number"),
)


def _round_keyed_data(conn: Connection, season: int, round_number: int) -> list[str]:
    found = []
    for name, season_col, round_col in _ROUND_KEYED:
        table = schema.metadata.tables[name]
        hit = conn.execute(
            select(
                exists().where(
                    table.c[season_col] == season, table.c[round_col] == round_number
                )
            )
        ).scalar_one()
        if hit:
            found.append(name)
    return found


def reconcile_calendar(
    conn: Connection, *, season: int, desired: list[RaceWeekend], dry_run: bool = False
) -> CalendarPlan:
    """Bring `season`'s `race_weekends` in line with `desired`, preserving row ids.

    Existing rows are updated in place (so sessions, strategies, weather and sim stats stay
    attached to the right circuit), new circuits are inserted, nothing is deleted. A
    renumber is applied in two phases — first every moving row is parked on a unique
    negative round, then all rows are written to their final values — because Postgres
    checks the (season, round_number) unique key row by row, so shifting rounds up by one
    in a single pass would trip over its own neighbours.

    With `dry_run=True` the plan (and the safety check below) is computed but nothing is
    written. Returns the plan either way.

    Raises `CalendarConflict` — before writing anything — if a renumbered weekend already
    has round-keyed data (results, standings, traces, ...) stored under its old round.
    """
    existing = repositories.list_race_weekends(conn, season)
    plan = plan_calendar(existing, desired)

    for change in plan.renumbered:
        stale = _round_keyed_data(conn, season, change.old.round_number)
        if stale:
            raise CalendarConflict(
                f"{change.old.circuit_id} moves R{change.old.round_number} -> "
                f"R{change.new.round_number}, but {', '.join(stale)} already hold rows under "
                f"round {change.old.round_number}. Those would end up describing a different "
                "race; migrate them by hand first."
            )

    if dry_run or plan.is_noop:
        return plan

    rw = schema.race_weekends
    for change in plan.renumbered:
        conn.execute(update(rw).where(rw.c.id == change.old.id).values(round_number=-change.old.id))
    for change in plan.updates:
        conn.execute(update(rw).where(rw.c.id == change.old.id).values(**_fields(change.new)))
    if plan.inserts:
        conn.execute(insert(rw).values([_fields(w) for w in plan.inserts]))

    logger.info(
        "calendar season=%s: inserted=%d updated=%d (renumbered=%d) unchanged=%d orphans=%d",
        season,
        len(plan.inserts),
        len(plan.updates),
        len(plan.renumbered),
        plan.unchanged,
        len(plan.orphans),
    )
    return plan


def describe_plan(plan: CalendarPlan) -> list[str]:
    """Human-readable lines for the CLI (what changed / would change)."""
    lines: list[str] = []
    for w in plan.inserts:
        lines.append(
            f"+ R{w.round_number:<2} {w.circuit_id}  {w.event_name}  {w.race_date}  (new)"
        )
    for c in plan.updates:
        bits = []
        if c.renumbered:
            bits.append(f"round {c.old.round_number} -> {c.new.round_number}")
        for name in ("event_name", "race_date", "is_sprint", "soft_compound",
                     "medium_compound", "hard_compound", "circuit_id"):
            a, b = getattr(c.old, name), getattr(c.new, name)
            if a != b:
                bits.append(f"{name}: {a} -> {b}")
        lines.append(f"~ R{c.new.round_number:<2} {c.new.circuit_id}  " + "; ".join(bits))
    for o in plan.orphans:
        lines.append(f"! R{o.round_number:<2} {o.circuit_id}  in DB but not on the schedule (left as is)")
    lines.append(
        f"{len(plan.inserts)} to insert, {len(plan.updates)} to update "
        f"({len(plan.renumbered)} renumbered), {plan.unchanged} unchanged"
    )
    return lines
