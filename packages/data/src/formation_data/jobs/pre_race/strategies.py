"""Pre-race job — generate strategy options for an upcoming race.

Cadence: T-7, refreshed alongside weather.

Approach (v1, empirical): mine the strategies the field actually ran the last
time this circuit was raced, and surface the most-used ones. A "strategy" is the
ordered sequence of tyre compounds a driver used (e.g. ``MEDIUM->HARD``); two
drivers ran the *same* strategy if their compound sequences match. We rank
strategies by how many drivers used them and persist the top few, each with
per-stop pit windows derived from when those drivers actually pitted.

Safety / data-quality guards:
- **No race last year** (new or dropped venue): `rounds_for_location` returns
  `[]`. We look back up to ``LOOKBACK_SEASONS`` and use the most recent season
  that actually hosted a race here; if none did, we log and write nothing.
- **Wet races / unknown compounds**: only all-slick strategies are counted, so a
  wet or mixed race doesn't pollute the dry-strategy picture. A fully wet race
  yields no slick strategies and we write nothing.
- **DNFs / early crashes**: a driver must have completed at least
  ``MIN_RACE_FRACTION`` of the race distance for their strategy to count, so a
  lap-1 retirement doesn't register as a "0-stop" strategy.
- **Anomalous one-offs**: a strategy must have been used by at least
  ``MIN_DRIVERS`` drivers to be kept — unless that would discard everything, in
  which case we keep the single most-used strategy.
- **FastF1 rate limit**: re-raised; partial progress is on the on-disk cache so a
  re-run resumes for free (see `sources.fastf1_client`).

Upsert keys:
- Strategy           UniqueConstraint(race_weekend_id, label)
- StrategyStint      UniqueConstraint(strategy_id, stint_order)
"""

from __future__ import annotations

import logging

import numpy as np
from fastf1.exceptions import RateLimitExceededError
from sqlalchemy import Connection

from formation_data import domain, repositories
from formation_data.sources import fastf1_client

logger = logging.getLogger(__name__)

# How many prior seasons to search back through for a usable (dry) running of
# this circuit. We take the most recent season that yields clean slick
# strategies, stepping further back past wet races.
LOOKBACK_SEASONS = 3
# Keep at most this many distinct strategies (ranked by driver count).
MAX_STRATEGIES = 4
# A strategy needs this many drivers to be kept (anomaly filter).
MIN_DRIVERS = 2
# A driver must finish at least this fraction of the race for their strategy to count.
MIN_RACE_FRACTION = 0.5
# Pit window = middle band of observed in-laps for a stop, across drivers.
PIT_WINDOW_LO_PCT = 15
PIT_WINDOW_HI_PCT = 85

# Only dry-compound strategies are mined; anything else (INTERMEDIATE, WET,
# UNKNOWN, NaN) disqualifies a driver's strategy from the count.
SLICKS = {"SOFT", "MEDIUM", "HARD"}


def run(conn: Connection, *, season: int, round_number: int) -> None:
    """Generate and persist strategy options for (season, round_number)."""
    rw = repositories.get_race_weekend(conn, season, round_number)
    if rw is None:
        logger.warning(
            "pre_race.strategies.run: no race weekend %s R%s; nothing to do",
            season,
            round_number,
        )
        return

    circuit = repositories.get_circuit(conn, rw.circuit_id)
    if circuit is None:
        logger.warning(
            "pre_race.strategies.run: race weekend %s R%s references unknown "
            "circuit %s; nothing to do",
            season,
            round_number,
            rw.circuit_id,
        )
        return

    # Step back through prior seasons until one yields clean slick strategies,
    # skipping seasons the circuit wasn't raced (new/dropped venue) and wet
    # races (which produce no all-slick strategies).
    mined = _mine_most_recent_dry(season, circuit.fastf1_location)
    if mined is None:
        logger.warning(
            "pre_race.strategies.run: no dry historical strategies for %s in the "
            "%s seasons before %s (new/dropped venue, or every running was wet); "
            "nothing written",
            circuit.circuit_id,
            LOOKBACK_SEASONS,
            season,
        )
        return
    source_season, ranked = mined

    kept = [g for g in ranked if len(g["drivers"]) >= MIN_DRIVERS][:MAX_STRATEGIES]
    if not kept:  # very fragmented field — keep just the single most-used
        kept = ranked[:1]

    repositories.delete_strategies_for_weekend(conn, rw.id)
    for rank, group in enumerate(kept):
        strategy, stints = _build_strategy(rw.id, circuit.num_laps, group, is_base=rank == 0)
        repositories.upsert_strategy_with_stints(conn, strategy, stints)

    logger.info(
        "pre_race.strategies.run season=%s round=%s circuit=%s source_season=%s "
        "strategies=%d (base=%s)",
        season,
        round_number,
        circuit.circuit_id,
        source_season,
        len(kept),
        kept[0]["label"],
    )


# --- circuit history lookup ---


def _mine_most_recent_dry(
    season: int, fastf1_location: str
) -> tuple[int, list[dict]] | None:
    """Most recent prior season (within LOOKBACK_SEASONS) with mineable strategies.

    Steps back season by season, skipping any the circuit wasn't raced and any
    whose race(s) produced no clean all-slick strategies (e.g. a wet race).
    Returns (source_season, ranked_strategies) for the first usable season, or
    None if none in the window qualifies.
    """
    for back in range(1, LOOKBACK_SEASONS + 1):
        s = season - back
        rounds = fastf1_client.rounds_for_location(s, fastf1_location)
        if not rounds:
            continue
        sessions = _load_sessions(s, rounds)
        if not sessions:
            continue
        ranked = _rank_strategies(sessions)
        if ranked:
            return s, ranked
        logger.info(
            "pre_race.strategies: %s in %s had no clean slick strategies "
            "(likely wet); looking further back",
            fastf1_location,
            s,
        )
    return None


