"""`formation-data` CLI — one subcommand per job plus orchestrator flows.

Real wiring (so `formation-data --help` enumerates everything). The handlers themselves
open a connection_scope and call into the skeleton jobs, which log placeholder messages
today and will fetch + upsert via the repository layer in a follow-up.
"""

from __future__ import annotations

import logging
import os
import sys

import httpx
import typer
from fastf1.exceptions import RateLimitExceededError
from formation_sim.data import f1tv
from sqlalchemy import exc as sa_exc
from sqlalchemy.engine import url as sa_url

from formation_data import calendar_sync, db, orchestrator, repositories
from formation_data.db import connection_scope
from formation_data.jobs.post_race import (
    lap_records as post_race_lap_records,
    race_results,
    standings,
)
from formation_data.jobs.post_session import session_results as post_session_results
from formation_data.jobs.pre_race import sim_strategies, strategies, weather
from formation_data.jobs.pre_season import (
    circuit_race_stats,
    circuit_stats,
    drivers,
    lap_records as pre_season_lap_records,
    race_overtakes,
    race_traces,
    race_weekends,
    sessions,
    track_maps,
)
from formation_data.jobs.static import (
    circuits as static_circuits,
    drivers as static_drivers,
    race_weekends as static_weekends,
)
from formation_data.sources import fastf1_client

app = typer.Typer(help="Formation Lap data loader.")
circuits_app = typer.Typer(help="Static circuit seed.")
drivers_app = typer.Typer(help="Driver lineup per season.")
weekends_app = typer.Typer(help="Season calendar.")
sessions_app = typer.Typer(help="Weekend session timetable.")
lap_records_app = typer.Typer(help="All-time race lap records.")
circuit_stats_app = typer.Typer(help="Per-circuit per-season stats.")
circuit_race_stats_app = typer.Typer(help="Empirical per-circuit race analytics.")
race_traces_app = typer.Typer(help="Lap-by-lap race traces (RACE_TRACE panel).")
race_overtakes_app = typer.Typer(help="Classified on-track overtakes, per race.")
weather_app = typer.Typer(help="Race weekend weather forecast.")
strategies_app = typer.Typer(help="Historical (mined) strategy options.")
sim_strategies_app = typer.Typer(help="Simulated strategy options.")
results_app = typer.Typer(help="Race finishing order.")
standings_app = typer.Typer(help="Driver + constructor standings.")
session_results_app = typer.Typer(help="Per-session classification / timesheet.")
derived_app = typer.Typer(help="Derived-artifact store (sim laps in the DB).")
db_app = typer.Typer(help="Database schema management.")
f1tv_app = typer.Typer(help="F1TV sign-in, which FastF1 needs to fetch F1 timing data.")

app.add_typer(circuits_app, name="circuits")
app.add_typer(drivers_app, name="drivers")
app.add_typer(weekends_app, name="weekends")
app.add_typer(sessions_app, name="sessions")
app.add_typer(lap_records_app, name="lap-records")
app.add_typer(circuit_stats_app, name="circuit-stats")
app.add_typer(circuit_race_stats_app, name="circuit-race-stats")
app.add_typer(race_traces_app, name="race-traces")
app.add_typer(race_overtakes_app, name="overtakes")
app.add_typer(weather_app, name="weather")
app.add_typer(strategies_app, name="strategies")
app.add_typer(sim_strategies_app, name="sim-strategies")
app.add_typer(results_app, name="results")
app.add_typer(standings_app, name="standings")
app.add_typer(session_results_app, name="session-results")
app.add_typer(derived_app, name="derived")
app.add_typer(db_app, name="db")
app.add_typer(f1tv_app, name="f1tv")

_verbose = False


@app.callback()
def _configure_logging(
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Debug logging, and full tracebacks on errors."
    ),
) -> None:
    global _verbose
    _verbose = verbose
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


# --- per-job subcommands ---


@circuits_app.command("seed")
def circuits_seed() -> None:
    with connection_scope() as conn:
        static_circuits.run(conn)


@circuits_app.command("trackmap")
def circuits_trackmap(
    season: int = typer.Option(2025, help="Most recent season to source telemetry from."),
    circuit: str | None = typer.Option(None, "--circuit", help="Single circuit_id; default all."),
) -> None:
    """Generate circuit-outline SVG paths from FastF1 telemetry."""
    with connection_scope() as conn:
        track_maps.run(conn, season=season, circuit_id=circuit)


