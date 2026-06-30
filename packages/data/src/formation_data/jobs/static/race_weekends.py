"""Static job — seed the RaceWeekend table (season calendar) by hand.

Cadence: rare. v1 hand-written counterpart to pre_season/race_weekends.py, which
will reconcile Jolpica + FastF1 once those source clients are implemented.

Data is hand written. VERIFY before relying on it:
  - race_date values are best-known 2026 dates and need a final check against the
    official FIA calendar.
  - is_sprint is set from the 2025 sprint venues as a placeholder; confirm the
    2026 sprint rounds.
  - Compounds default to C3/C4/C5 (hard/medium/soft) for every round. Pirelli
    publishes a per-race allocation; fill _COMPOUNDS_BY_ROUND to override.

Coverage gap: the circuits seed has 22 tracks and is missing Bahrain (Sakhir) and
Jeddah, which are rounds 4 and 5 of the real 2026 calendar. Those rounds are
omitted here (a race_weekend FK-references an existing circuit_id), so round
numbers below skip 4 and 5 deliberately. Add those two circuits to
jobs/static/circuits.py, then add their rounds here, for a complete calendar.

Upsert key: RaceWeekend UniqueConstraint(season, round_number).
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import Connection

from formation_data.domain import RaceWeekend

logger = logging.getLogger(__name__)

# Default Pirelli allocation applied to every round unless overridden below.
# (soft, medium, hard) — softer compound = higher C number.
_DEFAULT_COMPOUNDS = ("C5", "C4", "C3")
_COMPOUNDS_BY_ROUND: dict[int, tuple[str, str, str]] = {
    # round_number: (soft, medium, hard)  — e.g. Monza/Las Vegas run harder allocations
}

# (round_number, circuit_id, event_name, race_date, is_sprint)
# Rounds 4 (Bahrain) and 5 (Jeddah) intentionally absent — circuits not seeded.
_CALENDAR_2026 = [
    (1, "melbourne", "Australian Grand Prix", date(2026, 3, 8), False),
    (2, "shanghai", "Chinese Grand Prix", date(2026, 3, 15), True),
    (3, "suzuka", "Japanese Grand Prix", date(2026, 3, 29), False),
    (6, "miami", "Miami Grand Prix", date(2026, 5, 3), True),
    (7, "montreal", "Canadian Grand Prix", date(2026, 5, 24), False),
    (8, "monaco", "Monaco Grand Prix", date(2026, 6, 7), False),
    (9, "barcelona", "Spanish Grand Prix", date(2026, 6, 14), False),
    (10, "red_bull_ring", "Austrian Grand Prix", date(2026, 6, 28), False),
    (11, "silverstone", "British Grand Prix", date(2026, 7, 5), False),
    (12, "spa", "Belgian Grand Prix", date(2026, 7, 19), True),
    (13, "hungaroring", "Hungarian Grand Prix", date(2026, 7, 26), False),
    (14, "zandvoort", "Dutch Grand Prix", date(2026, 8, 23), False),
    (15, "monza", "Italian Grand Prix", date(2026, 9, 6), False),
    (16, "madrid", "Spanish Grand Prix", date(2026, 9, 13), False),
    (17, "baku", "Azerbaijan Grand Prix", date(2026, 9, 27), False),
    (18, "singapore", "Singapore Grand Prix", date(2026, 10, 11), False),
    (19, "austin", "United States Grand Prix", date(2026, 10, 25), True),
    (20, "mexico_city", "Mexico City Grand Prix", date(2026, 11, 1), False),
    (21, "sao_paulo", "São Paulo Grand Prix", date(2026, 11, 8), True),
    (22, "las_vegas", "Las Vegas Grand Prix", date(2026, 11, 21), False),
    (23, "lusail", "Qatar Grand Prix", date(2026, 11, 29), True),
    (24, "abu_dhabi", "Abu Dhabi Grand Prix", date(2026, 12, 6), False),
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
    known = {c.circuit_id for c in repositories.list_circuits(conn)}
    items: list[RaceWeekend] = []
    for round_number, circuit_id, event_name, race_date, is_sprint in calendar:
        if circuit_id not in known:
            logger.warning(
                "static.race_weekends.run skipping round=%s: circuit %r not seeded",
                round_number,
                circuit_id,
            )
            continue
        soft, medium, hard = _COMPOUNDS_BY_ROUND.get(round_number, _DEFAULT_COMPOUNDS)
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
