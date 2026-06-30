import asyncio

from fastapi import APIRouter

from formation_data import repositories
from formation_data.db import connection_scope
from formation_data.domain import WeatherForecast

router = APIRouter(prefix="/weather", tags=["weather"])


def _list(season: int, round_number: int) -> list[WeatherForecast]:
    with connection_scope() as conn:
        return repositories.list_weather_for_weekend(conn, season, round_number)


@router.get("/", response_model=list[WeatherForecast])
async def list_weather(season: int, round: int) -> list[WeatherForecast]:
    """Per-session weather forecast for a race weekend.

    e.g. /weather/?season=2026&round=11. Returns an empty list if no forecast
    has been loaded for the weekend yet.
    """
    return await asyncio.to_thread(_list, season, round)
