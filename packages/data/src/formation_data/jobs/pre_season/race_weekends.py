"""Pre-season job — load the season calendar.

Cadence: yearly, once FIA + Pirelli confirm calendar and per-race tire allocations.

Source:
- sources.jolpica_client.get_schedule(season) for round_number, race_date, circuit_id, is_sprint.
- sources.fastf1_client.get_event_schedule(season) for event_name (FastF1's EventName,
  the canonical season-specific event label). Reconciled to Jolpica by round_number:
  Jolpica owns circuit/date/sprint (via Circuit.circuitId -> jolpica_id), FastF1 owns
  the event label. Validate every Jolpica round resolves to a FastF1 EventName; log and
  skip on a miss rather than write a mislabelled row.
- Pirelli compound allocations come from Pirelli's per-event press release; until that has a
  programmatic source, the job will use a small lookup table in this module (sketched below).

Upsert key: RaceWeekend UniqueConstraint(season, round_number) — double-header
seasons visit the same circuit twice, so (circuit_id, season) is not unique.
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection

logger = logging.getLogger(__name__)


# TODO: replace with a real source. Pirelli publishes per-race allocations; FastF1 also exposes
# session.event["TyreCompound"] once a session has run. For pre-season we may need to scrape
# or hand-curate the season's allocations until the first session loads.
COMPOUND_DEFAULTS = ("C3", "C4", "C5")  # (hard, medium, soft)


def run(conn: Connection, *, season: int) -> None:
    # TODO:
    #   from formation_data import domain, repositories, schema
    #   from formation_data.sources import jolpica_client, fastf1_client
    #   races = jolpica_client.get_schedule(season)
    #   by_jolpica_id = {c.jolpica_id: c for c in repositories.list_circuits(conn)}
    #   sched = fastf1_client.get_event_schedule(season)
    #   sched = sched[sched["EventFormat"] != "testing"]
    #   event_name_by_round = {int(e.RoundNumber): e.EventName for _, e in sched.iterrows()}
    #   hard, medium, soft = COMPOUND_DEFAULTS  # or lookup per circuit
    #   items = [domain.RaceWeekend(
    #       circuit_id=by_jolpica_id[r["Circuit"]["circuitId"]].circuit_id,
    #       season=season,
    #       round_number=int(r["round"]),
    #       event_name=event_name_by_round[int(r["round"])],  # KeyError -> log + skip, don't mislabel
    #       race_date=date.fromisoformat(r["date"]),
    #       is_sprint="Sprint" in r,
    #       soft_compound=soft, medium_compound=medium, hard_compound=hard,
    #   ) for r in races]
    #   repositories.upsert(conn, schema.race_weekends, items, ["season", "round_number"])
    logger.info("pre_season.race_weekends.run season=%s (skeleton)", season)
