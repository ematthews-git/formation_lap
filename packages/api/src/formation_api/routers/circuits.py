from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from formation_api.database import get_session
from formation_data.models import Circuit

router = APIRouter(prefix="/circuits", tags=["circuits"])


@router.get("/")
async def list_circuits(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Circuit))
    return result.scalars().all()
