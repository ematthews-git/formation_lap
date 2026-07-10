"""Repository layer — generic upsert + table-specific reads.

Every job writes rows the same way: build a list of domain models, then upsert
keyed on a unique constraint. The single `upsert()` helper covers all 9 tables.

Reads with real logic (filter by date, lookup by composite key) get their own
small functions below — there are only a handful, so keeping them here beats
spreading them across per-table modules.

The one bundled operation is `upsert_strategy_with_stints`, because a strategy
row's auto-id has to land before its child stints can be inserted.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date, datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import Connection, Table, and_, delete, exists, func, select, tuple_
from sqlalchemy.dialects.postgresql import insert

from formation_data import domain, flexibility, schema

logger = logging.getLogger(__name__)

# A postquali sim becomes due this many minutes after the Qualifying session *starts*
# (≈1h session + 1h30 buffer for FastF1's delayed data upload).
POSTQUALI_DELAY_MIN = 150

# Session results become due this many minutes after a session *ends*. Sessions store
# only a start time, so the end is estimated as start + SESSION_DURATION_MIN[name].
SESSION_RESULT_DELAY_MIN = 45
# Estimated running length per session (FastF1 session names, as stored in sessions.name).
# Only used to place the "results due" cutoff; red-flag overruns are absorbed by the
# idempotent retry (a not-yet-available session just lands on a later poll).
SESSION_DURATION_MIN = {
    "Practice 1": 60,
    "Practice 2": 60,
    "Practice 3": 60,
    "Qualifying": 60,
    "Sprint Qualifying": 45,
    "Sprint Shootout": 45,
    "Sprint": 60,
    "Race": 120,
}
_DEFAULT_SESSION_DURATION_MIN = 60
# Don't rescan the whole season on every poll: a session with no results after this long
# is stale (FastF1 would have had data), so we stop retrying it. Wide enough to catch up a
# full weekend after a missed cron run.
SESSION_RESULTS_LOOKBACK = timedelta(days=7)

# Columns the database owns. Excluded from upsert payloads so server defaults
# apply on insert; refreshed explicitly on conflict (ON CONFLICT DO UPDATE does
# not run SQLAlchemy `onupdate` hooks).
_SERVER_MANAGED_COLS = {"updated_at"}


# --- write ---


def upsert(
    conn: Connection,
    table: Table,
    items: Iterable[BaseModel],
    conflict_cols: list[str],
    update_exclude: set[str] | None = None,
) -> int:
    """Upsert a batch of domain models into `table`, keyed on `conflict_cols`.

    Auto-id PKs and server-managed columns are excluded from the dump (not via
    `exclude_none` — that would also drop legitimately-None values once nullable
    columns exist, and multi-row inserts need homogeneous keys). On conflict,
    every other non-conflict column is replaced with the incoming row's value.

    `update_exclude` names columns to leave untouched on conflict — used when a
    hand-authored seed shares a table with columns another job populates (e.g.
    the circuits seed must not clobber `track_outline`). Those columns are still
    set on insert (to the incoming value, typically None), just not on update.
    """
    payload = [
        item.model_dump(exclude={"id"} | _SERVER_MANAGED_COLS) for item in items
    ]  # union op
    if not payload:
        return 0
    stmt = insert(table).values(payload)
    preserve = _SERVER_MANAGED_COLS | (update_exclude or set())
    update_cols = [
        c.name
        for c in table.c
        if c.name not in conflict_cols
        and not c.primary_key
        and c.name not in preserve
    ]
    if update_cols:
        set_ = {col: stmt.excluded[col] for col in update_cols}
        if "updated_at" in table.c:
            set_["updated_at"] = func.now()
        stmt = stmt.on_conflict_do_update(index_elements=conflict_cols, set_=set_)
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=conflict_cols)
    return conn.execute(stmt).rowcount


def upsert_strategy_with_stints(
    conn: Connection, strategy: domain.Strategy, stints: list[domain.StrategyStint]
) -> int:
    """Upsert a Strategy and its stints atomically; returns the strategy id.

    The strategy row is inserted (or updated, keyed on its unique
    (race_weekend_id, source, label)) with RETURNING so its auto-id lands before
    the child stints are written — each stint's `strategy_id` is swapped to the
    returned id, then the stints upsert keyed on (strategy_id, stint_order).
    """
    strat_payload = strategy.model_dump(exclude={"id"} | _SERVER_MANAGED_COLS)
    strat_stmt = insert(schema.strategies).values(strat_payload)
    strat_stmt = strat_stmt.on_conflict_do_update(
        index_elements=["race_weekend_id", "source", "label"],
        set_={
            "is_base": strat_stmt.excluded.is_base,
            "num_stops": strat_stmt.excluded.num_stops,
            "phase": strat_stmt.excluded.phase,
            "plausibility": strat_stmt.excluded.plausibility,
            "tier": strat_stmt.excluded.tier,
            "updated_at": func.now(),
        },
    ).returning(schema.strategies.c.id)
    strategy_id = conn.execute(strat_stmt).scalar_one()

    for s in stints:
        s.strategy_id = strategy_id
    upsert(conn, schema.strategy_stints, stints, ["strategy_id", "stint_order"])
    return strategy_id


def delete_strategies_for_weekend(
    conn: Connection, race_weekend_id: int, source: str | None = None
) -> int:
    """Delete strategies (and their stints) for a race weekend.

    Used before a fresh strategy generation so strategies that are no longer in
    the current top-N don't linger. Pass `source` to scope the delete to one
    provenance ("historical" / "sim") so regenerating one doesn't wipe the other.
    There's no ON DELETE CASCADE on the FK, so the child stints are removed first.
    Returns the number of strategies deleted.
    """
    cond = [schema.strategies.c.race_weekend_id == race_weekend_id]
    if source is not None:
        cond.append(schema.strategies.c.source == source)
    ids = conn.execute(select(schema.strategies.c.id).where(*cond)).scalars().all()
    if not ids:
        return 0
    conn.execute(
        delete(schema.strategy_stints).where(
            schema.strategy_stints.c.strategy_id.in_(ids)
        )
    )
    conn.execute(delete(schema.strategies).where(schema.strategies.c.id.in_(ids)))
    return len(ids)


def upsert_sim_race_stats(
    conn: Connection, race_weekend_id: int, phase: str, stats: dict
) -> None:
    """Upsert the race-context stats blob for a weekend (one row per weekend).

    A later phase overwrites an earlier one — postquali supersedes prelim.
    """
    stmt = insert(schema.sim_race_stats).values(
        race_weekend_id=race_weekend_id, phase=phase, stats=stats
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["race_weekend_id"],
        set_={
            "phase": stmt.excluded.phase,
            "stats": stmt.excluded.stats,
            "generated_at": func.now(),
        },
    )
    conn.execute(stmt)


def upsert_circuit_race_stats(
    conn: Connection, circuit_id: str, season: int, stats: dict
) -> None:
    """Upsert the empirical race-analytics blob for a circuit (one row per circuit-season).

    Re-running for the same (circuit, season) replaces the blob — the whole feed is recomputed
    from the trailing window each run, so there's nothing to merge.
    """
    stmt = insert(schema.circuit_race_stats).values(
        circuit_id=circuit_id, season=season, stats=stats
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["circuit_id", "season"],
        set_={
            "stats": stmt.excluded.stats,
            "updated_at": func.now(),
        },
    )
    conn.execute(stmt)


def upsert_derived_artifact(
    conn: Connection,
    *,
    kind: str,
    year: int,
    round_number: int,
    data: bytes,
    data_format: str = "parquet",
) -> None:
    """Upsert one serialized per-race derived table (one row per kind+year+round).

    Re-dumping a race replaces its blob — the frame is regenerated wholesale, nothing to merge.
    """
    stmt = insert(schema.derived_artifacts).values(
        kind=kind,
        year=year,
        round_number=round_number,
        data=data,
        data_format=data_format,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["kind", "year", "round_number"],
        set_={
            "data": stmt.excluded.data,
            "data_format": stmt.excluded.data_format,
            "updated_at": func.now(),
        },
    )
    conn.execute(stmt)


def get_derived_artifact(
    conn: Connection, *, kind: str, year: int, round_number: int
) -> domain.DerivedArtifact | None:
    """The serialized derived table for (kind, year, round), or None if not stored."""
    row = conn.execute(
        select(schema.derived_artifacts).where(
            schema.derived_artifacts.c.kind == kind,
            schema.derived_artifacts.c.year == year,
            schema.derived_artifacts.c.round_number == round_number,
        )
    ).first()
    return domain.DerivedArtifact.model_validate(row._mapping) if row else None


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


# --- read ---


def list_circuits(conn: Connection) -> list[domain.Circuit]:
    """Gets the list of circuits from database.

    Args:
        conn (Connection): Database connection.

    Returns:
        list[domain.Circuit]: List of circuits as domain dataclass.
    """
    rows = conn.execute(
        select(schema.circuits).order_by(schema.circuits.c.circuit_id)
    ).all()
    return [domain.Circuit.model_validate(row._mapping) for row in rows]


def get_circuit(conn: Connection, circuit_id: str) -> domain.Circuit | None:
    """Fetch a single circuit by its id, or None if it doesn't exist."""
    row = conn.execute(
        select(schema.circuits).where(schema.circuits.c.circuit_id == circuit_id)
    ).first()
    return domain.Circuit.model_validate(row._mapping) if row else None


