"""Pre-season job — load the season calendar.

Cadence: yearly, once FIA + Pirelli confirm calendar and per-race tire allocations.

Source:
- sources.jolpica_client.get_schedule(season) for round_number, race_date, circuit_id, is_sprint.
- Pirelli compound allocations come from Pirelli's per-event press release; until that has a
  programmatic source, the job will use a small lookup table in this module (sketched below).

Upsert key: RaceWeekend UniqueConstraint(circuit_id, season).
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# TODO: replace with a real source. Pirelli publishes per-race allocations; FastF1 also exposes
# session.event["TyreCompound"] once a session has run. For pre-season we may need to scrape
# or hand-curate the season's allocations until the first session loads.
COMPOUND_DEFAULTS = ("C3", "C4", "C5")  # (hard, medium, soft)


def run(session: Session, *, season: int) -> None:
    # TODO:
    #   races = jolpica_client.get_schedule(season)
    #   for r in races:
    #       hard, medium, soft = COMPOUND_DEFAULTS  # or lookup per circuit
    #       stmt = insert(RaceWeekend).values(
    #           circuit_id=_jolpica_to_our_circuit_id(r["Circuit"]["circuitId"]),
    #           season=season,
    #           round_number=int(r["round"]),
    #           race_date=date.fromisoformat(r["date"]),
    #           is_sprint="Sprint" in r,
    #           soft_compound=soft, medium_compound=medium, hard_compound=hard,
    #       ).on_conflict_do_update(
    #           index_elements=["circuit_id", "season"],
    #           set_={"round_number": ..., "race_date": ..., ...},
    #       )
    #       session.execute(stmt)
    logger.info("pre_season.race_weekends.run season=%s (skeleton)", season)
