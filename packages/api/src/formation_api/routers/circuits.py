import asyncio

from fastapi import APIRouter, HTTPException

from formation_data import repositories
from formation_data.db import connection_scope
from formation_data.domain import Circuit, CircuitStats, LapRecord

router = APIRouter(prefix="/circuits", tags=["circuits"])


def _list_all() -> list[Circuit]:
    with connection_scope() as conn:
        return repositories.list_circuits(conn)


def _get_one(circuit_id: str) -> Circuit | None:
    with connection_scope() as conn:
        return repositories.get_circuit(conn, circuit_id)


def _get_stats(circuit_id: str, season: int) -> CircuitStats | None:
    with connection_scope() as conn:
        return repositories.get_circuit_stats(conn, circuit_id, season)


def _get_lap_record(circuit_id: str) -> LapRecord | None:
    with connection_scope() as conn:
        return repositories.get_lap_record_for_circuit(conn, circuit_id)


@router.get("/", response_model=list[Circuit])
async def list_circuits() -> list[Circuit]:
    return await asyncio.to_thread(_list_all)


@router.get("/{circuit_id}", response_model=Circuit)
async def get_circuit(circuit_id: str) -> Circuit:
    circuit = await asyncio.to_thread(_get_one, circuit_id)
    if circuit is None:
        raise HTTPException(status_code=404, detail="Circuit not found")
    return circuit


@router.get("/{circuit_id}/stats", response_model=CircuitStats)
async def get_circuit_stats(circuit_id: str, season: int) -> CircuitStats:
    stats = await asyncio.to_thread(_get_stats, circuit_id, season)
    if stats is None:
        raise HTTPException(
            status_code=404, detail="No stats for that circuit and season"
        )
    return stats


@router.get("/{circuit_id}/lap-record", response_model=LapRecord)
async def get_lap_record(circuit_id: str) -> LapRecord:
    record = await asyncio.to_thread(_get_lap_record, circuit_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No lap record for that circuit")
    return record