def list_race_weekends(conn: Connection, season: int) -> list[domain.RaceWeekend]:
    """All race weekends for a season, in calendar (round) order."""
    rows = conn.execute(
        select(schema.race_weekends)
        .where(schema.race_weekends.c.season == season)
        .order_by(schema.race_weekends.c.round_number)
    ).all()
    return [domain.RaceWeekend.model_validate(row._mapping) for row in rows]


def remaining_race_weekends(
    conn: Connection, season: int, today: date
) -> list[domain.RaceWeekend]:
    """Race weekends in `season` whose race hasn't happened yet (race_date >= today),
    in round order. Drives the bulk prelim backfill (`run-prelim-remaining`)."""
    rows = conn.execute(
        select(schema.race_weekends)
        .where(
            schema.race_weekends.c.season == season,
            schema.race_weekends.c.race_date >= today,
        )
        .order_by(schema.race_weekends.c.round_number)
    ).all()
    return [domain.RaceWeekend.model_validate(row._mapping) for row in rows]


def get_race_weekend(
    conn: Connection, season: int, round_number: int
) -> domain.RaceWeekend | None:
    """Fetch a single race weekend by (season, round_number), or None."""
    row = conn.execute(
        select(schema.race_weekends).where(
            schema.race_weekends.c.season == season,
            schema.race_weekends.c.round_number == round_number,
        )
    ).first()
    return domain.RaceWeekend.model_validate(row._mapping) if row else None