@drivers_app.command("seed")
def drivers_seed(season: int = typer.Option(2026)) -> None:
    """Hand-curated grid (v1). Use `refresh` to pull from Jolpica instead."""
    with connection_scope() as conn:
        static_drivers.run(conn, season=season)


@drivers_app.command("refresh")
def drivers_refresh(season: int = typer.Option(...)) -> None:
    with connection_scope() as conn:
        drivers.run(conn, season=season)


_DRY_RUN_OPT = typer.Option(
    False, "--dry-run", help="Show what would change without writing anything."
)


def _echo_plan(plan: calendar_sync.CalendarPlan | None, *, dry_run: bool) -> None:
    if plan is None:
        return
    for line in calendar_sync.describe_plan(plan):
        typer.echo(line)
    if dry_run:
        typer.echo("(dry run — nothing written)")
    elif plan.inserts:
        typer.echo(
            f"New weekend(s) need their timetable: formation-data sessions refresh "
            f"--season {plan.season}"
        )


@weekends_app.command("seed")
def weekends_seed(
    season: int = typer.Option(2026), dry_run: bool = _DRY_RUN_OPT
) -> None:
    """Hand-curated calendar (offline fallback). Prefer `refresh`, which reads Jolpica."""
    with connection_scope() as conn:
        plan = static_weekends.run(conn, season=season, dry_run=dry_run)
    _echo_plan(plan, dry_run=dry_run)


@weekends_app.command("refresh")
def weekends_refresh(
    season: int = typer.Option(...), dry_run: bool = _DRY_RUN_OPT
) -> None:
    """Re-sync the season calendar from Jolpica (+ FastF1 local dates). Try --dry-run first.

    Renumbers existing weekends in place; skips (with a warning) any unseeded circuit."""
    with connection_scope() as conn:
        plan = race_weekends.run(conn, season=season, dry_run=dry_run)
    _echo_plan(plan, dry_run=dry_run)


@sessions_app.command("refresh")
def sessions_refresh(season: int = typer.Option(2026)) -> None:
    """Load each weekend's session timetable (names + UTC start times) from FastF1."""
    with connection_scope() as conn:
        sessions.run(conn, season=season)


@lap_records_app.command("refresh")
def lap_records_refresh() -> None:
    with connection_scope() as conn:
        pre_season_lap_records.run(conn)


@circuit_stats_app.command("recompute")
def circuit_stats_recompute(season: int = typer.Option(...)) -> None:
    with connection_scope() as conn:
        circuit_stats.run(conn, season=season)


@circuit_race_stats_app.command("recompute")
def circuit_race_stats_recompute(
    season: int = typer.Option(..., help="Upcoming season the rollup is keyed to."),
    circuit: str | None = typer.Option(None, "--circuit", help="Single circuit_id; default all."),
) -> None:
    """Mine empirical race analytics from the trailing seasons (all races, wet included)."""
    with connection_scope() as conn:
        circuit_race_stats.run(conn, season=season, circuit_id=circuit)


@race_traces_app.command("backfill")
def race_traces_backfill(
    season: int = typer.Option(..., help="Upcoming season; traces the 5 seasons before it."),
    circuit: str | None = typer.Option(None, "--circuit", help="Single circuit_id; default all."),
) -> None:
    """Build lap-by-lap traces for every race in the trailing seasons (resumable)."""
    with connection_scope() as conn:
        race_traces.run(conn, season=season, circuit_id=circuit)


@race_traces_app.command("refresh")
def race_traces_refresh(
    season: int = typer.Option(...),
    round: int = typer.Option(..., "--round", help="Official F1 round number."),
    circuit: str = typer.Option(..., "--circuit", help="circuit_id the race was held at."),
) -> None:
    """Build the trace for a single race (manual escape hatch; post-race does this too)."""
    with connection_scope() as conn:
        stored = race_traces.run_single(
            conn, circuit_id=circuit, season=season, round_number=round
        )
        typer.echo(f"race-traces {season} R{round}: {'stored' if stored else 'no data'}")


@race_overtakes_app.command("backfill")
def race_overtakes_backfill(
    season: int = typer.Option(..., help="Upcoming season; mines the 5 seasons before it."),
    circuit: str | None = typer.Option(None, "--circuit", help="Single circuit_id; default all."),
) -> None:
    """Detect and classify on-track overtakes for every race in the trailing seasons."""
    with connection_scope() as conn:
        race_overtakes.run(conn, season=season, circuit_id=circuit)


