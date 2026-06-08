import asyncio

from fastapi import APIRouter

from formation_data import repositories
from formation_data.db import connection_scope
from formation_data.domain import Circuit

router = APIRouter(prefix="/circuits", tags=["circuits"])


def _list_all() -> list[Circuit]:
    with connection_scope() as conn:
        return repositories.list_circuits(conn)


@router.get("/", response_model=list[Circuit])
async def list_circuits() -> list[Circuit]:
    return await asyncio.to_thread(_list_all)
