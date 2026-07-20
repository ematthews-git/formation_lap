"""Pre-season job — empirical per-circuit race analytics from recent history.

Cadence: yearly (manual for now — not yet wired into an orchestrator flow). For each circuit it
mines EVERY race (wet included) over the trailing ``HISTORY_SEASONS`` completed seasons and
persists one ``circuit_race_stats`` blob keyed by the *upcoming* season. This is the observed-
history counterpart to the sim's dry-only, model-derived race-context numbers.

Reuses the sim's FastF1 collector for the raw per-race frames (it already parses track status,
tyres, results and weather, and shares the sim's on-disk cache so warm sessions cost no API
budget); all metric definitions live in ``formation_data.race_metrics``. Rate-limit-graceful:
``collector.load_session`` returns None once FastF1's hourly budget is spent, so the run stops
before writing a half-mined circuit and resumes for free on a later re-run.

Upsert key: CircuitRaceStats UniqueConstraint(circuit_id, season).
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection

from formation_data import race_metrics, race_trace, repositories

logger = logging.getLogger(__name__)

HISTORY_SEASONS = 5


def run(conn: Connection, *, season: int, circuit_id: str | None = None) -> None:
    """Recompute empirical race analytics for `season` (trailing `HISTORY_SEASONS` seasons).

    `circuit_id` limits the run to a single circuit; None does the whole calendar.
    """
    # Imported lazily: the sim collector pulls in FastF1 + the sim package, which the other
    # non-sim jobs sharing this process shouldn't pay for at import time.
    from formation_sim.data import collector

    from formation_data.sources import fastf1_client

    circuits = repositories.list_circuits(conn)
    if circuit_id is not None:
        circuits = [c for c in circuits if c.circuit_id == circuit_id]

    window = range(season - HISTORY_SEASONS, season)
    written = 0
    for circuit in circuits:
        features: list[dict] = []
        used_seasons: set[int] = set()
        interrupted = False

        for s in window:
            for r in fastf1_client.rounds_for_location(s, circuit.fastf1_location):
                try:
                    # telemetry=True so avg_overtakes_per_race uses the same durable
                    # on-track-pass counter as the race trace (consistent feeds).
                    ses = collector.load_session(s, r, "R", weather=True, telemetry=True)
                    if ses is None:
                        # None = missing data OR the hourly budget was just spent. Once the
                        # collector reports rate-limiting, treat the circuit as incomplete.
                        if collector.rate_limited():
                            interrupted = True
                            break
                        continue
                    laps = collector.session_laps(ses)
                    overtakes = race_trace.overtakes_by_lap(
                        collector.driver_progress(ses), laps
                    )
                    feat = race_metrics.race_features(
                        laps,
                        collector.session_results(ses),
                        collector.weather_summary(ses),
                        overtakes=sum(overtakes.values()),
                    )
                except Exception:  # noqa: BLE001 — a single unavailable/partial race must not
                    # sink the whole backfill; skip it and carry on.
                    logger.warning(
                        "pre_season.circuit_race_stats: skipping %s R%s (load/parse failed)",
                        s, r, exc_info=True,
                    )
                    continue
                if feat is not None:
                    features.append(feat)
                    used_seasons.add(s)
            if interrupted:
                break

        if interrupted:
            logger.error(
                "pre_season.circuit_race_stats: FastF1 rate limit hit at circuit=%s; "
                "%d circuits written, progress cached — re-run to resume.",
                circuit.circuit_id,
                written,
            )
            return

        if not features:
            continue  # new venue, or no races in the window

        blob = race_metrics.aggregate(features, seasons=sorted(used_seasons))
        repositories.upsert_circuit_race_stats(conn, circuit.circuit_id, season, blob)
        written += 1

    logger.info(
        "pre_season.circuit_race_stats.run season=%s circuits=%d history_seasons=%d",
        season,
        written,
        HISTORY_SEASONS,
    )