@race_overtakes_app.command("refresh")
def race_overtakes_refresh(
    season: int = typer.Option(...),
    round: int = typer.Option(..., "--round", help="Official F1 round number."),
    circuit: str = typer.Option(..., "--circuit", help="circuit_id the race was held at."),
) -> None:
    """Detect overtakes for a single race (the race-traces job does this too)."""
    with connection_scope() as conn:
        blob = race_overtakes.run_single(
            conn, circuit_id=circuit, season=season, round_number=round
        )
        if blob is None:
            typer.echo(f"overtakes {season} R{round}: no data")
        else:
            t = blob["totals"]
            typer.echo(
                f"overtakes {season} R{round}: racing={t['racing']} gross={t['gross']} "
                f"{ {k: v for k, v in t['by_kind'].items() if v} }"
            )


@weather_app.command("refresh")
def weather_refresh(
    season: int = typer.Option(...),
    round: int = typer.Option(..., "--round"),
) -> None:
    with connection_scope() as conn:
        weather.run(conn, season=season, round_number=round)


@strategies_app.command("generate")
def strategies_generate(
    season: int = typer.Option(...),
    round: int = typer.Option(..., "--round"),
) -> None:
    with connection_scope() as conn:
        strategies.run(conn, season=season, round_number=round)


@sim_strategies_app.command("generate")
def sim_strategies_generate(
    season: int = typer.Option(...),
    round: int = typer.Option(..., "--round"),
    mode: str = typer.Option("postquali", help="Sim mode: 'prelim' or 'postquali'."),
    sims: int = typer.Option(None, "--sims", help="Monte-Carlo count override (default: sim config)."),
    source: str = typer.Option(
        "disk", help="Cleaned-laps source: 'disk' (local pkl / FastF1) or 'db' (derived_artifacts)."
    ),
) -> None:
    """Run the strategy simulator and persist the race-level shown-5 + race-context stats."""
    with connection_scope() as conn:
        sim_strategies.run(
            conn, season=season, round_number=round, mode=mode, n_sims=sims, source=source
        )


@results_app.command("refresh")
def results_refresh(
    season: int = typer.Option(...),
    round: int = typer.Option(..., "--round"),
) -> None:
    with connection_scope() as conn:
        race_results.run(conn, season=season, round_number=round)


@results_app.command("backfill")
def results_backfill(
    start: int = typer.Option(2025, help="Most recent season to backfill."),
    count: int = typer.Option(6, help="Number of seasons back from --start."),
    circuit: str | None = typer.Option(None, "--circuit", help="Single circuit_id; default all."),
) -> None:
    """Backfill past race results (for the past-results archive)."""
    seasons = list(range(start, start - count, -1))
    circuit_ids = [circuit] if circuit else None
    with connection_scope() as conn:
        race_results.backfill(conn, seasons=seasons, circuit_ids=circuit_ids)


@standings_app.command("refresh")
def standings_refresh(
    season: int = typer.Option(...),
    round: int = typer.Option(..., "--round"),
) -> None:
    with connection_scope() as conn:
        standings.run(conn, season=season, round_number=round)
        # post_race.lap_records is also part of T+1, expose it via the orchestrator command;
        # standings alone is a fine manual operation.
        _ = post_race_lap_records  # silence unused


@standings_app.command("backfill")
def standings_backfill(
    start: int = typer.Option(2025, help="Most recent season to backfill."),
    count: int = typer.Option(1, help="Number of seasons back from --start."),
) -> None:
    """Backfill past seasons' final standings (the "last season" reference panel)."""
    seasons = list(range(start, start - count, -1))
    with connection_scope() as conn:
        standings.backfill(conn, seasons=seasons)


@session_results_app.command("save")
def session_results_save(
    season: int = typer.Option(...),
    round: int = typer.Option(..., "--round"),
    session: str = typer.Option(
        ...,
        "--session",
        help='FastF1 session name as stored in sessions.name, e.g. "Practice 1", '
        '"Qualifying", "Sprint", "Race".',
    ),
) -> None:
    """Fetch + save one session's classification from FastF1 (manual / backfill)."""
    with connection_scope() as conn:
        rw = repositories.get_race_weekend(conn, season, round)
        if rw is None:
            typer.echo(f"No race weekend {season} R{round}.")
            raise typer.Exit(code=1)
        sess = repositories.get_session_by_name(conn, rw.id, session)
        if sess is None:
            typer.echo(f"No session named {session!r} for {season} R{round}.")
            raise typer.Exit(code=1)
        post_session_results.run(conn, session_id=sess.id)


