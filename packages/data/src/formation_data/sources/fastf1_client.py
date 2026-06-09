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
    logger.info("FastF1 cache enabled at %s", cache_dir)


def get_event_schedule(season: int):
    """Return the FIA event schedule for `season` as a DataFrame-ish object."""
    logger.info("get_event_schedule season=%s", season)
    return fastf1.get_event_schedule(season)


def get_race_session(season: int, round_number: int):
    """Return a FastF1 race session, loaded with laps + results + messages."""

    session = fastf1.get_session(season, round_number, "R")
    session.load(laps=True, telemetry=False, weather=False, messages=True)

    logger.info("get_race_session season=%s round=%s", season, round_number)
    return session