def get_race_weekend_by_id(
    conn: Connection, race_weekend_id: int
) -> domain.RaceWeekend | None:
    """Fetch a single race weekend by its surrogate id, or None."""
    row = conn.execute(
        select(schema.race_weekends).where(
            schema.race_weekends.c.id == race_weekend_id
        )
    ).first()
    return domain.RaceWeekend.model_validate(row._mapping) if row else None


def list_drivers(conn: Connection, season: int) -> list[domain.Driver]:
    """All drivers for a season, ordered by name."""
    rows = conn.execute(
        select(schema.drivers)
        .where(schema.drivers.c.season == season)
        .order_by(schema.drivers.c.full_name)
    ).all()
    return [domain.Driver.model_validate(row._mapping) for row in rows]


def list_standings(
    conn: Connection,
    season: int,
    type: str,
    after_round: int | None = None,
) -> list[domain.Standing]:
    """Championship standings for a season and type ("driver"/"constructor").

    When `after_round` is omitted, returns the most recent round available for
    that season+type. Results are ordered by championship position.
    """
    table = schema.standings
    if after_round is None:
        after_round = conn.execute(
            select(func.max(table.c.after_round)).where(
                table.c.season == season, table.c.type == type
            )
        ).scalar()
        if after_round is None:
            return []
    rows = conn.execute(
        select(table)
        .where(
            table.c.season == season,
            table.c.type == type,
            table.c.after_round == after_round,
        )
        .order_by(table.c.position)
    ).all()
    return [domain.Standing.model_validate(row._mapping) for row in rows]