# --- orchestrator flows ---


@app.command("run-pre-season")
def run_pre_season(season: int = typer.Option(...)) -> None:
    orchestrator.run_pre_season(season)


@app.command("run-weather")
def run_weather() -> None:
    """Daily: refresh the forecast for the next weekend within 10 days (blank otherwise)."""
    orchestrator.run_weather_refresh()


_SOURCE_OPT = typer.Option(
    "disk", help="Cleaned-laps source: 'disk' (local pkl / FastF1) or 'db' (derived_artifacts)."
)


@app.command("run-prelim")
def run_prelim(
    season: int | None = typer.Option(
        None, help="Force prelim for this season (requires --round)."
    ),
    round_number: int | None = typer.Option(
        None, "--round", help="Force prelim for this round (requires --season)."
    ),
    source: str = _SOURCE_OPT,
) -> None:
    """Monday of race week: prelim strategy sim for that week's race (no-op otherwise).

    Pass --season and --round together to force the prelim sim for a specific weekend,
    skipping the race-week gate."""
    orchestrator.run_prelim_sim(season=season, round_number=round_number, source=source)


@app.command("run-prelim-remaining")
def run_prelim_remaining(
    season: int = typer.Option(...), source: str = _SOURCE_OPT
) -> None:
    """Manual bulk backfill: prelim sim for every round still to come this season.

    Unlike `run-prelim` (gated to the current race week), this sweeps the whole
    remaining calendar in one pass. Meant for workflow_dispatch, not a recurring
    schedule — each round re-fits season form from scratch."""
    orchestrator.run_prelim_sim_for_remaining_calendar(season=season, source=source)


@app.command("run-post-race")
def run_post_race() -> None:
    orchestrator.run_post_race_for_last_weekend()


@app.command("run-post-session")
def run_post_session(source: str = _SOURCE_OPT) -> None:
    """~45 min after each session: save session results, and run the postquali sim once
    Qualifying is done (idempotent catch-up)."""
    orchestrator.run_post_session(source=source)


@app.command("run-postquali-sim")
def run_postquali_sim(source: str = _SOURCE_OPT) -> None:
    """Postquali sim for any weekend whose quali finished ≥2h30 ago (idempotent catch-up).

    Manual escape hatch — the scheduled poll uses run-post-session, which does this too."""
    orchestrator.run_postquali_sim(source=source)


# --- derived-artifact store ---


@derived_app.command("dump-laps")
def derived_dump_laps(
    season: int = typer.Option(None, help="Dump only this season (requires --round)."),
    round: int = typer.Option(None, "--round", help="Dump only this round (requires --season)."),
) -> None:
    """Serialize cleaned per-race laps into the derived_artifacts table.

    No args: dump every local laps_*.pkl (one-time history backfill from a warm cache).
    With --season and --round: dump one race, fetching + cleaning it from FastF1 if it isn't
    cached (post-race refresh so the current season stays available to the sim in CI)."""
    from formation_data import artifact_store

    if (season is None) != (round is None):
        typer.echo("Provide both --season and --round, or neither.")
        raise typer.Exit(code=1)
    with connection_scope() as conn:
        if season is not None:
            stored = artifact_store.dump_race_laps(conn, season, round)
            typer.echo(f"dump-laps {season} R{round}: {'stored' if stored else 'no data'}")
        else:
            n = artifact_store.dump_all_local_laps(conn)
            typer.echo(f"dump-laps: stored {n} local laps files into derived_artifacts")


# --- schema ---


@db_app.command("upgrade")
def db_upgrade() -> None:
    """Apply the schema to DATABASE_URL (idempotent; safe on fresh or existing DBs)."""
    db.upgrade()


# --- F1TV sign-in ---


@f1tv_app.command("login")
def f1tv_login(
    method: str = typer.Option(
        None, help="'password' (default: F1_USERNAME/F1_PASSWORD or a prompt) or 'browser'."
    ),
) -> None:
    """Sign in to F1TV and store a token for FastF1 (valid ~4 days)."""
    status = f1tv.sign_in(method)
    typer.echo(f"Signed in to F1TV. {_describe_token(status)}")


