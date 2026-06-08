"""Post-race job — update LapRecord if the just-finished race produced a new fastest lap.

Cadence: T+1, runs after race_results to make sure FastF1 has the session cached.

Source: sources.fastf1_client.get_race_session(season, round_number) → session.laps fastest.
Compare against the existing LapRecord for this circuit; update if faster.

Upsert key: LapRecord.circuit_id is already unique.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def run(session: Session, *, season: int, round_number: int) -> None:
    # TODO:
    #   rw = _get_race_weekend(session, season, round_number)
    #   ff1_session = fastf1_client.get_race_session(season, round_number)
    #   fastest = ff1_session.laps.pick_fastest()
    #   current = session.scalar(select(LapRecord).where(LapRecord.circuit_id == rw.circuit_id))
    #   new_seconds = fastest["LapTime"].total_seconds()
    #   if current is None or new_seconds < current.lap_time_seconds:
    #       stmt = insert(LapRecord).values(
    #           circuit_id=rw.circuit_id,
    #           driver=fastest["Driver"], year=season,
    #           lap_time_seconds=new_seconds,
    #       ).on_conflict_do_update(
    #           index_elements=["circuit_id"],
    #           set_={"driver": fastest["Driver"], "year": season, "lap_time_seconds": new_seconds},
    #       )
    #       session.execute(stmt)
    logger.info(
        "post_race.lap_records.run season=%s round=%s (skeleton)", season, round_number
    )
