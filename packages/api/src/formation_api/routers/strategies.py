import asyncio

from fastapi import APIRouter

from formation_data import repositories
from formation_data.db import connection_scope
from formation_data.domain import StrategyWithStints

router = APIRouter(prefix="/strategies", tags=["strategies"])


def _list(season: int, round_number: int) -> list[StrategyWithStints]:
    with connection_scope() as conn:
        return repositories.list_strategies_for_weekend(conn, season, round_number)


@router.get("/", response_model=list[StrategyWithStints])
async def list_strategies(season: int, round: int) -> list[StrategyWithStints]:
    """Generated strategy options for a race weekend, each with its ordered stints.

    e.g. /strategies/?season=2026&round=11. Returns an empty list if the weekend
    has no strategies generated yet.
    """
    return await asyncio.to_thread(_list, season, round)
