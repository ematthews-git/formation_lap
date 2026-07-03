import asyncio

from fastapi import APIRouter

from formation_data import repositories
from formation_data.db import connection_scope
from formation_data.domain import Session

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _list(season: int, round_number: int) -> list[Session]:
    with connection_scope() as conn:
        return repositories.list_sessions_for_weekend(conn, season, round_number)


@router.get("/", response_model=list[Session])
async def list_sessions(season: int, round: int) -> list[Session]:
    """Session timetable for a race weekend, in running order (FP1 → Race).

    e.g. /sessions/?season=2026&round=11. Returns an empty list if no sessions
    have been loaded for the weekend yet. Each session's `start_time` is a UTC
    instant.
    """
    return await asyncio.to_thread(_list, season, round)
