"""Pre-season job — refresh the all-time race lap record per circuit.

Cadence: yearly. Carries records forward; post_race.lap_records handles in-season updates.

Source: sources.fastf1_client.get_fastest_lap_for_circuit(circuit_id) — iterates FastF1
sessions for the circuit and tracks the minimum lap time. The race lap record (not qualifying)
is what we care about.

Upsert key: LapRecord.circuit_id is already unique (declared on the column in models.py).
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def run(session: Session) -> None:
    # TODO:
    #   for circuit in session.scalars(select(Circuit)):
    #       result = fastf1_client.get_fastest_lap_for_circuit(circuit.circuit_id)
    #       if result is None:
    #           continue
    #       driver, year, lap_time_seconds = result
    #       stmt = insert(LapRecord).values(
    #           circuit_id=circuit.circuit_id, driver=driver, year=year,
    #           lap_time_seconds=lap_time_seconds,
    #       ).on_conflict_do_update(
    #           index_elements=["circuit_id"],
    #           set_={"driver": driver, "year": year, "lap_time_seconds": lap_time_seconds},
    #       )
    #       session.execute(stmt)
    logger.info("pre_season.lap_records.run (skeleton)")
