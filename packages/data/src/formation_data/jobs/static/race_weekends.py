"""Static job — seed the RaceWeekend table (season calendar) by hand.

Cadence: rare. v1 hand-written counterpart to pre_season/race_weekends.py, which
will reconcile Jolpica + FastF1 once those source clients are implemented.

Data is hand written. VERIFY before relying on it:
  - race_date values are best-known 2026 dates and need a final check against the
    official FIA calendar.
  - is_sprint reflects the 2026 sprint venues (Shanghai, Miami, Montréal,
    Silverstone, Zandvoort, Singapore), cross-checked against FastF1's
    get_event_schedule(2026) EventFormat == "sprint_qualifying".
  - Compounds come from the simulator's shared Pirelli nomination table
    (``formation_data.nominations`` -> ``config/nominations.yaml``), keyed by the
    circuit's fastf1_location. Circuits with no nomination there (e.g. the new Madrid
    venue) fall back to _DEFAULT_COMPOUNDS.

Round numbers match FastF1's get_event_schedule(2026).RoundNumber, so the same round
identifies a weekend to both this table and the simulator's FastF1 lookups. Bahrain and
Jeddah were cancelled for 2026, so the calendar is a contiguous 22 rounds with no gap —
the seed's 22 circuits are exactly the 22 rounds FastF1 lists.

Upsert key: RaceWeekend UniqueConstraint(season, round_number).
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import Connection

from formation_data.domain import RaceWeekend
from formation_data.nominations import compounds_for

logger = logging.getLogger(__name__)

# Fallback allocation for circuits absent from the shared nomination table (e.g. the
# new Madrid venue with no history). (soft, medium, hard) — softer = higher C number.
_DEFAULT_COMPOUNDS = ("C5", "C4", "C3")

# (round_number, circuit_id, event_name, race_date, is_sprint)
# Rounds 4 (Bahrain) and 5 (Jeddah) intentionally absent — circuits not seeded.
_CALENDAR_2026 = [
    (1, "melbourne", "Australian Grand Prix", date(2026, 3, 8), False),
    (2, "shanghai", "Chinese Grand Prix", date(2026, 3, 15), True),
    (3, "suzuka", "Japanese Grand Prix", date(2026, 3, 29), False),
    (4, "miami", "Miami Grand Prix", date(2026, 5, 3), True),
    (5, "montreal", "Canadian Grand Prix", date(2026, 5, 24), True),
    (6, "monaco", "Monaco Grand Prix", date(2026, 6, 7), False),
    (7, "barcelona", "Spanish Grand Prix", date(2026, 6, 14), False),
    (8, "red_bull_ring", "Austrian Grand Prix", date(2026, 6, 28), False),
    (9, "silverstone", "British Grand Prix", date(2026, 7, 5), True),
    (10, "spa", "Belgian Grand Prix", date(2026, 7, 19), False),
    (11, "hungaroring", "Hungarian Grand Prix", date(2026, 7, 26), False),
    (12, "zandvoort", "Dutch Grand Prix", date(2026, 8, 23), True),
    (13, "monza", "Italian Grand Prix", date(2026, 9, 6), False),
    (14, "madrid", "Spanish Grand Prix", date(2026, 9, 13), False),
    (15, "baku", "Azerbaijan Grand Prix", date(2026, 9, 27), False),
    (16, "singapore", "Singapore Grand Prix", date(2026, 10, 11), True),
    (17, "austin", "United States Grand Prix", date(2026, 10, 25), False),
    (18, "mexico_city", "Mexico City Grand Prix", date(2026, 11, 1), False),
    (19, "sao_paulo", "São Paulo Grand Prix", date(2026, 11, 8), False),
    (20, "las_vegas", "Las Vegas Grand Prix", date(2026, 11, 21), False),
    (21, "lusail", "Qatar Grand Prix", date(2026, 11, 29), False),
    (22, "abu_dhabi", "Abu Dhabi Grand Prix", date(2026, 12, 6), False),
]

_CALENDAR_BY_SEASON = {2026: _CALENDAR_2026}


def run(conn: Connection, *, season: int) -> None:
    from formation_data import repositories, schema

    calendar = _CALENDAR_BY_SEASON.get(season)
    if calendar is None:
        logger.warning(
            "static.race_weekends.run season=%s has no hand-curated calendar (have: %s)",
            season,
            sorted(_CALENDAR_BY_SEASON),
        )
        return

    # Guard the FK: skip (and warn on) any round pointing at an unseeded circuit
    # rather than letting the upsert blow up mid-batch.
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
        compounds = compounds_for(season, circuit.fastf1_location)
        if compounds is None:
            logger.warning(
                "static.race_weekends.run round=%s (%s): no Pirelli nomination for %r; "
                "using default %s",
                round_number,
                circuit_id,
                circuit.fastf1_location,
                _DEFAULT_COMPOUNDS,
            )
            compounds = _DEFAULT_COMPOUNDS
        soft, medium, hard = compounds
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

    repositories.upsert(
        conn,
        table=schema.race_weekends,
        items=items,
        conflict_cols=["season", "round_number"],
    )
    logger.info("static.race_weekends.run season=%s weekends=%d", season, len(items))
