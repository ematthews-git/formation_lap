import asyncio

from fastapi import APIRouter

from formation_data import repositories
from formation_data.db import connection_scope
from formation_data.domain import GridDriver

router = APIRouter(prefix="/drivers", tags=["drivers"])


def _list_for_season(season: int) -> list[GridDriver]:
    with connection_scope() as conn:
        return repositories.list_season_grid(conn, season)


@router.get("/", response_model=list[GridDriver])
async def list_drivers(season: int) -> list[GridDriver]:
    """The driver grid for a season with each driver's team, e.g. /drivers/?season=2026."""
    return await asyncio.to_thread(_list_for_season, season)
