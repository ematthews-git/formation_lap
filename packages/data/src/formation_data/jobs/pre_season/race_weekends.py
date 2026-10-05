"""Pre-season job — load (or re-sync) the season calendar.

Cadence: yearly once FIA + Pirelli confirm the calendar — and again, by hand, whenever the
calendar changes mid-season (a race added, replaced or rescheduled):

    formation-data weekends refresh --season 2026 --dry-run   # show what would change
    formation-data weekends refresh --season 2026

Source:
- sources.jolpica_client.get_schedule(season) owns the round number, circuit
  (Circuit.circuitId -> circuits.jolpica_id), event name (`raceName`) and sprint flag.
- sources.fastf1_client.get_event_schedule(season) supplies the race's *local* date.
  Jolpica's `date` is the UTC date, which for an evening race (Las Vegas starts 04:00Z the
  next day) is a day later than the weekend's local Sunday/Saturday. FastF1's EventDate is
  the local date, so it wins whenever it is within a day of Jolpica's. FastF1 is also
  cross-checked on the round number: the simulator and the sessions job address a weekend
  by FastF1's numbering, so a disagreement is logged loudly (not fatal).
- Pirelli compounds come from the shared nomination table (see
  ``calendar_sync.compounds_for_weekend``).

A round whose circuit isn't in the `circuits` table is skipped with a warning — add the
circuit to jobs/static/circuits.py (and run `circuits seed`) and refresh again.

The write goes through ``calendar_sync.reconcile_calendar``, which updates existing weekends
in place by circuit, so a mid-season insert renumbers the later rounds without orphaning
the sessions/strategies/sims attached to them. Run `sessions refresh` afterwards to load
timetables for any new weekend.

Upsert key: RaceWeekend UniqueConstraint(season, round_number) — double-header
seasons visit the same circuit twice, so (circuit_id, season) is not unique.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import Connection

from formation_data import calendar_sync, domain, repositories
from formation_data.sources import fastf1_client, jolpica_client

logger = logging.getLogger(__name__)


def run(
    conn: Connection, *, season: int, dry_run: bool = False
) -> calendar_sync.CalendarPlan:
    """Reconcile `season`'s race_weekends with the Jolpica schedule; return the plan.

    `dry_run=True` computes (and safety-checks) the plan without writing."""
    races = jolpica_client.get_schedule(season)
    if not races:
        logger.warning("pre_season.race_weekends.run season=%s: Jolpica returned no races", season)
        return calendar_sync.CalendarPlan(season=season)

    circuits_by_jolpica_id = {c.jolpica_id: c for c in repositories.list_circuits(conn)}
    fastf1_by_round = _fastf1_events_by_round(season)

    desired: list[domain.RaceWeekend] = []
    for race in races:
        round_number = int(race["round"])
        jolpica_circuit = race["Circuit"]["circuitId"]
        circuit = circuits_by_jolpica_id.get(jolpica_circuit)
        if circuit is None:
            logger.warning(
                "pre_season.race_weekends.run: skipping R%s %r — circuit %r is not seeded; "
                "add it to jobs/static/circuits.py, run `circuits seed`, then refresh again",
                round_number,
                race["raceName"],
                jolpica_circuit,
            )
            continue

        soft, medium, hard = calendar_sync.compounds_for_weekend(season, circuit)
        desired.append(
            domain.RaceWeekend(
                circuit_id=circuit.circuit_id,
                season=season,
                round_number=round_number,
                event_name=race["raceName"],
                race_date=_local_race_date(race, circuit, fastf1_by_round.get(round_number)),
                is_sprint="Sprint" in race,
                soft_compound=soft,
                medium_compound=medium,
                hard_compound=hard,
            )
        )

    plan = calendar_sync.reconcile_calendar(
        conn, season=season, desired=desired, dry_run=dry_run
    )
    logger.info(
        "pre_season.race_weekends.run season=%s dry_run=%s inserts=%d updates=%d unchanged=%d",
        season,
        dry_run,
        len(plan.inserts),
        len(plan.updates),
        plan.unchanged,
    )
    return plan


def _fastf1_events_by_round(season: int) -> dict[int, object]:
    """FastF1's (non-testing) events keyed by round number; {} if the schedule can't be
    fetched, in which case dates fall back to Jolpica's."""
    try:
        schedule = fastf1_client.get_event_schedule(season)
        schedule = schedule[schedule["EventFormat"] != "testing"]
        return {int(e.RoundNumber): e for _, e in schedule.iterrows()}
    except Exception:
        logger.warning(
            "pre_season.race_weekends.run: FastF1 schedule unavailable for %s; using "
            "Jolpica's UTC dates and skipping the round cross-check",
            season,
            exc_info=True,
        )
        return {}


def _local_race_date(race: dict, circuit: domain.Circuit, fastf1_event) -> date:
    """The weekend's local race date: FastF1's EventDate when it agrees with Jolpica's (same
    circuit, within a day), else Jolpica's own date."""
    jolpica_date = date.fromisoformat(race["date"])
    if fastf1_event is None:
        return jolpica_date

    if fastf1_event.Location not in fastf1_client.aliases_for(circuit.fastf1_location):
        logger.warning(
            "pre_season.race_weekends.run: Jolpica R%s is %s but FastF1 R%s is %r — the sim "
            "and sessions job use FastF1's numbering, so check FastF1 has caught up",
            race["round"],
            circuit.circuit_id,
            race["round"],
            fastf1_event.Location,
        )
        return jolpica_date

    local_date = fastf1_event.EventDate.date()
    if abs(local_date - jolpica_date) > timedelta(days=1):
        logger.warning(
            "pre_season.race_weekends.run: R%s dates disagree by more than a day "
            "(Jolpica %s, FastF1 %s); using Jolpica's",
            race["round"],
            jolpica_date,
            local_date,
        )
        return jolpica_date
    return local_date
