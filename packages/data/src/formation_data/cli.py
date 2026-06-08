"""`formation-data` CLI — one subcommand per job plus orchestrator flows.

Real wiring (so `formation-data --help` enumerates everything). The handlers themselves
open a session and call into the skeleton jobs, which log placeholder messages today
and will fetch + upsert in a follow-up.
"""

from __future__ import annotations

import logging

import typer

from formation_data import orchestrator
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
    with session_scope() as session:
        static_circuits.run(session)


@drivers_app.command("refresh")
def drivers_refresh(season: int = typer.Option(...)) -> None:
    with session_scope() as session:
        drivers.run(session, season=season)


@weekends_app.command("refresh")
def weekends_refresh(season: int = typer.Option(...)) -> None:
    with session_scope() as session:
        race_weekends.run(session, season=season)


@lap_records_app.command("refresh")
def lap_records_refresh() -> None:
    with session_scope() as session:
        pre_season_lap_records.run(session)


@circuit_stats_app.command("recompute")
def circuit_stats_recompute(season: int = typer.Option(...)) -> None:
    with session_scope() as session:
        circuit_stats.run(session, season=season)


@weather_app.command("refresh")
def weather_refresh(
    season: int = typer.Option(...),
    round: int = typer.Option(..., "--round"),
) -> None:
    with session_scope() as session:
        weather.run(session, season=season, round_number=round)


@strategies_app.command("generate")
def strategies_generate(
    season: int = typer.Option(...),
    round: int = typer.Option(..., "--round"),
) -> None:
    with session_scope() as session:
        strategies.run(session, season=season, round_number=round)


@results_app.command("refresh")
def results_refresh(
    season: int = typer.Option(...),
    round: int = typer.Option(..., "--round"),
) -> None:
    with session_scope() as session:
        race_results.run(session, season=season, round_number=round)


@standings_app.command("refresh")
def standings_refresh(
    season: int = typer.Option(...),
    round: int = typer.Option(..., "--round"),
) -> None:
    with session_scope() as session:
        standings.run(session, season=season, round_number=round)
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
    app()


if __name__ == "__main__":
    main()
