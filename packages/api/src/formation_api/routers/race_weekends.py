import asyncio

from fastapi import APIRouter, HTTPException

from formation_data import repositories
from formation_data.db import connection_scope
from formation_data.domain import RaceWeekend

router = APIRouter(prefix="/race-weekends", tags=["race-weekends"])


def _list_for_season(season: int) -> list[RaceWeekend]:
    with connection_scope() as conn:
        return repositories.list_race_weekends(conn, season)


def _get_one(season: int, round_number: int) -> RaceWeekend | None:
    with connection_scope() as conn:
        return repositories.get_race_weekend(conn, season, round_number)


@router.get("/", response_model=list[RaceWeekend])
async def list_race_weekends(season: int) -> list[RaceWeekend]:
    """The race calendar for a season, e.g. /race-weekends/?season=2026."""
    return await asyncio.to_thread(_list_for_season, season)


@router.get("/{season}/{round_number}", response_model=RaceWeekend)
async def get_race_weekend(season: int, round_number: int) -> RaceWeekend:
    weekend = await asyncio.to_thread(_get_one, season, round_number)
    if weekend is None:
        raise HTTPException(status_code=404, detail="Race weekend not found")
    return weekend
