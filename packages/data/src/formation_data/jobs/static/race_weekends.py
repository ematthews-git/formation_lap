"""Static job — seed the RaceWeekend table (season calendar) by hand.

Cadence: rare. Hand-written offline counterpart to pre_season/race_weekends.py
(`weekends refresh`), which reconciles against Jolpica + FastF1 and is the preferred way to
pick up calendar changes. Event names follow Jolpica's `raceName`, so the two stay in step
and don't flip-flop a row's name when both are run.

Data is hand written. VERIFY before relying on it:
  - race_date values are the local race dates (as in FastF1's EventDate), checked against
    Jolpica/FastF1 on 2026-10-05 — recheck after any calendar change.
  - is_sprint reflects the 2026 sprint venues (Shanghai, Miami, Montréal,
    Silverstone, Zandvoort, Singapore), cross-checked against FastF1's
    get_event_schedule(2026) EventFormat == "sprint_qualifying".
  - Compounds come from the simulator's shared Pirelli nomination table
    (``formation_data.nominations`` -> ``config/nominations.yaml``), keyed by the
    circuit's fastf1_location. Circuits with no nomination there (e.g. the new Madrid
    venue) fall back to calendar_sync.DEFAULT_COMPOUNDS.

Round numbers match FastF1's get_event_schedule(2026).RoundNumber, so the same round
identifies a weekend to both this table and the simulator's FastF1 lookups. Jeddah was
cancelled for 2026, and Bahrain's race moved to Sepang (Malaysia) as the "Bahrain Grand
Prix in Malaysia" — added mid-season as round 16, which shifted every later round up by one.
That makes a contiguous 23-round calendar, exactly the rounds FastF1 lists.

The write goes through ``calendar_sync.reconcile_calendar``, which pairs existing rows to this
list by circuit and renumbers them in place — re-running the seed after a round shift is safe
(a plain upsert on (season, round_number) would re-point a row's sessions/strategies at the
wrong circuit).

Upsert key: RaceWeekend UniqueConstraint(season, round_number).
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import Connection

from formation_data import calendar_sync
from formation_data.domain import RaceWeekend

logger = logging.getLogger(__name__)

# (round_number, circuit_id, event_name, race_date, is_sprint)
# event_name = Jolpica's raceName; race_date = local race date.
_CALENDAR_2026 = [
    (1, "melbourne", "Australian Grand Prix", date(2026, 3, 8), False),
    (2, "shanghai", "Chinese Grand Prix", date(2026, 3, 15), True),
    (3, "suzuka", "Japanese Grand Prix", date(2026, 3, 29), False),
    (4, "miami", "Miami Grand Prix", date(2026, 5, 3), True),
    (5, "montreal", "Canadian Grand Prix", date(2026, 5, 24), True),
    (6, "monaco", "Monaco Grand Prix", date(2026, 6, 7), False),
    (7, "barcelona", "Barcelona Grand Prix", date(2026, 6, 14), False),
    (8, "red_bull_ring", "Austrian Grand Prix", date(2026, 6, 28), False),
    (9, "silverstone", "British Grand Prix", date(2026, 7, 5), True),
    (10, "spa", "Belgian Grand Prix", date(2026, 7, 19), False),
    (11, "hungaroring", "Hungarian Grand Prix", date(2026, 7, 26), False),
    (12, "zandvoort", "Dutch Grand Prix", date(2026, 8, 23), True),
    (13, "monza", "Italian Grand Prix", date(2026, 9, 6), False),
    (14, "madrid", "Spanish Grand Prix", date(2026, 9, 13), False),
    (15, "baku", "Azerbaijan Grand Prix", date(2026, 9, 26), False),
    (16, "sepang", "Bahrain Grand Prix in Malaysia", date(2026, 10, 4), False),
    (17, "singapore", "Singapore Grand Prix", date(2026, 10, 11), True),
    (18, "austin", "United States Grand Prix", date(2026, 10, 25), False),
    (19, "mexico_city", "Mexico City Grand Prix", date(2026, 11, 1), False),
    (20, "sao_paulo", "Brazilian Grand Prix", date(2026, 11, 8), False),
    (21, "las_vegas", "Las Vegas Grand Prix", date(2026, 11, 21), False),
    (22, "lusail", "Qatar Grand Prix", date(2026, 11, 29), False),
    (23, "abu_dhabi", "Abu Dhabi Grand Prix", date(2026, 12, 6), False),
]

_CALENDAR_BY_SEASON = {2026: _CALENDAR_2026}


def run(
    conn: Connection, *, season: int, dry_run: bool = False
) -> calendar_sync.CalendarPlan | None:
    """Seed `season`'s calendar from the hand-curated list; returns the reconcile plan
    (None when there is no list for the season). `dry_run=True` writes nothing."""
    from formation_data import repositories

    calendar = _CALENDAR_BY_SEASON.get(season)
    if calendar is None:
        logger.warning(
            "static.race_weekends.run season=%s has no hand-curated calendar (have: %s)",
            season,
            sorted(_CALENDAR_BY_SEASON),
        )
        return None

    # Guard the FK: skip (and warn on) any round pointing at an unseeded circuit
    # rather than letting the write blow up mid-batch.
    circuits = {c.circuit_id: c for c in repositories.list_circuits(conn)}
    items: list[RaceWeekend] = []
    for round_number, circuit_id, event_name, race_date, is_sprint in calendar:
        circuit = circuits.get(circuit_id)
        if circuit is None:
            logger.warning(
                "static.race_weekends.run skipping round=%s: circuit %r not seeded",
                round_number,
                circuit_id,
            )
            continue
        soft, medium, hard = calendar_sync.compounds_for_weekend(season, circuit)
        items.append(
            RaceWeekend(
                circuit_id=circuit_id,
                season=season,
                round_number=round_number,
                event_name=event_name,
                race_date=race_date,
                is_sprint=is_sprint,
                soft_compound=soft,
                medium_compound=medium,
                hard_compound=hard,
            )
        )

    plan = calendar_sync.reconcile_calendar(
        conn, season=season, desired=items, dry_run=dry_run
    )
    logger.info(
        "static.race_weekends.run season=%s dry_run=%s weekends=%d inserts=%d updates=%d",
        season,
        dry_run,
        len(items),
        len(plan.inserts),
        len(plan.updates),
    )
    return plan