def _load_sessions(season: int, rounds: list[int]) -> list:
    """Load each prior race session, skipping any that fail to load.

    A FastF1 rate-limit error is re-raised (the caller's contract); anything else
    (a missing/corrupt session) is logged and skipped so one bad round doesn't
    sink the job.
    """
    sessions = []
    for r in rounds:
        try:
            sessions.append(fastf1_client.get_race_session(season, r))
        except RateLimitExceededError:
            logger.error(
                "pre_race.strategies: FastF1 rate limit hit loading %s R%s; "
                "progress is cached on disk, re-run to resume.",
                season,
                r,
            )
            raise
        except Exception as exc:  # noqa: BLE001 - one bad round shouldn't sink the job
            logger.warning(
                "pre_race.strategies: could not load %s R%s (%s); skipping",
                season,
                r,
                exc,
            )
    return sessions


# --- strategy mining ---


def _rank_strategies(sessions: list) -> list[dict]:
    """Rank all-slick strategies across the given sessions by driver count.

    Each returned dict: {label, compounds, drivers, stop_laps} where `stop_laps`
    is a list (one per pit stop) of the in-laps drivers actually pitted on.
    Sorted most-used first.
    """
    entries: list[dict] = []
    for session in sessions:
        entries.extend(_driver_strategies(session))

    groups: dict[str, dict] = {}
    for entry in entries:
        label = "->".join(entry["compounds"])
        group = groups.setdefault(
            label,
            {"label": label, "compounds": entry["compounds"], "drivers": [], "stop_laps": []},
        )
        group["drivers"].append(entry["driver"])
        for i, lap in enumerate(entry["stop_laps"]):
            if len(group["stop_laps"]) <= i:
                group["stop_laps"].append([])
            group["stop_laps"][i].append(lap)

    return sorted(groups.values(), key=lambda g: len(g["drivers"]), reverse=True)


def _driver_strategies(session) -> list[dict]:
    """One entry per driver who ran a clean, race-completing, all-slick strategy.

    Stints come from FastF1's per-driver Stint counter; the stop in-lap is the
    last lap of each stint except the final one (the lap the driver pitted on).
    """
    laps = session.laps
    if laps is None or laps.empty:
        return []

    total_laps = int(laps["LapNumber"].max())

    stints = (
        laps.groupby(["Driver", "Stint"])
        .agg(
            Compound=("Compound", "first"),
            StartLap=("LapNumber", "min"),
            EndLap=("LapNumber", "max"),
        )
        .reset_index()
    )

    out: list[dict] = []
    for driver, group in stints.groupby("Driver"):
        group = group.sort_values("Stint")
        compounds = group["Compound"].tolist()

        # All-slick only (drops wet/intermediate/unknown/NaN runs).
        if not all(isinstance(c, str) and c in SLICKS for c in compounds):
            continue

        # Drop early DNFs: require the driver to have completed most of the race.
        driver_last_lap = int(group["EndLap"].max())
        if driver_last_lap < MIN_RACE_FRACTION * total_laps:
            continue

        # The in-lap for each pit stop = the last lap of each stint but the last.
        stop_laps = [int(lap) for lap in group["EndLap"].tolist()[:-1]]
        out.append({"driver": driver, "compounds": compounds, "stop_laps": stop_laps})

    return out


# --- persistence shaping ---


def _build_strategy(
    race_weekend_id: int, race_laps: int, group: dict, *, is_base: bool
) -> tuple[domain.Strategy, list[domain.StrategyStint]]:
    """Turn a ranked strategy group into a Strategy + its StrategyStints."""
    compounds: list[str] = group["compounds"]
    num_stops = len(compounds) - 1

    strategy = domain.Strategy(
        race_weekend_id=race_weekend_id,
        is_base=is_base,
        num_stops=num_stops,
        label=group["label"],
    )

    stints: list[domain.StrategyStint] = []
    for order, compound in enumerate(compounds, start=1):
        if order <= num_stops:
            start, end = _pit_window(group["stop_laps"][order - 1], race_laps)
        else:
            # Final stint runs to the flag — no pit window, pin to race end.
            start = end = race_laps
        stints.append(
            domain.StrategyStint(
                strategy_id=0,  # replaced in upsert_strategy_with_stints
                stint_order=order,
                compound=compound,
                pit_lap_window_start=start,
                pit_lap_window_end=end,
            )
        )
    return strategy, stints


def _pit_window(stop_laps: list[int], race_laps: int) -> tuple[int, int]:
    """Middle-band pit window (inclusive lap range) for one stop.

    The window is the 15th–85th-percentile band of the in-laps drivers actually
    used for this stop, clamped to [1, race_laps]. A single observation collapses
    to a one-lap window.
    """
    lo = int(round(np.percentile(stop_laps, PIT_WINDOW_LO_PCT)))
    hi = int(round(np.percentile(stop_laps, PIT_WINDOW_HI_PCT)))
    lo = max(1, min(lo, race_laps))
    hi = max(lo, min(hi, race_laps))
    return lo, hi
