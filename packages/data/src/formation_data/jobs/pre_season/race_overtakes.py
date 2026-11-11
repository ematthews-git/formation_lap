"""Pre-season job — classified on-track overtakes, one blob per race.

Cadence mirrors ``race_traces``: a yearly backfill over the trailing ``HISTORY_SEASONS``
completed seasons, plus one incremental build per completed race through the post-race
flow. This is the single source of truth for overtake counts — ``race_traces`` and
``circuit_race_stats`` both read the events produced here rather than counting again, so
the three feeds cannot disagree.

The expensive part is loading a session with telemetry, so :func:`build_for_session` takes
an already-loaded session and callers that have one (the race-trace job, the circuit
race-stats job) pass it straight through instead of paying for a second load.

Rate-limit-graceful in the same way as the other pre-season jobs: ``collector.load_session``
returns None once FastF1's hourly budget is spent, so a run stops mid-calendar and resumes
for free later against the on-disk cache.
"""

from __future__ import annotations

import logging

import numpy as np
from sqlalchemy import Connection

from formation_data import overtakes, repositories

logger = logging.getLogger(__name__)

HISTORY_SEASONS = 5


def build_for_session(ses, laps=None, results=None, status_windows=None) -> dict | None:
    """Detect and classify every change of on-track order in a loaded race session.

    Returns the storable blob (see :func:`formation_data.overtakes.summarise`), or None
    when the session has no usable telemetry — callers then fall back to lap resolution.
    """
    from formation_sim.data import collector, track_position

    if laps is None:
        laps = collector.session_laps(ses)
    if not len(laps):
        return None
    if results is None:
        results = collector.session_results(ses)
    if status_windows is None:
        status_windows = collector.session_track_status(ses)

    frame = track_position.track_frame(ses)
    if frame is None:
        return None
    positions = track_position.driver_track_positions(ses, frame)
    if not positions:
        return None

    total_laps = int(np.nanmax(laps["lap_number"].to_numpy(dtype=float)))
    events = overtakes.detect_overtakes(
        positions,
        laps,
        official=track_position.official_positions(ses),
        results=results,
        status_windows=status_windows,
        corners=frame.corners,
        marshal_sectors=frame.marshal_sectors,
        track_length_m=frame.length_m,
    )
    return overtakes.summarise(events, total_laps)


def run_single(
    conn: Connection, *, circuit_id: str, season: int, round_number: int, ses=None
) -> dict | None:
    """Build + upsert one race's overtake blob; returns it so callers can reuse it.

    Pass ``ses`` when the caller already holds a loaded session (telemetry + messages).
    """
    from formation_sim.data import collector

    if ses is None:
        ses = collector.load_session(
            season, round_number, "R", weather=True, messages=True, telemetry=True
        )
    if ses is None:
        return None
    blob = build_for_session(ses)
    if blob is None:
        return None
    repositories.upsert_race_overtakes(conn, circuit_id, season, round_number, blob)
    return blob


def run(conn: Connection, *, season: int, circuit_id: str | None = None) -> None:
    """Backfill overtake blobs for the trailing `HISTORY_SEASONS` seasons before `season`.

    `circuit_id` limits the run to a single circuit; None does the whole calendar.
    """
    # Imported lazily: the sim collector pulls in FastF1 + the sim package, which the
    # other non-sim jobs sharing this process shouldn't pay for at import time.
    from formation_sim.data import collector

    from formation_data.sources import fastf1_client

    circuits = repositories.list_circuits(conn)
    if circuit_id is not None:
        circuits = [c for c in circuits if c.circuit_id == circuit_id]

    window = range(season - HISTORY_SEASONS, season)
    written = 0
    for circuit in circuits:
        for s in window:
            for r in fastf1_client.rounds_for_location(s, circuit.fastf1_location):
                try:
                    stored = run_single(
                        conn, circuit_id=circuit.circuit_id, season=s, round_number=r
                    )
                except fastf1_client.F1AccessError:
                    raise  # a setup problem: every later race would fail the same way
                except Exception:  # noqa: BLE001 — one unavailable/partial race must not
                    # sink the whole backfill; skip it and carry on.
                    logger.warning(
                        "pre_season.race_overtakes: skipping %s R%s (load/parse failed)",
                        s, r, exc_info=True,
                    )
                    continue
                if stored is not None:
                    written += 1
                elif collector.rate_limited():
                    logger.error(
                        "pre_season.race_overtakes: FastF1 rate limit hit at %s %s R%s; "
                        "%d races written, progress cached — re-run to resume.",
                        circuit.circuit_id, s, r, written,
                    )
                    return

    logger.info(
        "pre_season.race_overtakes.run season=%s races=%d history_seasons=%d",
        season, written, HISTORY_SEASONS,
    )
