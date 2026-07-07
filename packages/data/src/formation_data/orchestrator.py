"""High-level flows that compose individual jobs.

These are what the scheduler (AWS EventBridge / GitHub Actions / docker compose worker) calls.
Each flow opens a single connection_scope, finds the right target weekend by consulting
RaceWeekend, and dispatches the relevant per-cadence jobs in order.

Round-number note: our seed calendar is compacted (unseeded circuits dropped), so
``race_weekends.round_number`` is *not* the official F1 round. Jobs that read our DB
(weather, the sim) take the seed round; jobs that fetch external data keyed on the real
round (results, standings, the lap-record check) are handed the official round the
post-race flow resolves from Jolpica.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

import httpx

from formation_data import repositories
from formation_data.db import connection_scope
from formation_data.jobs.post_race import (
    lap_records as post_race_lap_records,
    race_results,
    standings,
)
from formation_data.jobs.post_session import session_results
from formation_data.jobs.pre_race import sim_strategies, weather
from formation_data.jobs.pre_season import (
    circuit_stats,
    drivers,
    lap_records as pre_season_lap_records,
    race_weekends,
    sessions,
)
from formation_data.jobs.static import circuits as static_circuits
from formation_data.sources import jolpica_client

logger = logging.getLogger(__name__)

# Only fetch a weather forecast once the race is within this horizon — Open-Meteo's
# forecast is only meaningful ~10 days out, so we skip it while the weekend is further off.
# The daily weather cron leaves a further-off weekend's forecast blank until it enters this
# window, then refreshes it every day as the forecast firms up.
WEATHER_WINDOW = timedelta(days=10)
# The prelim sim runs on the Monday of race week. A 7-day look-ahead uniquely selects that
# week's race — the following weekend is ≥12 days out on a Monday, so it can't be caught.
PRELIM_WINDOW = timedelta(days=7)


def run_pre_season(season: int) -> None:
    """Once a year. Loads everything that should be ready before round 1.

    Order matters: race_weekends + drivers depend on Circuit being seeded;
    circuit_stats depends on prior post_race data already being in the DB.
    """
    logger.info("orchestrator.run_pre_season season=%s", season)
    with connection_scope() as conn:
        static_circuits.run(conn)  # cheap no-op if already seeded
        drivers.run(conn, season=season)
        race_weekends.run(conn, season=season)
        sessions.run(conn, season=season)  # needs race_weekends in place
        pre_season_lap_records.run(conn)
        circuit_stats.run(conn, season=season)


def run_weather_refresh(today: date | None = None) -> None:
    """Called daily. Refreshes the weather forecast for the next weekend inside
    ``WEATHER_WINDOW`` (10 days); no-ops otherwise, so a race >10 days out stays blank
    until it enters the window.

    Idempotent: the weather job upserts (bumping ``updated_at``) and self-guards
    Open-Meteo's horizon, so firing every day simply keeps the forecast current as the
    weekend approaches.
    """
    today = today or date.today()
    with connection_scope() as conn:
        rw = repositories.next_race_weekend_within(conn, today, WEATHER_WINDOW)
        if rw is None:
            logger.info(
                "run_weather_refresh: no race within %s days; leaving weather blank",
                WEATHER_WINDOW.days,
            )
            return
        logger.info(
            "run_weather_refresh: forecast for %s R%s (race %s)",
            rw.season,
            rw.round_number,
            rw.race_date,
        )
        weather.run(conn, season=rw.season, round_number=rw.round_number)


def run_prelim_sim(today: date | None = None) -> None:
    """Called on the Monday of race week. Generates the prelim (pre-quali, season-form)
    strategy sim for that week's race, then superseded by the postquali sim once quali
    runs.

    No-ops when no race falls inside ``PRELIM_WINDOW`` (7 days), so it only fires on race
    weeks. Idempotent — a re-run just refreshes the prelim projection.
    """
    today = today or date.today()
    with connection_scope() as conn:
        rw = repositories.next_race_weekend_within(conn, today, PRELIM_WINDOW)
        if rw is None:
            logger.info(
                "run_prelim_sim: no race within %s days; skipping", PRELIM_WINDOW.days
            )
            return
        logger.info(
            "run_prelim_sim: prelim sim for %s R%s (race %s)",
            rw.season,
            rw.round_number,
            rw.race_date,
        )
        sim_strategies.run(
            conn, season=rw.season, round_number=rw.round_number, mode="prelim"
        )


def run_post_race_for_last_weekend(today: date | None = None) -> None:
    """Called on a cron. No-ops if every past race already has results loaded.

    Processes *all* past weekends lacking results, not just the most recent — a missed
    cron run (GitHub Actions schedules are best-effort, and auto-disable after 60 days of
    repo inactivity) plus back-to-back race weekends would otherwise leave a permanent
    hole. Idempotent upserts make catch-up free.

    Per weekend it loads the finishing order, refreshes the driver + constructor
    standings, and checks whether the race set a new circuit lap record. The official F1
    round is resolved from Jolpica (by circuit) because our seed round is compacted and
    can't address the external APIs directly; that lookup also gates on results being
    published, so an as-yet-unscored weekend is simply retried on the next run.
    """
    today = today or date.today()
    with connection_scope() as conn:
        pending = repositories.race_weekends_missing_results(conn, before=today)
        if not pending:
            logger.info(
                "run_post_race_for_last_weekend today=%s: all past races have results",
                today,
            )
            return

        for rw in pending:
            circuit = repositories.get_circuit(conn, rw.circuit_id)
            if circuit is None:
                logger.warning(
                    "run_post_race: weekend %s R%s references unknown circuit %s; skipping",
                    rw.season,
                    rw.round_number,
                    rw.circuit_id,
                )
                continue

            try:
                race = jolpica_client.get_circuit_race(rw.season, circuit.jolpica_id)
            except httpx.HTTPError as exc:
                logger.warning(
                    "run_post_race: Jolpica round lookup failed for %s %s (%s); skipping",
                    circuit.circuit_id,
                    rw.season,
                    exc,
                )
                continue
            if race is None or not race.get("Results"):
                logger.info(
                    "run_post_race: no published results yet for %s %s; will retry",
                    circuit.circuit_id,
                    rw.season,
                )
                continue

            official_round = int(race["round"])
            race_results.run(conn, season=rw.season, round_number=official_round)
            standings.run(conn, season=rw.season, round_number=official_round)
            post_race_lap_records.run(
                conn,
                circuit_id=rw.circuit_id,
                season=rw.season,
                round_number=official_round,
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


def run_post_session(now: datetime | None = None) -> None:
    """Called on a frequent race-weekend poll. Two independently-gated steps:

    1. Save the classification for any session that ended ≥45 min ago and isn't stored yet
       (``session_results_due`` — covers practice, quali, sprint, race).
    2. Run the postquali sim for any weekend whose Qualifying finished ≥2h30 ago and has no
       postquali yet (``weekends_postquali_due``).

    Both are idempotent catch-up sets keyed on missing rows, so extra fires — or a run
    spanning several timezones' sessions — are free and safe. The two gates differ on
    purpose: results save shortly after a session, but the sim keeps its longer buffer for
    FastF1's delayed quali data (which the sim fetches itself).
    """
    now = now or datetime.now(timezone.utc)
    with connection_scope() as conn:
        due_sessions = repositories.session_results_due(conn, now)
        if not due_sessions:
            logger.info("run_post_session now=%s: no session results due", now)
        for s in due_sessions:
            session_results.run(conn, session_id=s.id)

        due_postquali = repositories.weekends_postquali_due(conn, now)
        if not due_postquali:
            logger.info("run_post_session now=%s: no postquali sims due", now)
        for rw in due_postquali:
            sim_strategies.run(
                conn, season=rw.season, round_number=rw.round_number, mode="postquali"
            )


__all__ = [
    "run_pre_season",
    "run_weather_refresh",
    "run_prelim_sim",
    "run_post_race_for_last_weekend",
    "run_postquali_sim",
    "run_post_session",
]
