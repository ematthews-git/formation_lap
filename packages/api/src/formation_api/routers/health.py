import asyncio

from fastapi import APIRouter
from sqlalchemy import text

from formation_data.db import connection_scope

router = APIRouter(tags=["health"])


def _check_db() -> None:
    with connection_scope() as conn:
        conn.execute(text("SELECT 1"))


@router.get("/health")
async def health_check():
    await asyncio.to_thread(_check_db)
    return {"status": "ok", "database": "connected"}
