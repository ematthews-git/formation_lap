"""Post-race job — update LapRecord if the just-finished race set a new fastest lap.

Cadence: T+1, after race_results so FastF1 has had time to publish the session.

Source: sources.fastf1_client.get_race_session(season, round_number) → the race's
fastest lap. Compared against the circuit's existing LapRecord and written only if
faster, so a slow (wet / safety-car-heavy) race never overwrites a genuine record.

The caller passes our ``circuit_id`` (the record's key) alongside the *official* F1
season + round — FastF1 is addressed by the real round, which our compacted seed round
can't provide. Driver is stored as the surname, matching the pre-season lap-record
convention so the two sources agree.

Upsert key: LapRecord.circuit_id is unique.
"""

from __future__ import annotations

import logging

import pandas as pd
from fastf1.exceptions import RateLimitExceededError
from sqlalchemy import Connection

from formation_data import domain, repositories, schema
from formation_data.sources import fastf1_client

logger = logging.getLogger(__name__)


def run(conn: Connection, *, circuit_id: str, season: int, round_number: int) -> None:
    """Update `circuit_id`'s lap record if `season` R`round_number` beat it."""
    try:
        session = fastf1_client.get_race_session(season, round_number)
    except RateLimitExceededError:
        # Unlike the historical miner we don't re-raise: results + standings for this
        # weekend are already written in the shared transaction, and the lap record is a
        # refinement — log and move on rather than roll the whole batch back.
        logger.error(
            "post_race.lap_records.run: FastF1 rate limit loading %s R%s; skipping "
            "lap-record check (retry once the bucket refills)",
            season,
            round_number,
        )
        return
    except Exception as exc:  # noqa: BLE001 - a bad session shouldn't sink the flow
        logger.warning(
            "post_race.lap_records.run: could not load %s R%s (%s); skipping",
            season,
            round_number,
            exc,
        )
        return

    fastest = session.laps.pick_fastest()
    if fastest is None or pd.isna(fastest["LapTime"]):
        logger.warning(
            "post_race.lap_records.run: no fastest lap for %s R%s; nothing to do",
            season,
            round_number,
        )
        return

    new_seconds = float(fastest["LapTime"].total_seconds())
    current = repositories.get_lap_record_for_circuit(conn, circuit_id)
    if current is not None and new_seconds >= current.lap_time_seconds:
        logger.info(
            "post_race.lap_records.run: %s race best %.3fs did not beat the record "
            "%.3fs (%s); unchanged",
            circuit_id,
            new_seconds,
            current.lap_time_seconds,
            current.year,
        )
        return

    driver = _driver_surname(session, fastest["Driver"])
    repositories.upsert(
        conn,
        schema.lap_records,
        [
            domain.LapRecord(
                circuit_id=circuit_id,
                driver=driver,
                year=season,
                lap_time_seconds=new_seconds,
            )
        ],
        ["circuit_id"],
    )
    logger.info(
        "post_race.lap_records.run: new record at %s — %.3fs %s (%s)",
        circuit_id,
        new_seconds,
        driver,
        season,
    )


def _driver_surname(session, abbreviation: str) -> str:
    """Resolve a FastF1 driver abbreviation to a surname (pre-season record convention).

    Falls back to the abbreviation if FastF1 has no driver entry for it.
    """
    try:
        return str(session.get_driver(abbreviation)["LastName"])
    except Exception:  # noqa: BLE001 - the abbreviation is a fine fallback label
        return str(abbreviation)