def list_circuit_podiums(
    conn: Connection, circuit_id: str, limit: int = 5
) -> list[domain.RaceResult]:
    """Top-3 finishers for the most recent `limit` races at a circuit.

    Rows are ordered most-recent race first, then finishing position; the caller
    groups consecutive rows sharing (season, round_number) into one race. Returns
    fewer than `limit` races (or `[]`) when the circuit lacks that much history.
    """
    rr = schema.race_results
    races = conn.execute(
        select(rr.c.season, rr.c.round_number)
        .where(rr.c.circuit_id == circuit_id)
        .distinct()
        .order_by(rr.c.season.desc(), rr.c.round_number.desc())
        .limit(limit)
    ).all()
    if not races:
        return []
    pairs = [(r.season, r.round_number) for r in races]
    rows = conn.execute(
        select(rr)
        .where(
            rr.c.circuit_id == circuit_id,
            rr.c.position <= 3,
            tuple_(rr.c.season, rr.c.round_number).in_(pairs),
        )
        .order_by(
            rr.c.season.desc(), rr.c.round_number.desc(), rr.c.position.asc()
        )
    ).all()
    return [domain.RaceResult.model_validate(row._mapping) for row in rows]


def list_race_results(conn: Connection, season: int) -> list[domain.RaceResult]:
    """All race results for a season, ordered by round then finishing position."""
    rows = conn.execute(
        select(schema.race_results)
        .where(schema.race_results.c.season == season)
        .order_by(
            schema.race_results.c.round_number,
            schema.race_results.c.position,
        )
    ).all()
    return [domain.RaceResult.model_validate(row._mapping) for row in rows]


def next_race_weekend_within(
    conn: Connection, today: date, window: timedelta
) -> domain.RaceWeekend | None:
    """The soonest race weekend whose race falls in [today, today+window], or None."""
    row = conn.execute(
        select(schema.race_weekends)
        .where(
            schema.race_weekends.c.race_date >= today,
            schema.race_weekends.c.race_date <= today + window,
        )
        .order_by(schema.race_weekends.c.race_date.asc())
        .limit(1)
    ).first()
    return domain.RaceWeekend.model_validate(row._mapping) if row else None


def race_weekends_missing_results(
    conn: Connection, before: date
) -> list[domain.RaceWeekend]:
    """Past race weekends (race strictly before `before`) with no results loaded yet.

    Drives the post-race catch-up loop: a missed cron run plus back-to-back weekends
    would otherwise leave a permanent hole, so we re-scan every past weekend rather than
    only the most recent. Ordered oldest-first, so cumulative standings load in
    chronological order.

    Matched on (circuit_id, season), not round_number: `race_weekends` carries our
    compacted seed round while `race_results` stores the official F1 round, so the two
    don't share a round space. Unambiguous for current-season use (one race per circuit);
    a historical double-header would need the round to disambiguate.
    """
    rw = schema.race_weekends
    rr = schema.race_results
    has_results = (
        select(rr.c.id)
        .where(rr.c.circuit_id == rw.c.circuit_id, rr.c.season == rw.c.season)
        .exists()
    )
    rows = conn.execute(
        select(rw)
        .where(rw.c.race_date < before, ~has_results)
        .order_by(rw.c.race_date.asc())
    ).all()
    return [domain.RaceWeekend.model_validate(row._mapping) for row in rows]


def most_recent_race_weekend_before(
    conn: Connection, today: date
) -> domain.RaceWeekend | None:
    """The latest race weekend whose race is strictly before `today`, or None."""
    row = conn.execute(
        select(schema.race_weekends)
        .where(schema.race_weekends.c.race_date < today)
        .order_by(schema.race_weekends.c.race_date.desc())
        .limit(1)
    ).first()
    return domain.RaceWeekend.model_validate(row._mapping) if row else None


