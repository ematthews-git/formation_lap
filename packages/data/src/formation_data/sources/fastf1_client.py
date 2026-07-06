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
from datetime import date, datetime, timezone
from functools import lru_cache

import pandas as pd

logger = logging.getLogger(__name__)


def enable_cache() -> None:
    """Configure FastF1's on-disk cache. Call once at process start."""

    cache_dir = os.environ.get(
        "FASTF1_CACHE_DIR", os.path.expanduser("~/.cache/fastf1")
    )
    os.makedirs(cache_dir, exist_ok=True)

    fastf1.Cache.enable_cache(cache_dir)
    logger.info("FastF1 cache enabled at %s", cache_dir)


@lru_cache(maxsize=None)
def get_event_schedule(season: int):
    """Return the FIA event schedule for `season` as a DataFrame-ish object.

    Memoised per process. Callers must treat the result as read-only
    (filter into a copy, never mutate in place).
    """
    logger.info("get_event_schedule season=%s (fetch)", season)
    return fastf1.get_event_schedule(season)


# A circuit's schedule Location is the stable, collision-free way to find its
# rounds — Country isn't unique (USA hosts 3 events) and EventName is season-
# unstable ("Spanish Grand Prix" was Barcelona ≤2025, Madrid from 2026). Location
# never refers to two different tracks, but a few venues have been *renamed*
# across seasons, so each such venue maps to the full set of strings it has used.
# Canonical key = the current (2026) Location, matching the circuits seed.
_LOCATION_ALIASES = {
    "Miami Gardens": {
        "Miami Gardens",
        "Miami",
    },  # "Miami" 2022-24 -> "Miami Gardens" 2025+
    "Monte Carlo": {
        "Monte Carlo",
        "Monaco",
    },  # "Monaco" 2022-25; "Monte Carlo" 2021 & 2026
    "Yas Marina": {
        "Yas Marina",
        "Yas Island",
    },  # "Yas Island" -2025 -> "Yas Marina" 2026
}


def aliases_for(fastf1_location: str) -> set[str]:
    """Every FastF1 Location string a venue has used across seasons (see
    `_LOCATION_ALIASES`), including the canonical current name itself. A venue with no
    recorded rename maps to just its own name."""
    return _LOCATION_ALIASES.get(fastf1_location, {fastf1_location})


def rounds_for_location(season: int, fastf1_location: str) -> list[int]:
    """Round numbers in `season` whose event is held at `fastf1_location`.

    Matches on the schedule's Location column (see `_LOCATION_ALIASES`). Returns:
    - `[]` when the venue did not host a race that season (new/dropped circuit),
    - one round normally,
    - several for a double-header (e.g. Spielberg ran the Austrian + Styrian GPs
      in 2020/2021 — both resolve to the same circuit).

    Pre-season testing events are excluded so round numbers line up with races.
    """
    aliases = aliases_for(fastf1_location)
    schedule = get_event_schedule(season)
    schedule = schedule[schedule["EventFormat"] != "testing"]
    return [
        int(event.RoundNumber)
        for _, event in schedule.iterrows()
        if event.Location in aliases
    ]


def get_event_sessions(
    season: int, fastf1_location: str, race_date: date
) -> list[tuple[int, str, datetime]]:
    """Ordered sessions for the event at `fastf1_location` in `season`.

    Returns a list of (session_order, name, start_utc) — e.g.
    (1, "Practice 1", 2026-07-03 11:30+00:00) ... (5, "Race", ...). `start_utc`
    is a timezone-aware UTC datetime, taken from FastF1's SessionNDateUtc.

    The event is matched on Location (not round number — FastF1 numbers the full
    calendar while our seed skips unseeded circuits, so the two disagree). When a
    location hosts two rounds in a season (a double-header), `race_date`
    disambiguates against the event's Sunday. Returns `[]` if no event matches or
    the schedule carries no session data.
    """
    aliases = aliases_for(fastf1_location)
    schedule = get_event_schedule(season)
    schedule = schedule[schedule["EventFormat"] != "testing"]
    events = schedule[schedule["Location"].isin(aliases)]
    if len(events) > 1:
        events = events[events["EventDate"].dt.date == race_date]
    if events.empty:
        return []

    event = events.iloc[0]
    sessions: list[tuple[int, str, datetime]] = []
    for order in range(1, 6):
        name = event.get(f"Session{order}")
        start = event.get(f"Session{order}DateUtc")
        if name is None or pd.isna(name) or pd.isna(start):
            continue
        start_utc = start.to_pydatetime().replace(tzinfo=timezone.utc)
        sessions.append((order, str(name), start_utc))
    return sessions


def get_race_session(season: int, round_number: int):
    """Return a FastF1 race session, loaded with laps + results + messages."""

    session = fastf1.get_session(season, round_number, "R")
    session.load(laps=True, telemetry=False, weather=False, messages=True)

    logger.info("get_race_session season=%s round=%s", season, round_number)
    return session


def get_fastest_lap_track(season: int, round_number: int):
    """Position trace of the race's fastest lap, plus the circuit rotation.

    Returns (x, y, rotation_deg): the fastest lap's X/Y telemetry as numpy
    arrays (FastF1 position units), and the circuit's canonical rotation in
    degrees (from `get_circuit_info()`) so every generated map can be oriented
    consistently. Loads telemetry, which is heavier than a plain lap load.
    """
    session = fastf1.get_session(season, round_number, "R")
    session.load(laps=True, telemetry=True, weather=False, messages=False)

    telemetry = session.laps.pick_fastest().get_telemetry()
    rotation = float(session.get_circuit_info().rotation)

    logger.info("get_fastest_lap_track season=%s round=%s", season, round_number)
    return telemetry["X"].to_numpy(), telemetry["Y"].to_numpy(), rotation
