import asyncio

from fastapi import APIRouter, Query

from formation_data import repositories
from formation_data.db import connection_scope
from formation_data.domain import Standing

router = APIRouter(prefix="/standings", tags=["standings"])


def _list(season: int, type: str, after_round: int | None) -> list[Standing]:
    with connection_scope() as conn:
        return repositories.list_standings(conn, season, type, after_round)


@router.get("/", response_model=list[Standing])
async def list_standings(
    season: int,
    type: str = Query("driver", pattern="^(driver|constructor)$"),
    after_round: int | None = None,
) -> list[Standing]:
    """Championship standings, e.g. /standings/?season=2026&type=constructor.

    Omit `after_round` to get the latest standings available for the season.
    """
    return await asyncio.to_thread(_list, season, type, after_round)
