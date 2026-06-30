import asyncio

from fastapi import APIRouter

from formation_data import repositories
from formation_data.db import connection_scope
from formation_data.domain import Driver

router = APIRouter(prefix="/drivers", tags=["drivers"])


def _list_for_season(season: int) -> list[Driver]:
    with connection_scope() as conn:
        return repositories.list_drivers(conn, season)


@router.get("/", response_model=list[Driver])
async def list_drivers(season: int) -> list[Driver]:
    """The driver grid for a season, e.g. /drivers/?season=2026."""
    return await asyncio.to_thread(_list_for_season, season)
