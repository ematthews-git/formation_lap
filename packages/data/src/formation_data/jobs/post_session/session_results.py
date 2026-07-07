"""Post-session job — save one session's classification / timesheet.

Cadence: ~45 min after each session ends, driven by the run-post-session poll
(orchestrator.run_post_session → repositories.session_results_due).

Source: sources.fastf1_client.get_session_results(season, fastf1_location, race_date,
session_name). FastF1 is the only source with practice data; its timing can lag past the
45-minute mark, so an empty result is a no-op (logged) and the poll retries next fire.

Rows produced: one session_results row per session, holding the whole ordered per-driver
list as a JSONB blob (session classifications are too heterogeneous across FP / Q / Sprint
/ Race for a rigid column schema — same rationale as sim_race_stats).

Upsert key: session_results UniqueConstraint(session_id).
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection

from formation_data import repositories
from formation_data.sources import fastf1_client

logger = logging.getLogger(__name__)


def run(conn: Connection, *, session_id: int) -> None:
    """Fetch and persist the classification for `session_id`."""
    session = repositories.get_session(conn, session_id)
    if session is None:
        logger.warning(
            "post_session.session_results.run: no session id=%s; nothing to do",
            session_id,
        )
        return

    rw = repositories.get_race_weekend_by_id(conn, session.race_weekend_id)
    if rw is None:
        logger.warning(
            "post_session.session_results.run: session %s references unknown "
            "race weekend %s; nothing to do",
            session_id,
            session.race_weekend_id,
        )
        return

    circuit = repositories.get_circuit(conn, rw.circuit_id)
    if circuit is None:
        logger.warning(
            "post_session.session_results.run: weekend %s R%s references unknown "
            "circuit %s; nothing to do",
            rw.season,
            rw.round_number,
            rw.circuit_id,
        )
        return

    results = fastf1_client.get_session_results(
        rw.season, circuit.fastf1_location, rw.race_date, session.name
    )
    if not results:
        logger.info(
            "post_session.session_results.run: no results yet for %s R%s %r; "
            "will retry",
            rw.season,
            rw.round_number,
            session.name,
        )
        return

    repositories.upsert_session_results(conn, session_id, results)
    logger.info(
        "post_session.session_results.run season=%s round=%s session=%r drivers=%d",
        rw.season,
        rw.round_number,
        session.name,
        len(results),
    )
