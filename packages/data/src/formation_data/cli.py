"""`formation-data` CLI — one subcommand per job plus orchestrator flows.

Real wiring (so `formation-data --help` enumerates everything). The handlers themselves
open a connection_scope and call into the skeleton jobs, which log placeholder messages
today and will fetch + upsert via the repository layer in a follow-up.
"""

from __future__ import annotations

import logging

import typer

from formation_data import orchestrator
from formation_data.db import connection_scope
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
lap_records_app = typer.Typer(help="All-time race lap records.")
circuit_stats_app = typer.Typer(help="Per-circuit per-season stats.")
weather_app = typer.Typer(help="Race weekend weather forecast.")
strategies_app = typer.Typer(help="Generated strategy options.")
results_app = typer.Typer(help="Race finishing order.")
standings_app = typer.Typer(help="Driver + constructor standings.")

app.add_typer(circuits_app, name="circuits")
app.add_typer(drivers_app, name="drivers")
app.add_typer(weekends_app, name="weekends")
app.add_typer(lap_records_app, name="lap-records")
app.add_typer(circuit_stats_app, name="circuit-stats")
app.add_typer(weather_app, name="weather")
app.add_typer(strategies_app, name="strategies")
app.add_typer(results_app, name="results")
app.add_typer(standings_app, name="standings")


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


@lap_records_app.command("refresh")
def lap_records_refresh() -> None:
    with connection_scope() as conn:
        pre_season_lap_records.run(conn)


@circuit_stats_app.command("recompute")
def circuit_stats_recompute(season: int = typer.Option(...)) -> None:
    with connection_scope() as conn:
        circuit_stats.run(conn, season=season)


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


# --- orchestrator flows ---


@app.command("run-pre-season")
def run_pre_season(season: int = typer.Option(...)) -> None:
    orchestrator.run_pre_season(season)


@app.command("run-pre-race")
def run_pre_race() -> None:
    orchestrator.run_pre_race_for_next_weekend()


@app.command("run-post-race")
def run_post_race() -> None:
    orchestrator.run_post_race_for_last_weekend()


def main() -> None:
    fastf1_client.enable_cache()
    app()


if __name__ == "__main__":
    main()