def next_race_weekend_after(
    conn: Connection, race_date: date
) -> domain.RaceWeekend | None:
    """The soonest race weekend strictly after `race_date` — the weekend to run a
    prelim sim for once the previous one has finished. None if none is seeded yet."""
    row = conn.execute(
        select(schema.race_weekends)
        .where(schema.race_weekends.c.race_date > race_date)
        .order_by(schema.race_weekends.c.race_date.asc())
        .limit(1)
    ).first()
    return domain.RaceWeekend.model_validate(row._mapping) if row else None


def weekends_postquali_due(
    conn: Connection, now: datetime
) -> list[domain.RaceWeekend]:
    """Weekends whose postquali sim is due but not yet produced.

    Due = Qualifying started ≥ POSTQUALI_DELAY_MIN ago, the Race hasn't started yet,
    and no postquali `sim_race_stats` row exists. `now` must be timezone-aware (UTC),
    to compare against the timestamptz session start times. Drives the idempotent
    catch-up flow: safe to call repeatedly — a weekend drops out once its postquali runs.
    """
    cutoff = now - timedelta(minutes=POSTQUALI_DELAY_MIN)
    rw = schema.race_weekends
    quali = schema.sessions.alias("quali")
    race = schema.sessions.alias("race")
    srs = schema.sim_race_stats
    postquali_done = exists().where(
        and_(srs.c.race_weekend_id == rw.c.id, srs.c.phase == "postquali")
    )
    rows = conn.execute(
        select(rw)
        .join(quali, and_(quali.c.race_weekend_id == rw.c.id, quali.c.name == "Qualifying"))
        .join(race, and_(race.c.race_weekend_id == rw.c.id, race.c.name == "Race"))
        .where(quali.c.start_time <= cutoff, race.c.start_time > now, ~postquali_done)
        .order_by(rw.c.race_date.asc())
    ).all()
    return [domain.RaceWeekend.model_validate(row._mapping) for row in rows]


def get_session(conn: Connection, session_id: int) -> domain.Session | None:
    """Fetch a single session by its id, or None."""
    row = conn.execute(
        select(schema.sessions).where(schema.sessions.c.id == session_id)
    ).first()
    return domain.Session.model_validate(row._mapping) if row else None


def get_session_by_name(
    conn: Connection, race_weekend_id: int, name: str
) -> domain.Session | None:
    """Fetch a weekend's session by its (FastF1) name, or None. For manual saves."""
    row = conn.execute(
        select(schema.sessions).where(
            schema.sessions.c.race_weekend_id == race_weekend_id,
            schema.sessions.c.name == name,
        )
    ).first()
    return domain.Session.model_validate(row._mapping) if row else None


def results_due_at(session_name: str, start_time: datetime) -> datetime:
    """The instant a session's results become due to save.

    Estimated as start + running length (SESSION_DURATION_MIN, keyed on the FastF1
    session name) + SESSION_RESULT_DELAY_MIN, since sessions store only a start time.
    """
    duration = SESSION_DURATION_MIN.get(session_name, _DEFAULT_SESSION_DURATION_MIN)
    return start_time + timedelta(minutes=duration + SESSION_RESULT_DELAY_MIN)


def session_results_due(conn: Connection, now: datetime) -> list[domain.Session]:
    """Sessions whose results are due to be saved but haven't been yet.

    Due = `results_due_at(name, start) <= now` and no session_results row exists yet.
    `now` must be timezone-aware (UTC), to compare against the timestamptz start times.
    Bounded to the last SESSION_RESULTS_LOOKBACK so the poll doesn't rescan the season.
    Drives the idempotent catch-up flow: a session drops out once its results land.
    """
    s = schema.sessions
    sr = schema.session_results
    has_results = exists().where(sr.c.session_id == s.c.id)
    rows = conn.execute(
        select(s)
        .where(
            s.c.start_time >= now - SESSION_RESULTS_LOOKBACK,
            s.c.start_time <= now,
            ~has_results,
        )
        .order_by(s.c.start_time.asc())
    ).all()
    due: list[domain.Session] = []
    for row in rows:
        sess = domain.Session.model_validate(row._mapping)
        if results_due_at(sess.name, sess.start_time) <= now:
            due.append(sess)
    return due