@f1tv_app.command("status")
def f1tv_status() -> None:
    """Show whether FastF1 has a usable F1TV token. Exits 1 if jobs can't sign in."""
    status = f1tv.token_status()
    if status is None:
        typer.echo("Not signed in to F1TV.")
    elif status.valid:
        typer.echo(f"Signed in to F1TV. {_describe_token(status)}")
    else:
        typer.echo(f"F1TV token expired at {status.expires_at:%Y-%m-%d %H:%M} UTC.")

    if f1tv.credentials_in_env():
        typer.echo(
            f"{f1tv.ENV_USERNAME}/{f1tv.ENV_PASSWORD} are set, so jobs sign in again on "
            "their own when the token expires."
        )
    elif status is None or not status.valid:
        typer.echo(
            "Run `formation-data f1tv login` to sign in, or set "
            f"{f1tv.ENV_USERNAME}/{f1tv.ENV_PASSWORD} so jobs can sign in on their own."
        )
        raise typer.Exit(code=1)
    else:
        typer.echo(
            f"{f1tv.ENV_USERNAME}/{f1tv.ENV_PASSWORD} are not set, so run "
            "`formation-data f1tv login` again when the token expires."
        )


@f1tv_app.command("logout")
def f1tv_logout() -> None:
    """Delete the stored F1TV token."""
    f1tv.sign_out()
    typer.echo("Signed out of F1TV (stored token removed).")


def _describe_token(status: f1tv.TokenStatus) -> str:
    plan = " / ".join(p for p in (status.product, status.subscription_status) if p)
    return f"Token valid until {status.expires_at:%Y-%m-%d %H:%M} UTC" + (
        f" ({plan})." if plan else "."
    )


# --- error reporting ---


def _explain(exc: BaseException) -> tuple[str, str] | None:
    """(title, what-to-do) for failures with a known cause, else None."""
    if isinstance(exc, f1tv.F1AccessError):
        return exc.summary, str(exc)
    if isinstance(exc, fastf1_client.SessionDataUnavailable):
        return "No FastF1 data for this session", str(exc)
    if isinstance(exc, RateLimitExceededError):
        return (
            "FastF1 rate limit reached",
            "FastF1's hourly request budget is used up. Everything fetched so far is "
            "cached on disk and doesn't count again, so re-run in about an hour to "
            "pick up where this left off.",
        )
    if isinstance(exc, sa_exc.OperationalError) and _is_connection_failure(exc):
        return "Can't reach the database", _database_hint(exc)
    if isinstance(exc, httpx.HTTPStatusError):
        return (
            "An external API request failed",
            f"{exc.request.method} {exc.request.url} returned HTTP "
            f"{exc.response.status_code}. If it's a 5xx or 429, it's usually temporary, "
            "so retry later.",
        )
    if isinstance(exc, httpx.TransportError):
        return (
            "An external API couldn't be reached",
            f"{type(exc).__name__}: {exc}. Check the network connection and retry.",
        )
    return None


def _is_connection_failure(exc: sa_exc.OperationalError) -> bool:
    text = str(exc.orig).lower()
    return any(
        s in text
        for s in ("connection refused", "could not connect", "connection to server",
                  "could not translate host name", "timeout expired")
    )


def _database_hint(exc: sa_exc.OperationalError) -> str:
    url = sa_url.make_url(db._database_url())
    where = f"{url.host}:{url.port or 5432}/{url.database}"
    first_line = str(exc.orig).strip().splitlines()[0] if str(exc.orig).strip() else ""
    hint = f"Couldn't connect to Postgres at {where}"
    hint += f" ({first_line})." if first_line else "."
    if "DATABASE_URL" not in os.environ:
        hint += (
            "\nDATABASE_URL isn't set, so this is the local default. Start the local "
            "database with:\n    docker compose up -d db"
        )
    else:
        hint += "\nCheck DATABASE_URL and that the database server is running."
    return hint


def main() -> None:
    fastf1_client.enable_cache()
    try:
        app()
    except Exception as exc:
        explained = _explain(exc)
        if explained is None or _verbose:
            raise
        title, detail = explained
        typer.secho(f"\nError: {title}", fg=typer.colors.RED, bold=True, err=True)
        typer.echo(detail, err=True)
        typer.echo("(Re-run with --verbose for the full traceback.)", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
