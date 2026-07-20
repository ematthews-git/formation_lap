"""Pre-season job — lap-by-lap race traces for the RACE_TRACE panel.

Cadence: yearly backfill (manual for now), plus one incremental build per completed race
via the post-race flow (see ``orchestrator.run_post_race_for_last_weekend``, which calls
:func:`run_single`). For each circuit it builds EVERY race over the trailing
``HISTORY_SEASONS`` completed seasons and persists one ``race_traces`` blob per race,
keyed (season, official round) like race_results.

Reuses the sim's FastF1 collector for the raw frames (same on-disk cache as
circuit_race_stats, so a backfill run after that job costs no API budget).
Rate-limit-graceful: ``collector.load_session`` returns None once FastF1's hourly budget
is spent, so the run stops mid-calendar and resumes for free on a later re-run —
already-written traces are simply upserted again.
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection

from formation_data import race_trace, repositories

logger = logging.getLogger(__name__)

HISTORY_SEASONS = 5


def run_single(
    conn: Connection, *, circuit_id: str, season: int, round_number: int
) -> bool:
    """Build + upsert the trace for one race. False when the race has no usable data
    (or the FastF1 budget is spent — distinguishable via ``collector.rate_limited()``)."""
    from formation_sim.data import collector

    # telemetry=True so on-track overtakes come from the durable-lead-change counter
    # (race_trace.overtakes_by_lap) rather than the coarser lap-line fallback.
    ses = collector.load_session(season, round_number, "R", weather=True, telemetry=True)
    if ses is None:
        return False
    laps = collector.session_laps(ses)
    overtakes = race_trace.overtakes_by_lap(collector.driver_progress(ses), laps)
    blob = race_trace.build_trace(
        laps,
        collector.session_results(ses),
        collector.session_lap_rainfall(ses),
        season=season,
        round_number=round_number,
        event_name=str(ses.event["EventName"]),
        overtakes_by_lap=overtakes,
    )
    if blob is None:
        return False
    repositories.upsert_race_trace(conn, circuit_id, season, round_number, blob)
    return True


def run(conn: Connection, *, season: int, circuit_id: str | None = None) -> None:
    """Backfill traces for the trailing `HISTORY_SEASONS` seasons before `season`.

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
                except Exception:  # noqa: BLE001 — a single unavailable/partial race
                    # must not sink the whole backfill; skip it and carry on.
                    logger.warning(
                        "pre_season.race_traces: skipping %s R%s (load/parse failed)",
                        s, r, exc_info=True,
                    )
                    continue
                if stored:
                    written += 1
                elif collector.rate_limited():
                    logger.error(
                        "pre_season.race_traces: FastF1 rate limit hit at %s %s R%s; "
                        "%d traces written, progress cached — re-run to resume.",
                        circuit.circuit_id, s, r, written,
                    )
                    return

    logger.info(
        "pre_season.race_traces.run season=%s traces=%d history_seasons=%d",
        season,
        written,
        HISTORY_SEASONS,
    )
