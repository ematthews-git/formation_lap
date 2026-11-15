import asyncio

from fastapi import APIRouter

from formation_data import repositories
from formation_data.db import connection_scope
from formation_data.domain import SessionWeather

router = APIRouter(prefix="/weather", tags=["weather"])


def _list(season: int, round_number: int) -> list[SessionWeather]:
    with connection_scope() as conn:
        return repositories.list_weather_for_weekend(conn, season, round_number)


@router.get("/", response_model=list[SessionWeather])
async def list_weather(season: int, round: int) -> list[SessionWeather]:
    """Each session of a race weekend with the forecast for its day, in running order.

    e.g. /weather/?season=2026&round=11. The forecast is daily, so same-day sessions share
    one; a session's day is its local day at the circuit. Returns an empty list until the
    forecast is loaded (about ten days out).
    """
    return await asyncio.to_thread(_list, season, round)
