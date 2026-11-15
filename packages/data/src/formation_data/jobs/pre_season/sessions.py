"""Pre-season job — load each weekend's session schedule (names + start times).

Cadence: yearly, alongside the calendar refresh; sessions are fixed once the FIA
publishes the timetable.

Source: sources.fastf1_client.get_event_sessions(season, fastf1_location, race_date).
FastF1's event schedule carries Session1..5 names plus SessionNDateUtc start
times. We match the event by the circuit's fastf1_location rather than round number, so
this stays correct while a mid-season calendar change is still propagating, and store
each session's start as a UTC instant.

Rows produced: up to 5 Session rows per weekend, each with the `kind` code keys on —
- Conventional: Practice 1, Practice 2, Practice 3, Qualifying, Race
                (fp1, fp2, fp3, quali, race)
- Sprint      : Practice 1, Sprint Qualifying, Sprint, Qualifying, Race
                (fp1, sprint_quali, sprint, quali, race)

Safety: skips (and warns on) a weekend whose circuit is missing or whose event
FastF1 can't resolve, rather than failing the whole run. A session name with no kind
stops the run (UnknownSession): it means a new format, which needs a decision in code.

Upsert key: Session UniqueConstraint(race_weekend_id, kind). A weekend's sessions whose
kind is no longer on its timetable (a format change) are deleted with their results.
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection, delete

from formation_data import domain, repositories, schema
from formation_data.sources import fastf1_client

logger = logging.getLogger(__name__)

# FastF1 session name -> kind (schema.SESSION_KINDS).
_KIND_BY_NAME = {
    "Practice 1": "fp1",
    "Practice 2": "fp2",
    "Practice 3": "fp3",
    "Sprint Qualifying": "sprint_quali",
    "Sprint Shootout": "sprint_quali",  # 2023's name for it
    "Sprint": "sprint",
    "Qualifying": "quali",
    "Race": "race",
}


class UnknownSession(ValueError):
    """FastF1 named a session that has no kind."""


def session_kind(name: str, season: int) -> str:
    """What a session is, from FastF1's name for it that season."""
    if season == 2021 and name == "Sprint Qualifying":
        return "sprint"  # 2021's sprint race went by this name
    try:
        return _KIND_BY_NAME[name]
    except KeyError:
        raise UnknownSession(
            f"FastF1 calls a {season} session {name!r}, which has no kind. Add it to "
            "jobs.pre_season.sessions and, if it's a new kind, to schema.SESSION_KINDS "
            "with a migration."
        ) from None


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
                kind=session_kind(name, season),
                session_order=order,
                name=name,
                start_time=start,
            )
            for order, name, start in rows
        ]
        conn.execute(
            delete(schema.sessions).where(
                schema.sessions.c.race_weekend_id == rw.id,
                schema.sessions.c.kind.not_in([s.kind for s in items]),
            )
        )
        repositories.upsert(conn, schema.sessions, items, ["race_weekend_id", "kind"])
        total += len(items)

    logger.info(
        "pre_season.sessions.run season=%s weekends=%d sessions=%d",
        season,
        len(weekends),
        total,
    )
