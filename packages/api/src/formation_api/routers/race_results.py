import asyncio

from fastapi import APIRouter

from formation_data import repositories
from formation_data.db import connection_scope
from formation_data.domain import RaceResult

router = APIRouter(prefix="/race-results", tags=["race-results"])


def _list(season: int) -> list[RaceResult]:
    with connection_scope() as conn:
        return repositories.list_race_results(conn, season)


@router.get("/", response_model=list[RaceResult])
async def list_race_results(season: int) -> list[RaceResult]:
    """All race finishing positions for a season, e.g. /race-results/?season=2026.

    Ordered by round then position. Returns an empty list if none loaded yet.
    """
    return await asyncio.to_thread(_list, season)
