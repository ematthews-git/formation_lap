"""Pre-season job — refresh the all-time race lap record per circuit.

Cadence: yearly. Carries records forward; post_race.lap_records handles in-season updates.

Source: sources.fastf1_client.get_fastest_lap_for_circuit(circuit_id) — iterates FastF1
sessions for the circuit and tracks the minimum lap time. The race lap record (not qualifying)
is what we care about.

Upsert key: LapRecord.circuit_id is already unique (declared on the column in models.py).
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection

logger = logging.getLogger(__name__)


def run(conn: Connection) -> None:
    # TODO:
    #   from formation_data import domain, repositories, schema
    #   from formation_data.sources import fastf1_client
    #   items = []
    #   for circuit in repositories.list_circuits(conn):
    #       result = fastf1_client.get_fastest_lap_for_circuit(circuit.circuit_id)
    #       if result is None:
    #           continue
    #       driver, year, lap_time_seconds = result
    #       items.append(domain.LapRecord(
    #           circuit_id=circuit.circuit_id, driver=driver,
    #           year=year, lap_time_seconds=lap_time_seconds,
    #       ))
    #   repositories.upsert(conn, schema.lap_records, items, ["circuit_id"])
    logger.info("pre_season.lap_records.run (skeleton)")