def get_lap_record_for_circuit(
    conn: Connection, circuit_id: str
) -> domain.LapRecord | None:
    """Fetch the lap record for a circuit, or None if not set."""
    row = conn.execute(
        select(schema.lap_records).where(
            schema.lap_records.c.circuit_id == circuit_id
        )
    ).first()
    return domain.LapRecord.model_validate(row._mapping) if row else None


def list_strategies_for_weekend(
    conn: Connection, season: int, round_number: int, source: str | None = None
) -> list[domain.StrategyWithStints]:
    """Generated strategies (each with its ordered stints) for a race weekend.

    Base strategy first, then by stop count. Pass `source` ("historical" / "sim")
    to scope to one provenance. Returns `[]` when the weekend doesn't exist or has
    no matching strategies yet.
    """
    rw = get_race_weekend(conn, season, round_number)
    if rw is None:
        return []

    cond = [schema.strategies.c.race_weekend_id == rw.id]
    if source is not None:
        cond.append(schema.strategies.c.source == source)
    strat_rows = conn.execute(
        select(schema.strategies)
        .where(*cond)
        .order_by(
            schema.strategies.c.is_base.desc(),
            schema.strategies.c.num_stops,
            schema.strategies.c.label,
        )
    ).all()
    if not strat_rows:
        return []

    strategy_ids = [row.id for row in strat_rows]
    stint_rows = conn.execute(
        select(schema.strategy_stints)
        .where(schema.strategy_stints.c.strategy_id.in_(strategy_ids))
        .order_by(
            schema.strategy_stints.c.strategy_id,
            schema.strategy_stints.c.stint_order,
        )
    ).all()

    stints_by_strategy: dict[int, list[domain.StrategyStint]] = {}
    for row in stint_rows:
        stints_by_strategy.setdefault(row.strategy_id, []).append(
            domain.StrategyStint.model_validate(row._mapping)
        )

    return [
        domain.StrategyWithStints(
            **row._mapping, stints=stints_by_strategy.get(row.id, [])
        )
        for row in strat_rows
    ]


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
) -> list[domain.WeatherForecast]:
    """Per-session weather forecast for a race weekend, in chronological order.

    Returns `[]` when the weekend doesn't exist or has no forecast loaded yet.
    """
    rw = get_race_weekend(conn, season, round_number)
    if rw is None:
        return []
    rows = conn.execute(
        select(schema.weather_forecasts)
        .where(schema.weather_forecasts.c.race_weekend_id == rw.id)
        .order_by(
            schema.weather_forecasts.c.session_date,
            schema.weather_forecasts.c.id,
        )
    ).all()
    return [domain.WeatherForecast.model_validate(row._mapping) for row in rows]


def get_circuit_stats(
    conn: Connection, circuit_id: str, season: int
) -> domain.CircuitStats | None:
    """Fetch the stats row for a circuit in a given season, or None."""
    row = conn.execute(
        select(schema.circuit_stats).where(
            schema.circuit_stats.c.circuit_id == circuit_id,
            schema.circuit_stats.c.season == season,
        )
    ).first()
    return domain.CircuitStats.model_validate(row._mapping) if row else None


def get_circuit_race_stats(
    conn: Connection, circuit_id: str, season: int
) -> domain.CircuitRaceStats | None:
    """The empirical race-analytics blob for a circuit in a given season, or None."""
    row = conn.execute(
        select(schema.circuit_race_stats).where(
            schema.circuit_race_stats.c.circuit_id == circuit_id,
            schema.circuit_race_stats.c.season == season,
        )
    ).first()
    return domain.CircuitRaceStats.model_validate(row._mapping) if row else None


