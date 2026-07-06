"""Pre-season job — recompute CircuitStats for the upcoming season.

Cadence: yearly. Runs after the prior season has fully settled. Reads several closed seasons
of FastF1 data and produces one CircuitStats row per circuit, keyed by the *upcoming* season.

Upsert key: CircuitStats UniqueConstraint(circuit_id, season).
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection
from fastf1.exceptions import RateLimitExceededError

from formation_data import domain, repositories, schema
from formation_data.sources import fastf1_client

logger = logging.getLogger(__name__)

HISTORY_SEASONS = 4


def run(conn: Connection, *, season: int) -> None:
    """Populates circuit stats.

    Pit-loss and undercut/overcut strength are no longer computed here — the
    strategy simulator derives those per weekend (see ``formation_sim`` /
    ``jobs.pre_race.sim_strategies``). This job now only backfills the
    SC / red-flag probabilities from FastF1 race-control history.

    Args:
        conn (Connection): Database connection.
        season (int): This is the last season completed.
    """
    items = []
    try:
        for circuit in repositories.list_circuits(conn):
            sessions_race = [
                fastf1_client.get_race_session(s, r)
                for s in range(season - HISTORY_SEASONS, season)
                for r in fastf1_client.rounds_for_location(s, circuit.fastf1_location)
            ]
            if not sessions_race:
                continue  # suggests new venue

            items.append(
                domain.CircuitStats(
                    circuit_id=circuit.circuit_id,
                    season=season,
                    sc_probability=_safety_car_probability(sessions_race),
                    red_flag_probability=_red_flag_probability(sessions_race),
                )
            )
    except RateLimitExceededError:
        # Every session fetched so far is already on FastF1's on-disk cache, and
        # cache hits don't count against the limit — so re-running in ~1h resumes
        # for free. Loading a large history for the first time? Warm the cache in
        # smaller HISTORY_SEASONS chunks spaced an hour apart.
        logger.error(
            "pre_season.circuit_stats: FastF1 rate limit hit while loading %s "
            "seasons; progress is cached on disk, re-run to resume.",
            HISTORY_SEASONS,
        )
        raise

    repositories.upsert(conn, schema.circuit_stats, items, ["circuit_id", "season"])

    logger.info(
        "pre_season.circuit_stats.run season=%s circuits=%s history_seasons=%s",
        season,
        len(items),
        HISTORY_SEASONS,
    )


def _safety_car_probability(sessions) -> int:
    """Percentage (0-100) of sessions with at least one full SC deployment.

    VSC messages also contain "SAFETY CAR", so they are excluded explicitly.

    Args:
        sessions: non-empty list of loaded FastF1 race sessions.
    """
    if not sessions:
        raise ValueError("sessions must be non-empty")
    count = 0

    for session in sessions:
        rc = session.race_control_messages
        sc_messages = rc[
            rc["Message"].str.contains("SAFETY CAR", na=False)
            & ~rc["Message"].str.contains("VIRTUAL", na=False)
            & rc["Status"].str.contains("DEPLOYED", na=False)
        ]
        if len(sc_messages) != 0:
            count += 1

    return round(100 * count / len(sessions))


def _red_flag_probability(sessions) -> int:
    """Percentage (0-100) of sessions with at least one red flag.

    Args:
        sessions: non-empty list of loaded FastF1 race sessions.
    """
    if not sessions:
        raise ValueError("sessions must be non-empty")
    count = 0

    for session in sessions:
        rc = session.race_control_messages
        # \b guard: "CHEQUERED FLAG" ends every race and contains "RED FLAG"
        red = rc[rc["Message"].str.contains(r"\bRED FLAG", regex=True, na=False)]
        if len(red) != 0:
            count += 1

    return round(100 * count / len(sessions))
