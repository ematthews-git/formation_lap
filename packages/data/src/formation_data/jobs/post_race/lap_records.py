"""Post-race job — update LapRecord if the just-finished race produced a new fastest lap.

Cadence: T+1, runs after race_results to make sure FastF1 has the session cached.

Source: sources.fastf1_client.get_race_session(season, round_number) → session.laps fastest.
Compare against the existing LapRecord for this circuit; update if faster.

Upsert key: LapRecord.circuit_id is already unique.
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection

logger = logging.getLogger(__name__)


def run(conn: Connection, *, season: int, round_number: int) -> None:
    # TODO:
    #   from formation_data import domain, repositories, schema
    #   from formation_data.sources import fastf1_client
    #   rw = repositories.get_race_weekend(conn, season, round_number)
    #   ff1_session = fastf1_client.get_race_session(season, round_number)
    #   fastest = ff1_session.laps.pick_fastest()
    #   new_seconds = fastest["LapTime"].total_seconds()
    #   current = repositories.get_lap_record_for_circuit(conn, rw.circuit_id)
    #   if current is None or new_seconds < current.lap_time_seconds:
    #       repositories.upsert(conn, schema.lap_records, [domain.LapRecord(
    #           circuit_id=rw.circuit_id, driver=fastest["Driver"],
    #           year=season, lap_time_seconds=new_seconds,
    #       )], ["circuit_id"])
    logger.info(
        "post_race.lap_records.run season=%s round=%s (skeleton)", season, round_number
    )
