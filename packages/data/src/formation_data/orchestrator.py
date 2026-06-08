"""High-level flows that compose individual jobs.

These are what the scheduler (AWS EventBridge / GitHub Actions / docker compose worker) calls.
Each flow opens a single session_scope, finds the right target round by consulting RaceWeekend,
and dispatches the relevant per-cadence jobs in order.

In this skeleton pass the flows just log their intent and delegate to the no-op job stubs.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from formation_data.db import session_scope
from formation_data.jobs.post_race import (
    lap_records as post_race_lap_records,
    race_results,
    standings,
)
from formation_data.jobs.pre_race import strategies, weather
from formation_data.jobs.pre_season import (
    circuit_stats,
    drivers,
    lap_records as pre_season_lap_records,
    race_weekends,
)
from formation_data.jobs.static import circuits as static_circuits

logger = logging.getLogger(__name__)

PRE_RACE_WINDOW = timedelta(days=7)


def run_pre_season(season: int) -> None:
    """Once a year. Loads everything that should be ready before round 1.

    Order matters: race_weekends + drivers depend on Circuit being seeded;
    circuit_stats depends on prior post_race data already being in the DB.
    """
    logger.info("orchestrator.run_pre_season season=%s", season)
    with session_scope() as session:
        static_circuits.run(session)            # cheap no-op if already seeded
        drivers.run(session, season=season)
        race_weekends.run(session, season=season)
        pre_season_lap_records.run(session)
        circuit_stats.run(session, season=season)


def run_pre_race_for_next_weekend(today: date | None = None) -> None:
    """Called on a cron. No-ops if no race is within the next 7 days."""
    today = today or date.today()
    # TODO:
    #   with session_scope() as session:
    #       rw = session.scalar(
    #           select(RaceWeekend)
    #           .where(RaceWeekend.race_date >= today)
    #           .where(RaceWeekend.race_date <= today + PRE_RACE_WINDOW)
    #           .order_by(RaceWeekend.race_date.asc())
    #       )
    #       if rw is None:
    #           logger.info("no race within %s days; skipping", PRE_RACE_WINDOW.days)
    #           return
    #       weather.run(session, season=rw.season, round_number=rw.round_number)
    #       strategies.run(session, season=rw.season, round_number=rw.round_number)
    logger.info(
        "orchestrator.run_pre_race_for_next_weekend today=%s window=%s (skeleton)",
        today, PRE_RACE_WINDOW,
    )


def run_post_race_for_last_weekend(today: date | None = None) -> None:
    """Called on a cron. No-ops if the most recent race already has results loaded.

    For now the "already loaded" check is left as a TODO — idempotent upserts mean
    re-running is safe, just slightly wasteful of upstream API calls.
    """
    today = today or date.today()
    # TODO:
    #   with session_scope() as session:
    #       rw = session.scalar(
    #           select(RaceWeekend)
    #           .where(RaceWeekend.race_date < today)
    #           .order_by(RaceWeekend.race_date.desc())
    #       )
    #       if rw is None:
    #           logger.info("no completed race found")
    #           return
    #       race_results.run(session, season=rw.season, round_number=rw.round_number)
    #       standings.run(session, season=rw.season, round_number=rw.round_number)
    #       post_race_lap_records.run(session, season=rw.season, round_number=rw.round_number)
    logger.info(
        "orchestrator.run_post_race_for_last_weekend today=%s (skeleton)", today
    )


__all__ = [
    "run_pre_season",
    "run_pre_race_for_next_weekend",
    "run_post_race_for_last_weekend",
]


# Silence unused-import warnings while bodies are still TODO — these are real
# imports the live versions will use; keeping them documents intent.
_ = (
    race_results,
    standings,
    post_race_lap_records,
    weather,
    strategies,
)