def get_sim_race_stats(
    conn: Connection, season: int, round_number: int
) -> domain.SimRaceStats | None:
    """The race-context stats blob from the latest sim run for a weekend, or None.

    One row per weekend; `phase` says whether it came from the prelim or postquali run.
    The blob's `race_stats` is enriched at read time with `strategy_flexibility` and
    `chaos` — this weekend's flexibility and chaos ranks across the season's simulated
    circuits (see `strategy_flexibility_rank` / `chaos_rank`) — since those numbers are
    relative to the rest of the calendar and so can't be baked in when a single weekend
    is simulated.
    """
    rw = get_race_weekend(conn, season, round_number)
    if rw is None:
        return None
    row = conn.execute(
        select(schema.sim_race_stats).where(
            schema.sim_race_stats.c.race_weekend_id == rw.id
        )
    ).first()
    if row is None:
        return None
    stats = domain.SimRaceStats.model_validate(row._mapping)
    flex = strategy_flexibility_rank(conn, season, round_number)
    chaos = chaos_rank(conn, season, round_number)
    race_stats = stats.stats.get("race_stats") if isinstance(stats.stats, dict) else None
    if isinstance(race_stats, dict):
        if flex is not None:
            race_stats["strategy_flexibility"] = flex
        if chaos is not None:
            race_stats["chaos"] = chaos
    return stats


def strategy_flexibility_rank(
    conn: Connection, season: int, round_number: int
) -> dict | None:
    """Where this weekend's strategic flexibility ranks among the season's simulated
    weekends (rank 1 = most flexible), as `{"score", "rank", "of"}`; None when the weekend
    has no sim on record or the field can't be scored.

    Flexibility blends how spread the stop-count distribution (from each weekend's
    `sim_race_stats` blob) and the shown-strategy plausibilities (from its `source="sim"`
    strategies) are — see `formation_data.flexibility`. Ranked at read time over whatever
    circuits are currently simulated, so the value tracks the live calendar the same way
    the degradation rank tracks all known circuit profiles.
    """
    rw = schema.race_weekends
    srs = schema.sim_race_stats
    stat_rows = conn.execute(
        select(rw.c.id, rw.c.round_number, srs.c.stats)
        .join(srs, srs.c.race_weekend_id == rw.c.id)
        .where(rw.c.season == season)
    ).all()
    if not stat_rows:
        return None

    st = schema.strategies
    plaus_by_weekend: dict[int, list[float]] = {}
    for wid, plausibility in conn.execute(
        select(st.c.race_weekend_id, st.c.plausibility).where(
            st.c.race_weekend_id.in_([r.id for r in stat_rows]),
            st.c.source == "sim",
            st.c.plausibility.is_not(None),
        )
    ).all():
        plaus_by_weekend.setdefault(wid, []).append(float(plausibility))

    scores: dict[int, float] = {}
    target_id: int | None = None
    for r in stat_rows:
        if r.round_number == round_number:
            target_id = r.id
        race_stats = (r.stats or {}).get("race_stats") or {}
        score = flexibility.flexibility_score(
            race_stats.get("stop_count_distribution"),
            plaus_by_weekend.get(r.id, []),
        )
        if score is not None:
            scores[r.id] = score

    if target_id is None or target_id not in scores:
        return None
    return flexibility.rank_of(scores[target_id], scores.values())


def chaos_rank(conn: Connection, season: int, round_number: int) -> dict | None:
    """Where this weekend's chaos index ranks among the season's simulated weekends
    (rank 1 = most chaotic), as `{"score", "rank", "of"}`; None when the weekend has no
    sim on record or no chaos index was scored.

    The raw `chaos_index_0to100` is baked into each weekend's `sim_race_stats` blob, but
    it's an absolute figure — this ranks it across whatever circuits are currently
    simulated, mirroring `strategy_flexibility_rank` so chaos tracks the live calendar
    the same way flexibility does.
    """
    rw = schema.race_weekends
    srs = schema.sim_race_stats
    stat_rows = conn.execute(
        select(rw.c.round_number, srs.c.stats)
        .join(srs, srs.c.race_weekend_id == rw.c.id)
        .where(rw.c.season == season)
    ).all()
    if not stat_rows:
        return None

    scores: dict[int, float] = {}
    target_score: float | None = None
    for r in stat_rows:
        race_stats = (r.stats or {}).get("race_stats") or {}
        chaos = race_stats.get("chaos_index_0to100")
        if chaos is None:
            continue
        scores[r.round_number] = float(chaos)
        if r.round_number == round_number:
            target_score = float(chaos)

    if target_score is None:
        return None
    return flexibility.rank_of(target_score, scores.values())
