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


# A circuit's schedule Location is the stable, collision-free way to find its
# rounds — Country isn't unique (USA hosts 3 events) and EventName is season-
# unstable ("Spanish Grand Prix" was Barcelona ≤2025, Madrid from 2026). Location
# never refers to two different tracks, but a few venues have been *renamed*
# across seasons, so each such venue maps to the full set of strings it has used.
# Canonical key = the current (2026) Location, matching the circuits seed.
_LOCATION_ALIASES = {
    "Miami Gardens": {"Miami Gardens", "Miami"},  # "Miami" 2022-24 -> "Miami Gardens" 2025+
    "Monte Carlo": {"Monte Carlo", "Monaco"},  # "Monaco" 2022-25; "Monte Carlo" 2021 & 2026
    "Yas Marina": {"Yas Marina", "Yas Island"},  # "Yas Island" -2025 -> "Yas Marina" 2026
}


def rounds_for_location(season: int, fastf1_location: str) -> list[int]:
    """Round numbers in `season` whose event is held at `fastf1_location`.

    Matches on the schedule's Location column (see `_LOCATION_ALIASES`). Returns:
    - `[]` when the venue did not host a race that season (new/dropped circuit),
    - one round normally,
    - several for a double-header (e.g. Spielberg ran the Austrian + Styrian GPs
      in 2020/2021 — both resolve to the same circuit).

    Pre-season testing events are excluded so round numbers line up with races.
    """
    aliases = _LOCATION_ALIASES.get(fastf1_location, {fastf1_location})
    schedule = get_event_schedule(season)
    schedule = schedule[schedule["EventFormat"] != "testing"]
    return [int(event.RoundNumber) for _, event in schedule.iterrows() if event.Location in aliases]


def get_race_session(season: int, round_number: int):
    """Return a FastF1 race session, loaded with laps + results + messages."""

    session = fastf1.get_session(season, round_number, "R")
    session.load(laps=True, telemetry=False, weather=False, messages=True)

    logger.info("get_race_session season=%s round=%s", season, round_number)
    return session
