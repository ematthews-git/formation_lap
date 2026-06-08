"""FastF1 adapter — timing, lap data, telemetry.

Used by:
- jobs.pre_season.lap_records   (fastest historical laps per circuit)
- jobs.pre_season.circuit_stats (pit losses, SC/RF probabilities, undercut/overcut from prior seasons)
- jobs.post_race.lap_records    (update if a race produced a new fastest lap)

"""

from __future__ import annotations

import logging
import fastf1
import os

logger = logging.getLogger(__name__)


def enable_cache() -> None:
    """Configure FastF1's on-disk cache. Call once at process start."""

    cache_dir = os.environ.get(
        "FASTF1_CACHE_DIR", os.path.expanduser("~/.cache/fastf1")
    )
    os.makedirs(cache_dir, exist_ok=True)

    fastf1.Cache.enable_cache(cache_dir)


def get_event_schedule(season: int):
    """Return the FIA event schedule for `season` as a DataFrame-ish object."""
    # TODO: return fastf1.get_event_schedule(season)
    logger.info("get_event_schedule season=%s (skeleton)", season)
    return None


def get_race_session(season: int, round_number: int):
    """Return a FastF1 race session, loaded with laps + results."""
    # TODO:
    #   session = fastf1.get_session(season, round_number, "R")
    #   session.load(laps=True, telemetry=False, weather=False, messages=False)
    #   return session
    logger.info("get_race_session season=%s round=%s (skeleton)", season, round_number)
    return None


def get_fastest_lap_for_circuit(circuit_id: str):
    """Return (driver, year, lap_time_seconds) for the all-time fastest race lap."""
    # TODO: iterate FastF1 sessions for the circuit; track min lap time.
    logger.info("get_fastest_lap_for_circuit %s (skeleton)", circuit_id)
    return None
