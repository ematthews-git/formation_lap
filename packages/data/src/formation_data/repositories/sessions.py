"""A weekend's sessions, their results, and the weather for each."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from sqlalchemy import Connection, func, select
from sqlalchemy.dialects.postgresql import insert

from formation_data import domain, schema
from formation_data.repositories.circuits import get_circuit
from formation_data.repositories.weekends import get_race_weekend


def upsert_session_results(
    conn: Connection, session_id: int, results: list[dict]
) -> None:
    """Upsert one session's classification blob (one row per session).

    Re-running for the same session overwrites the stored results — a later poll,
    once FastF1's data has firmed up, replaces an earlier partial classification.
    """
    stmt = insert(schema.session_results).values(
        session_id=session_id, results=results
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["session_id"],
        set_={
            "results": stmt.excluded.results,
            "updated_at": func.now(),
        },
    )
    conn.execute(stmt)


def get_session(conn: Connection, session_id: int) -> domain.Session | None:
    """Fetch a single session by its id, or None."""
    row = conn.execute(
        select(schema.sessions).where(schema.sessions.c.id == session_id)
    ).first()
    return domain.Session.model_validate(row._mapping) if row else None


def get_session_by_kind(
    conn: Connection, race_weekend_id: int, kind: str
) -> domain.Session | None:
    """Fetch a weekend's session of `kind` ("quali", "race", ...), or None. For manual saves."""
    row = conn.execute(
        select(schema.sessions).where(
            schema.sessions.c.race_weekend_id == race_weekend_id,
            schema.sessions.c.kind == kind,
        )
    ).first()
    return domain.Session.model_validate(row._mapping) if row else None


def list_sessions_for_weekend(
    conn: Connection, season: int, round_number: int
) -> list[domain.SessionWithResults]:
    """Session timetable for a race weekend, in running order (FP1 → Race).

    Each session carries its top-3 finishers (empty until results are saved). Returns
    `[]` when the weekend doesn't exist or has no sessions loaded yet.
    """
    rw = get_race_weekend(conn, season, round_number)
    if rw is None:
        return []
    rows = conn.execute(
        select(schema.sessions)
        .where(schema.sessions.c.race_weekend_id == rw.id)
        .order_by(schema.sessions.c.session_order)
    ).all()
    if not rows:
        return []

    sr = schema.session_results
    session_ids = [row.id for row in rows]
    top_by_session = {
        sid: _top_finishers(results)
        for sid, results in conn.execute(
            select(sr.c.session_id, sr.c.results).where(
                sr.c.session_id.in_(session_ids)
            )
        ).all()
    }
    return [
        domain.SessionWithResults(
            **row._mapping, top_finishers=top_by_session.get(row.id, [])
        )
        for row in rows
    ]


def _top_finishers(results: list[dict], n: int = 3) -> list[domain.SessionFinisher]:
    """Top-`n` finishers (by position) from a stored session_results blob."""
    ranked = [
        r
        for r in results
        if isinstance(r.get("position"), int) and 1 <= r["position"] <= n
    ]
    ranked.sort(key=lambda r: r["position"])
    return [
        domain.SessionFinisher(position=r["position"], driver_id=r["driver_id"])
        for r in ranked
    ]


def list_weather_for_weekend(
    conn: Connection, season: int, round_number: int
) -> list[domain.SessionWeather]:
    """Each of a weekend's sessions with the forecast for its day, in running order.

    A session's day is its local day at the circuit (circuits.timezone), which is how the
    daily forecast is stored. Sessions with no forecast for their day yet (too far out)
    are left out, so this is `[]` until the forecast lands, and also when the weekend
    doesn't exist or its timetable isn't loaded.
    """
    rw = get_race_weekend(conn, season, round_number)
    if rw is None:
        return []
    circuit = get_circuit(conn, rw.circuit_id)
    tz = ZoneInfo(circuit.timezone)
    wf, s = schema.weather_forecasts, schema.sessions
    by_day = {
        row.forecast_date: row
        for row in conn.execute(select(wf).where(wf.c.race_weekend_id == rw.id)).all()
    }
    out: list[domain.SessionWeather] = []
    for session in conn.execute(
        select(s).where(s.c.race_weekend_id == rw.id).order_by(s.c.session_order)
    ).all():
        day = by_day.get(session.start_time.astimezone(tz).date())
        if day is None:
            continue
        out.append(
            domain.SessionWeather(
                session_kind=session.kind,
                session_name=session.name,
                start_time=session.start_time,
                **{
                    k: v
                    for k, v in day._mapping.items()
                    if k not in ("id", "race_weekend_id")
                },
            )
        )
    return out
