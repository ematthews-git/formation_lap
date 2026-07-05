import asyncio

from fastapi import APIRouter

from formation_data import repositories
from formation_data.db import connection_scope
from formation_data.domain import SimRaceStats, StrategyWithStints

router = APIRouter(prefix="/strategies", tags=["strategies"])


def _list(season: int, round_number: int, source: str | None) -> list[StrategyWithStints]:
    with connection_scope() as conn:
        return repositories.list_strategies_for_weekend(conn, season, round_number, source)


def _sim_stats(season: int, round_number: int) -> SimRaceStats | None:
    with connection_scope() as conn:
        return repositories.get_sim_race_stats(conn, season, round_number)


@router.get("/", response_model=list[StrategyWithStints])
async def list_strategies(season: int, round: int) -> list[StrategyWithStints]:
    """Historical (mined) strategy options for a race weekend, each with its stints.

    e.g. /strategies/?season=2026&round=11. These come from the last dry running of the
    circuit; for the simulated projection use /strategies/simulated. Empty list if none.
    """
    return await asyncio.to_thread(_list, season, round, "historical")


@router.get("/simulated", response_model=list[StrategyWithStints])
async def list_simulated_strategies(season: int, round: int) -> list[StrategyWithStints]:
    """Officially simulated strategy options — the race-level shown-5 from the sim.

    Each carries `phase` (prelim/postquali), `plausibility` and `tier`. The list holds the
    latest run's output: prelim until quali, then superseded by postquali. Empty list until
    the first sim has run for the weekend.
    """
    return await asyncio.to_thread(_list, season, round, "sim")


@router.get("/simulated/stats", response_model=SimRaceStats | None)
async def simulated_race_stats(season: int, round: int) -> SimRaceStats | None:
    """Race-context numbers from the sim (tyre life, undercut, SC/VSC prob, chaos index, …).

    Returns null until a sim has run for the weekend.
    """
    return await asyncio.to_thread(_sim_stats, season, round)
