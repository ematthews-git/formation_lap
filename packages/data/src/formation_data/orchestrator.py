"""High-level flows that compose individual jobs.

These are what the scheduler (AWS EventBridge / GitHub Actions / docker compose worker) calls.
Each flow opens a single connection_scope, finds the right target round by consulting RaceWeekend,
and dispatches the relevant per-cadence jobs in order.

In this skeleton pass the flows just log their intent and delegate to the no-op job stubs.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from formation_data import repositories
from formation_data.db import connection_scope
from formation_data.jobs.post_race import (
    lap_records as post_race_lap_records,
    race_results,
    standings,
)
from formation_data.jobs.pre_race import sim_strategies, strategies, weather
from formation_data.jobs.pre_season import (
    circuit_stats,
    drivers,
    lap_records as pre_season_lap_records,
    race_weekends,
    sessions,
)
from formation_data.jobs.static import circuits as static_circuits

logger = logging.getLogger(__name__)

PRE_RACE_WINDOW = timedelta(days=7)
# How far ahead the Monday post-race cron looks for the weekend to prelim-simulate.
# Wide enough to cover a normal inter-race gap; idempotent re-runs refine it each week.
PRELIM_WINDOW = timedelta(days=21)


def run_pre_season(season: int) -> None:
    """Once a year. Loads everything that should be ready before round 1.

    Order matters: race_weekends + drivers depend on Circuit being seeded;
    circuit_stats depends on prior post_race data already being in the DB.
    """
    logger.info("orchestrator.run_pre_season season=%s", season)
    with connection_scope() as conn:
        static_circuits.run(conn)            # cheap no-op if already seeded
        drivers.run(conn, season=season)
        race_weekends.run(conn, season=season)
        sessions.run(conn, season=season)    # needs race_weekends in place
        pre_season_lap_records.run(conn)
        circuit_stats.run(conn, season=season)


def run_pre_race_for_next_weekend(today: date | None = None) -> None:
    """Called on a cron. No-ops if no race is within the next 7 days."""
    today = today or date.today()
    # TODO:
    #   from formation_data import repositories
    #   with connection_scope() as conn:
    #       rw = repositories.next_race_weekend_within(conn, today, PRE_RACE_WINDOW)
    #       if rw is None:
    #           logger.info("no race within %s days; skipping", PRE_RACE_WINDOW.days)
    #           return
    #       weather.run(conn, season=rw.season, round_number=rw.round_number)
    #       strategies.run(conn, season=rw.season, round_number=rw.round_number)
    logger.info(
        "orchestrator.run_pre_race_for_next_weekend today=%s window=%s (skeleton)",
        today, PRE_RACE_WINDOW,
    )


def run_post_race_for_last_weekend(today: date | None = None) -> None:
    """Called on a cron. No-ops if every past race already has results loaded.

    Processes *all* past weekends lacking results, not just the most recent —
    a missed cron run (GitHub Actions schedules are best-effort, and auto-disable
    after 60 days of repo inactivity) plus back-to-back race weekends would
    otherwise leave a permanent hole. Idempotent upserts make catch-up free.

    Also generates the prelim sim for the next weekend: the previous race has just
    finished, so an early (pre-quali) projection should be published now.
    """
    today = today or date.today()
    # TODO:
    #   with connection_scope() as conn:
    #       for rw in repositories.race_weekends_missing_results(conn, before=today):
    #           race_results.run(conn, season=rw.season, round_number=rw.round_number)
    #           standings.run(conn, season=rw.season, round_number=rw.round_number)
    #           post_race_lap_records.run(conn, season=rw.season, round_number=rw.round_number)
    logger.info(
        "orchestrator.run_post_race_for_last_weekend today=%s (results: skeleton)", today
    )
    run_prelim_sim_for_next_weekend(today)


def run_prelim_sim_for_next_weekend(today: date | None = None) -> None:
    """Generate the prelim (pre-quali, season-form) sim for the next upcoming weekend.

    Runs at the end of a race weekend (the Monday post-race cron). No-ops when no race
    is on the calendar within ``PRELIM_WINDOW``. Idempotent — a re-run replaces the
    weekend's sim rows, and postquali later supersedes them.
    """
    today = today or date.today()
    with connection_scope() as conn:
        rw = repositories.next_race_weekend_within(conn, today, PRELIM_WINDOW)
        if rw is None:
            logger.info(
                "run_prelim_sim_for_next_weekend: no race within %s days; skipping",
                PRELIM_WINDOW.days,
            )
            return
        sim_strategies.run(
            conn, season=rw.season, round_number=rw.round_number, mode="prelim"
        )


def run_postquali_sim(now: datetime | None = None) -> None:
    """Generate postquali sims for weekends whose Qualifying finished ≥2h30 ago and
    that don't have one yet (and whose race hasn't started).

    Called on a frequent Sat/Sun cron. Idempotent catch-up: a weekend drops out of the
    due set once its postquali runs, so extra fires — or a run that spans several
    timezones' quali times — are free and safe.
    """
    now = now or datetime.now(timezone.utc)
    with connection_scope() as conn:
        due = repositories.weekends_postquali_due(conn, now)
        if not due:
            logger.info("run_postquali_sim now=%s: no weekends due", now)
            return
        for rw in due:
            sim_strategies.run(
                conn, season=rw.season, round_number=rw.round_number, mode="postquali"
            )


__all__ = [
    "run_pre_season",
    "run_pre_race_for_next_weekend",
    "run_post_race_for_last_weekend",
    "run_prelim_sim_for_next_weekend",
    "run_postquali_sim",
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
