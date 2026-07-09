"""`formation-data` CLI — one subcommand per job plus orchestrator flows.

Real wiring (so `formation-data --help` enumerates everything). The handlers themselves
open a connection_scope and call into the skeleton jobs, which log placeholder messages
today and will fetch + upsert via the repository layer in a follow-up.
"""

from __future__ import annotations

import logging

import typer

from formation_data import db, orchestrator, repositories
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
weather_app = typer.Typer(help="Race weekend weather forecast.")
strategies_app = typer.Typer(help="Historical (mined) strategy options.")
sim_strategies_app = typer.Typer(help="Simulated strategy options.")
results_app = typer.Typer(help="Race finishing order.")
standings_app = typer.Typer(help="Driver + constructor standings.")
session_results_app = typer.Typer(help="Per-session classification / timesheet.")
db_app = typer.Typer(help="Database schema management.")

app.add_typer(circuits_app, name="circuits")
app.add_typer(drivers_app, name="drivers")
app.add_typer(weekends_app, name="weekends")
app.add_typer(sessions_app, name="sessions")
app.add_typer(lap_records_app, name="lap-records")
app.add_typer(circuit_stats_app, name="circuit-stats")
app.add_typer(circuit_race_stats_app, name="circuit-race-stats")
app.add_typer(weather_app, name="weather")
app.add_typer(strategies_app, name="strategies")
app.add_typer(sim_strategies_app, name="sim-strategies")
app.add_typer(results_app, name="results")
app.add_typer(standings_app, name="standings")
app.add_typer(session_results_app, name="session-results")
app.add_typer(db_app, name="db")


@app.callback()
def _configure_logging(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
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


@weekends_app.command("seed")
def weekends_seed(season: int = typer.Option(2026)) -> None:
    """Hand-curated calendar (v1). Use `refresh` to pull from Jolpica instead."""
    with connection_scope() as conn:
        static_weekends.run(conn, season=season)


@weekends_app.command("refresh")
def weekends_refresh(season: int = typer.Option(...)) -> None:
    with connection_scope() as conn:
        race_weekends.run(conn, season=season)


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
) -> None:
    """Run the strategy simulator and persist the race-level shown-5 + race-context stats."""
    with connection_scope() as conn:
        sim_strategies.run(conn, season=season, round_number=round, mode=mode, n_sims=sims)


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


@app.command("run-prelim")
def run_prelim(
    season: int | None = typer.Option(
        None, help="Force prelim for this season (requires --round)."
    ),
    round_number: int | None = typer.Option(
        None, "--round", help="Force prelim for this round (requires --season)."
    ),
) -> None:
    """Monday of race week: prelim strategy sim for that week's race (no-op otherwise).

    Pass --season and --round together to force the prelim sim for a specific weekend,
    skipping the race-week gate."""
    orchestrator.run_prelim_sim(season=season, round_number=round_number)


@app.command("run-post-race")
def run_post_race() -> None:
    orchestrator.run_post_race_for_last_weekend()


@app.command("run-post-session")
def run_post_session() -> None:
    """~45 min after each session: save session results, and run the postquali sim once
    Qualifying is done (idempotent catch-up)."""
    orchestrator.run_post_session()


@app.command("run-postquali-sim")
def run_postquali_sim() -> None:
    """Postquali sim for any weekend whose quali finished ≥2h30 ago (idempotent catch-up).

    Manual escape hatch — the scheduled poll uses run-post-session, which does this too."""
    orchestrator.run_postquali_sim()


# --- schema ---


@db_app.command("upgrade")
def db_upgrade() -> None:
    """Apply the schema to DATABASE_URL (idempotent; safe on fresh or existing DBs)."""
    db.upgrade()


def main() -> None:
    fastf1_client.enable_cache()
    app()


if __name__ == "__main__":
    main()
