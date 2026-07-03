"""Pre-season job — load each weekend's session schedule (names + start times).

Cadence: yearly, alongside the calendar refresh; sessions are fixed once the FIA
publishes the timetable.

Source: sources.fastf1_client.get_event_sessions(season, fastf1_location, race_date).
FastF1's event schedule carries Session1..5 names plus SessionNDateUtc start
times. We match the event by the circuit's fastf1_location (round numbers differ
from our seed, which skips unseeded circuits) and store each session's start as a
UTC instant.

Rows produced: up to 5 Session rows per weekend —
- Conventional: Practice 1, Practice 2, Practice 3, Qualifying, Race
- Sprint      : Practice 1, Sprint Qualifying, Sprint, Qualifying, Race

Safety: skips (and warns on) a weekend whose circuit is missing or whose event
FastF1 can't resolve, rather than failing the whole run.

Upsert key: Session UniqueConstraint(race_weekend_id, session_order).
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection

from formation_data import domain, repositories, schema
from formation_data.sources import fastf1_client

logger = logging.getLogger(__name__)


def run(conn: Connection, *, season: int) -> None:
    """Fetch and persist the session timetable for every weekend in `season`."""
    weekends = repositories.list_race_weekends(conn, season)
    if not weekends:
        logger.warning(
            "pre_season.sessions.run season=%s: no race weekends seeded; "
            "nothing to do",
            season,
        )
        return

    circuits_by_id = {c.circuit_id: c for c in repositories.list_circuits(conn)}

    total = 0
    for rw in weekends:
        circuit = circuits_by_id.get(rw.circuit_id)
        if circuit is None:
            logger.warning(
                "pre_season.sessions.run: weekend %s R%s references unknown "
                "circuit %r; skipping",
                season,
                rw.round_number,
                rw.circuit_id,
            )
            continue

        rows = fastf1_client.get_event_sessions(
            season, circuit.fastf1_location, rw.race_date
        )
        if not rows:
            logger.warning(
                "pre_season.sessions.run: no FastF1 sessions for %s (%s) %s; "
                "skipping",
                circuit.circuit_id,
                circuit.fastf1_location,
                rw.race_date,
            )
            continue

        items = [
            domain.Session(
                race_weekend_id=rw.id,
                session_order=order,
                name=name,
                start_time=start,
            )
            for order, name, start in rows
        ]
        repositories.upsert(
            conn, schema.sessions, items, ["race_weekend_id", "session_order"]
        )
        total += len(items)

    logger.info(
        "pre_season.sessions.run season=%s weekends=%d sessions=%d",
        season,
        len(weekends),
        total,
    )
