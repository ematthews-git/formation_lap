"""High-level flows that compose individual jobs.

These are what the scheduler (AWS EventBridge / GitHub Actions / docker compose worker) calls.
Each flow opens a single connection_scope, finds the right target weekend by consulting
RaceWeekend, and dispatches the relevant per-cadence jobs in order.

Round-number note: ``race_weekends.round_number`` is the official F1 round (FastF1's
``RoundNumber``) — the simulator addresses a race by it, so ``weekends refresh`` /
``weekends seed`` keep it in step with the real calendar, renumbering in place when a race is
added mid-season (see ``calendar_sync``). The post-race flow still resolves the official
round from Jolpica by circuit rather than trusting ours, so results/standings/lap-record
jobs stay correct even if the two were ever to drift.
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
from formation_data.sources.fastf1_client import F1TVAuthError

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


def run_prelim_sim(
    today: date | None = None,
    season: int | None = None,
    round_number: int | None = None,
    source: str = "disk",
) -> None:
    """Called on the Monday of race week. Generates the prelim (pre-quali, season-form)
    strategy sim for that week's race, then superseded by the postquali sim once quali
    runs.

    No-ops when no race falls inside ``PRELIM_WINDOW`` (7 days), so it only fires on race
    weeks. Idempotent — a re-run just refreshes the prelim projection.

    Pass ``season`` and ``round_number`` together to force the prelim sim for a specific
    weekend, skipping the window gate (manual escape hatch, e.g. via workflow_dispatch).
    """
    if (season is None) != (round_number is None):
        raise ValueError("season and round_number must be provided together")

    today = today or date.today()
    with connection_scope() as conn:
        if season is not None and round_number is not None:
            rw = repositories.get_race_weekend(conn, season, round_number)
            if rw is None:
                logger.warning(
                    "run_prelim_sim: no race weekend for %s R%s; skipping",
                    season,
                    round_number,
                )
                return
        else:
            rw = repositories.next_race_weekend_within(conn, today, PRELIM_WINDOW)
            if rw is None:
                logger.info(
                    "run_prelim_sim: no race within %s days; skipping",
                    PRELIM_WINDOW.days,
                )
                return
        logger.info(
            "run_prelim_sim: prelim sim for %s R%s (race %s)",
            rw.season,
            rw.round_number,
            rw.race_date,
        )
        sim_strategies.run(
            conn, season=rw.season, round_number=rw.round_number, mode="prelim", source=source
        )


def run_prelim_sim_for_remaining_calendar(
    season: int, today: date | None = None, source: str = "disk"
) -> None:
    """Manual bulk backfill: prelim sim for every round still to come in `season`.

    Unlike `run_prelim_sim` (gated to the current race week's 7-day window), this walks
    the whole remaining calendar in one pass — e.g. to seed every future weekend's
    projection right after the season is loaded, or to refresh them all after a model
    change. Triggered by hand via workflow_dispatch, not on a recurring cron: each round
    re-fits season form from scratch, so sweeping the full calendar is real FastF1 +
    compute cost, not something to pay on every scheduled tick.
    """
    today = today or date.today()
    with connection_scope() as conn:
        remaining = repositories.remaining_race_weekends(conn, season, today)
        if not remaining:
            logger.info(
                "run_prelim_sim_for_remaining_calendar season=%s today=%s: no remaining rounds",
                season,
                today,
            )
            return
        for rw in remaining:
            logger.info(
                "run_prelim_sim_for_remaining_calendar: prelim sim for %s R%s (race %s)",
                rw.season,
                rw.round_number,
                rw.race_date,
            )
            sim_strategies.run(
                conn,
                season=rw.season,
                round_number=rw.round_number,
                mode="prelim",
                source=source,
            )


def run_post_race_for_last_weekend(today: date | None = None) -> None:
    """Called on a cron. No-ops if every past race already has results loaded.

    Processes *all* past weekends lacking results, not just the most recent — a missed
    cron run (GitHub Actions schedules are best-effort, and auto-disable after 60 days of
    repo inactivity) plus back-to-back race weekends would otherwise leave a permanent
    hole. Idempotent upserts make catch-up free.

    Two stages, so a FastF1 problem never holds back results:

    1. Jolpica: finishing order + driver/constructor standings, one transaction per
       weekend. The official F1 round is resolved from Jolpica (by circuit) because our
       seed round can't address the external APIs directly; that lookup also gates on
       results being published, so an as-yet-unscored weekend is retried next run.
    2. FastF1: lap record, stored laps frame and race trace (+ overtakes) for every race
       of the latest season that has results but is still missing FastF1 data. Keyed
       on what's missing, not on this run's weekends, so a race FastF1 couldn't serve
       last time (unpublished, rate-limited, signed out) is picked up again.

    Raises F1TVAuthError (after stage 1 has committed) if FastF1 can't sign in.
    """
    today = today or date.today()
    with connection_scope() as conn:
        pending = repositories.race_weekends_missing_results(conn, before=today)
        latest = repositories.most_recent_race_weekend_before(conn, today)

    if not pending:
        logger.info(
            "run_post_race_for_last_weekend today=%s: all past races have results", today
        )
    for rw in pending:
        # Own transaction per weekend: a failure further on can't roll back weekends
        # already loaded. Oldest-first, so cumulative standings stay in order.
        with connection_scope() as conn:
            _load_results_and_standings(conn, rw)

    if latest is not None:
        _refresh_fastf1_data(latest.season)


def _load_results_and_standings(conn, rw) -> None:
    """Stage 1 of the post-race flow for one weekend (see run_post_race_for_last_weekend)."""
    circuit = repositories.get_circuit(conn, rw.circuit_id)
    if circuit is None:
        logger.warning(
            "run_post_race: weekend %s R%s references unknown circuit %s; skipping",
            rw.season,
            rw.round_number,
            rw.circuit_id,
        )
        return

    try:
        race = jolpica_client.get_circuit_race(rw.season, circuit.jolpica_id)
    except httpx.HTTPError as exc:
        logger.warning(
            "run_post_race: Jolpica round lookup failed for %s %s (%s); skipping",
            circuit.circuit_id,
            rw.season,
            exc,
        )
        return
    if race is None or not race.get("Results"):
        logger.info(
            "run_post_race: no published results yet for %s %s; will retry",
            circuit.circuit_id,
            rw.season,
        )
        return

    official_round = int(race["round"])
    race_results.run(conn, season=rw.season, round_number=official_round)
    standings.run(conn, season=rw.season, round_number=official_round)


def _refresh_fastf1_data(season: int) -> None:
    """Stage 2 of the post-race flow: FastF1-derived data for `season`'s raced rounds."""
    from formation_sim.data import collector

    with connection_scope() as conn:
        todo = repositories.races_missing_fastf1_data(conn, season)
    if not todo:
        logger.info("run_post_race: FastF1 data is complete for %s", season)
        return
    logger.info(
        "run_post_race: fetching FastF1 data for %s %s",
        season,
        ", ".join(f"R{rnd}" for _, rnd, _ in todo),
    )

    for i, (s, rnd, circuit_id) in enumerate(todo):
        try:
            _refresh_fastf1_race(s, rnd, circuit_id)
        except F1TVAuthError:
            logger.error(
                "run_post_race: stopped, FastF1 can't sign in to F1TV. Results and "
                "standings are saved; FastF1 data for %s %s is still missing and will be "
                "fetched on the next run after signing in.",
                s,
                ", ".join(f"R{r}" for _, r, _ in todo[i:]),
            )
            raise
        if collector.rate_limited():
            logger.warning(
                "run_post_race: FastF1 hourly rate limit reached at %s R%s; progress is "
                "cached, and the next run picks up the rest.",
                s,
                rnd,
            )
            return


def _refresh_fastf1_race(season: int, rnd: int, circuit_id: str) -> None:
    """Lap record, laps frame and race trace for one race, each in its own transaction.

    Every step is best-effort and idempotent, and anything missing is retried next run,
    except F1TVAuthError, which stops the run because every later race would fail too.
    """
    from formation_data import artifact_store
    from formation_data.jobs.pre_season import race_traces

    steps = (
        (
            "lap record",
            lambda conn: post_race_lap_records.run(
                conn, circuit_id=circuit_id, season=season, round_number=rnd
            ),
        ),
        # Keeps the sim's current-season laps in derived_artifacts, so prelim/postquali
        # runs that read laps from the DB can see just-completed races.
        ("laps", lambda conn: artifact_store.dump_race_laps(conn, season, rnd)),
        # Also writes the classified overtake blob: both come off one telemetry load.
        (
            "race trace + overtakes",
            lambda conn: race_traces.run_single(
                conn, circuit_id=circuit_id, season=season, round_number=rnd
            ),
        ),
    )
    for label, step in steps:
        try:
            with connection_scope() as conn:
                stored = step(conn)
        except F1TVAuthError:
            raise
        except Exception:
            logger.exception(
                "run_post_race: %s failed for %s R%s (non-fatal; retried next run)",
                label,
                season,
                rnd,
            )
            continue
        if stored is True:
            logger.info("run_post_race: stored %s for %s R%s", label, season, rnd)
        elif stored is False:
            logger.warning(
                "run_post_race: no FastF1 data for the %s of %s R%s yet; retried next run",
                label,
                season,
                rnd,
            )


def run_postquali_sim(now: datetime | None = None, source: str = "disk") -> None:
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
                conn,
                season=rw.season,
                round_number=rw.round_number,
                mode="postquali",
                source=source,
            )


def run_post_session(now: datetime | None = None, source: str = "disk") -> None:
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
                conn,
                season=rw.season,
                round_number=rw.round_number,
                mode="postquali",
                source=source,
            )


__all__ = [
    "run_pre_season",
    "run_weather_refresh",
    "run_prelim_sim",
    "run_prelim_sim_for_remaining_calendar",
    "run_post_race_for_last_weekend",
    "run_postquali_sim",
    "run_post_session",
]
