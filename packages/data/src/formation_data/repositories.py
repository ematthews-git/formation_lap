"""Repository layer — generic upsert + table-specific reads.

Every job writes rows the same way: build a list of domain models, then upsert
keyed on a unique constraint. The single `upsert()` helper covers most tables;
`upsert_drivers` and `replace_standings` add the two rules it can't express.

Reads with real logic (filter by date, lookup by composite key) get their own
small functions below — there are only a handful, so keeping them here beats
spreading them across per-table modules.

The one bundled write is `insert_strategy_run`, because a run's and each strategy's
auto-id have to land before the rows beneath them can be inserted.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from sqlalchemy import Connection, Table, and_, delete, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert

from formation_data import domain, flexibility, schema

logger = logging.getLogger(__name__)

# A postquali sim becomes due this many minutes after the Qualifying session *starts*
# (≈1h session + 1h30 buffer for FastF1's delayed data upload).
POSTQUALI_DELAY_MIN = 150

# Session results become due this many minutes after a session *ends*. Sessions store
# only a start time, so the end is estimated as start + SESSION_DURATION_MIN[kind].
SESSION_RESULT_DELAY_MIN = 45
# Estimated running length per session kind. Only used to place the "results due" cutoff;
# red-flag overruns are absorbed by the idempotent retry (a not-yet-available session just
# lands on a later poll).
SESSION_DURATION_MIN = {
    "fp1": 60,
    "fp2": 60,
    "fp3": 60,
    "quali": 60,
    "sprint_quali": 45,
    "sprint": 60,
    "race": 120,
}
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

    Model fields that aren't columns of `table` are dropped: some read models carry
    fields joined in from another table (a RaceResult's season and round come from
    its race weekend), and those are never written here.
    """
    columns = set(table.c.keys())
    payload = [
        {
            k: v
            for k, v in item.model_dump(exclude={"id"} | _SERVER_MANAGED_COLS).items()
            if k in columns
        }
        for item in items
    ]
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


def insert_strategy_run(
    conn: Connection,
    run: domain.StrategyRun,
    strategies: list[tuple[domain.Strategy, list[domain.StrategyStint]]],
) -> int:
    """Store one generation of a weekend's strategies, each with its stints, as a new run.

    Earlier runs are kept; the current_strategy_runs view decides which one is shown.
    Returns the new run's id.
    """
    run_id = conn.execute(
        insert(schema.strategy_runs)
        .values(run.model_dump(exclude={"id"}, exclude_none=True))
        .returning(schema.strategy_runs.c.id)
    ).scalar_one()
    for strategy, stints in strategies:
        strategy_id = conn.execute(
            insert(schema.strategies)
            .values(strategy.model_dump(exclude={"id", "run_id"}) | {"run_id": run_id})
            .returning(schema.strategies.c.id)
        ).scalar_one()
        if stints:
            conn.execute(
                insert(schema.strategy_stints),
                [s.model_dump(exclude={"id"}) | {"strategy_id": strategy_id} for s in stints],
            )
    return run_id


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


def upsert_race_trace(conn: Connection, race_weekend_id: int, trace: dict) -> None:
    """Upsert one race's lap-by-lap trace blob (one row per race weekend).

    Re-running for the same race replaces the blob — it's recomputed wholesale from the
    FastF1 session, so there's nothing to merge.
    """
    stmt = insert(schema.race_traces).values(race_weekend_id=race_weekend_id, trace=trace)
    stmt = stmt.on_conflict_do_update(
        index_elements=["race_weekend_id"],
        set_={"trace": stmt.excluded.trace, "updated_at": func.now()},
    )
    conn.execute(stmt)


def upsert_race_overtakes(conn: Connection, race_weekend_id: int, overtakes: dict) -> None:
    """Upsert one race's classified overtake blob (one row per race weekend).

    Re-running replaces the blob wholesale — it is recomputed from the FastF1 session, so
    there is nothing to merge.
    """
    stmt = insert(schema.race_overtakes).values(
        race_weekend_id=race_weekend_id, overtakes=overtakes
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["race_weekend_id"],
        set_={"overtakes": stmt.excluded.overtakes, "updated_at": func.now()},
    )
    conn.execute(stmt)


def upsert_derived_artifact(
    conn: Connection,
    *,
    kind: str,
    season: int,
    round_number: int,
    data: bytes,
    data_format: str = "parquet",
) -> None:
    """Upsert one serialized per-race derived table (one row per kind+season+round).

    Re-dumping a race replaces its blob — the frame is regenerated wholesale, nothing to merge.
    """
    stmt = insert(schema.derived_artifacts).values(
        kind=kind,
        season=season,
        round_number=round_number,
        data=data,
        data_format=data_format,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["kind", "season", "round_number"],
        set_={
            "data": stmt.excluded.data,
            "data_format": stmt.excluded.data_format,
            "updated_at": func.now(),
        },
    )
    conn.execute(stmt)


def get_derived_artifact(
    conn: Connection, *, kind: str, season: int, round_number: int
) -> domain.DerivedArtifact | None:
    """The serialized derived table for (kind, season, round), or None if not stored."""
    row = conn.execute(
        select(schema.derived_artifacts).where(
            schema.derived_artifacts.c.kind == kind,
            schema.derived_artifacts.c.season == season,
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


def upsert_drivers(conn: Connection, drivers: Iterable[domain.Driver]) -> None:
    """Add or update people, keyed on driver_id (Jolpica's driverId).

    A missing code or nationality never blanks a stored one: Jolpica omits both for some
    drivers it lists, so a later payload without them keeps what's already known.
    """
    payload = {d.driver_id: d.model_dump() for d in drivers}  # a race lists each once
    if not payload:
        return
    table = schema.drivers
    stmt = insert(table).values(list(payload.values()))
    conn.execute(
        stmt.on_conflict_do_update(
            index_elements=["driver_id"],
            set_={
                "given_name": stmt.excluded.given_name,
                "family_name": stmt.excluded.family_name,
                "code": func.coalesce(stmt.excluded.code, table.c.code),
                "nationality": func.coalesce(stmt.excluded.nationality, table.c.nationality),
            },
        )
    )


def replace_standings(
    conn: Connection,
    race_weekend_id: int,
    drivers: list[domain.DriverStanding],
    constructors: list[domain.ConstructorStanding],
) -> None:
    """Store the standings after one race, replacing whatever that race had before, so a
    driver dropped from a corrected table doesn't linger."""
    for table, items, key in (
        (schema.driver_standings, drivers, "driver_id"),
        (schema.constructor_standings, constructors, "team_id"),
    ):
        conn.execute(delete(table).where(table.c.race_weekend_id == race_weekend_id))
        upsert(conn, table, items, ["race_weekend_id", key])


# --- read ---


class TeamNotFound(LookupError):
    """A source named a team that isn't in team_seasons for that season."""


class DriverNotFound(LookupError):
    """A source named a driver that can't be matched to exactly one person."""


def team_for_jolpica(conn: Connection, season: int, constructor_id: str) -> domain.TeamSeason:
    """The team Jolpica's constructorId means in `season`.

    Raises TeamNotFound when the teams seed has no such row: a new team, a rebrand, or a
    season whose teams haven't been added yet."""
    ts = schema.team_seasons
    row = conn.execute(
        select(ts).where(ts.c.season == season, ts.c.jolpica_id == constructor_id)
    ).first()
    if row is None:
        raise TeamNotFound(
            f"Jolpica's constructor {constructor_id!r} isn't a {season} team on file. Add "
            f"it to TEAM_SEASONS in formation_data/jobs/static/teams.py and run "
            "`formation-data teams seed`."
        )
    return domain.TeamSeason.model_validate(row._mapping)


def fastf1_team_ids(conn: Connection, seasons: Iterable[int]) -> dict[tuple[int, str], str]:
    """(season, FastF1 TeamName) -> team_id for the given seasons."""
    ts = schema.team_seasons
    rows = conn.execute(
        select(ts.c.season, ts.c.fastf1_name, ts.c.team_id).where(
            ts.c.season.in_(set(seasons)), ts.c.fastf1_name.is_not(None)
        )
    ).all()
    return {(r.season, r.fastf1_name): r.team_id for r in rows}


def require_fastf1_teams(conn: Connection, season: int, names: Iterable[str]) -> None:
    """Raise TeamNotFound unless every FastF1 team name is on file for `season`."""
    known = fastf1_team_ids(conn, [season])
    missing = sorted({n for n in names if (season, n) not in known})
    if missing:
        raise TeamNotFound(
            f"FastF1 names {season} teams that aren't on file: {', '.join(missing)}. Set "
            "their fastf1_name in formation_data/jobs/static/teams.py and run "
            "`formation-data teams seed`."
        )


def driver_for_code(conn: Connection, code: str, season: int) -> domain.Driver:
    """The driver FastF1's three-letter code means in `season`.

    Codes are only unique within a season (both Schumachers are MSC), so the match is
    limited to drivers with a race result or a seat that season. Raises DriverNotFound
    when there's no such driver, or more than one."""
    d, rr, rw, st = schema.drivers, schema.race_results, schema.race_weekends, schema.seats
    raced = exists().where(
        rr.c.driver_id == d.c.driver_id, rw.c.id == rr.c.race_weekend_id, rw.c.season == season
    )
    seated = exists().where(st.c.driver_id == d.c.driver_id, st.c.season == season)
    rows = conn.execute(select(d).where(d.c.code == code, raced | seated)).all()
    if len(rows) != 1:
        found = "no driver" if not rows else f"{len(rows)} drivers"
        raise DriverNotFound(
            f"{found} with code {code!r} raced or holds a seat in {season}. Load that "
            "season's results (`formation-data results backfill`) or its grid "
            "(`formation-data drivers seed`) first."
        )
    return domain.Driver.model_validate(rows[0]._mapping)


def _with_weekend(table: Table):
    """SELECT every column of a race-history table plus its weekend's circuit_id, season
    and round_number, which the read models (RaceTrace, RaceOvertakes) carry."""
    rw = schema.race_weekends
    return select(table, rw.c.circuit_id, rw.c.season, rw.c.round_number).join(
        rw, rw.c.id == table.c.race_weekend_id
    )


class RaceWeekendNotFound(LookupError):
    """No race weekend matches a race a source described."""


def resolve_race_weekend(
    conn: Connection, *, season: int, circuit_id: str, round_number: int
) -> domain.RaceWeekend:
    """The weekend a source's race belongs to, for writing race history against.

    Matched on season and circuit, which identify a race; the round (Jolpica's or
    FastF1's official one) is only used to pick between a double-header's two visits.
    Matching on the round alone breaks whenever the stored calendar and the source
    disagree on numbering, e.g. mid-season while a renumber is pending.

    Raises RaceWeekendNotFound when the season's calendar doesn't have the race (run
    `weekends refresh` for that season), or when a double-header can't be told apart.
    """
    rw = schema.race_weekends
    rows = conn.execute(
        select(rw)
        .where(rw.c.season == season, rw.c.circuit_id == circuit_id)
        .order_by(rw.c.round_number)
    ).all()
    weekends = [domain.RaceWeekend.model_validate(r._mapping) for r in rows]
    exact = [w for w in weekends if w.round_number == round_number]
    if exact:
        return exact[0]
    if len(weekends) == 1:
        return weekends[0]
    if not weekends:
        raise RaceWeekendNotFound(
            f"No race weekend for {circuit_id} in {season}. Load that season's calendar "
            f"with `formation-data weekends refresh --season {season}`."
        )
    raise RaceWeekendNotFound(
        f"{circuit_id} hosts {len(weekends)} races in {season} (rounds "
        f"{', '.join(str(w.round_number) for w in weekends)}) and none is round "
        f"{round_number}, so the race can't be placed. Refresh the {season} calendar."
    )


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


def list_season_grid(
    conn: Connection, season: int, today: date | None = None
) -> list[domain.GridDriver]:
    """The drivers holding a seat in a season, with that seat, ordered by name.

    The grid as of `today`, kept within the season: its last day once it's over, and the
    first seats' start date before it begins. So a mid-season swap shows the seat held
    at the time, and a driver whose seat ended without another is off the grid.
    """
    st, d, ts = schema.seats, schema.drivers, schema.team_seasons
    first = conn.execute(
        select(func.min(st.c.valid_from)).where(st.c.season == season)
    ).scalar()
    if first is None:
        return []
    as_of = max(min(today or date.today(), date(season, 12, 31)), first)
    rows = conn.execute(
        select(
            d,
            (d.c.given_name + " " + d.c.family_name).label("full_name"),
            st.c.team_id,
            ts.c.name.label("team"),
            st.c.season,
        )
        .join(st, st.c.driver_id == d.c.driver_id)
        .join(ts, and_(ts.c.team_id == st.c.team_id, ts.c.season == st.c.season))
        .where(
            st.c.season == season,
            st.c.valid_from <= as_of,
            or_(st.c.valid_to.is_(None), st.c.valid_to > as_of),
        )
        .order_by(d.c.given_name, d.c.family_name)
    ).all()
    return [domain.GridDriver.model_validate(row._mapping) for row in rows]


def list_standings(
    conn: Connection,
    season: int,
    type: str,
    after_round: int | None = None,
) -> list[domain.Standing]:
    """Championship standings for a season and type ("driver"/"constructor").

    When `after_round` is omitted, returns the standings after the latest race that has
    them. Results are ordered by championship position.
    """
    rw = schema.race_weekends
    if type == "driver":
        table, d = schema.driver_standings, schema.drivers
        cols = (
            (d.c.given_name + " " + d.c.family_name).label("name"),
            table.c.driver_id,
        )
        joined = table.join(rw, rw.c.id == table.c.race_weekend_id).join(
            d, d.c.driver_id == table.c.driver_id
        )
    else:
        table, ts = schema.constructor_standings, schema.team_seasons
        cols = (ts.c.name, table.c.team_id)
        joined = table.join(rw, rw.c.id == table.c.race_weekend_id).join(
            ts, and_(ts.c.team_id == table.c.team_id, ts.c.season == rw.c.season)
        )
    if after_round is None:
        after_round = conn.execute(
            select(func.max(rw.c.round_number))
            .select_from(table.join(rw, rw.c.id == table.c.race_weekend_id))
            .where(rw.c.season == season)
        ).scalar()
        if after_round is None:
            return []
    rows = conn.execute(
        select(
            table.c.race_weekend_id,
            rw.c.season,
            rw.c.round_number.label("after_round"),
            table.c.position,
            table.c.points,
            *cols,
        )
        .select_from(joined)
        .where(rw.c.season == season, rw.c.round_number == after_round)
        .order_by(table.c.position)
    ).all()
    return [domain.Standing.model_validate({**row._mapping, "type": type}) for row in rows]


def _race_results_with_names():
    """SELECT race results with the weekend's circuit, season and round, the driver's
    names, and the team's name that season — the RaceResult read shape."""
    rr, rw, d, ts = (
        schema.race_results,
        schema.race_weekends,
        schema.drivers,
        schema.team_seasons,
    )
    return (
        select(
            rr,
            rw.c.circuit_id,
            rw.c.season,
            rw.c.round_number,
            d.c.given_name,
            d.c.family_name,
            d.c.code,
            ts.c.name.label("team"),
        )
        .join(rw, rw.c.id == rr.c.race_weekend_id)
        .join(d, d.c.driver_id == rr.c.driver_id)
        .join(ts, and_(ts.c.team_id == rr.c.team_id, ts.c.season == rw.c.season))
    )


def list_circuit_podiums(
    conn: Connection, circuit_id: str, limit: int = 5
) -> list[domain.RaceResult]:
    """Top-3 finishers for the most recent `limit` races at a circuit.

    Rows are ordered most-recent race first, then finishing position; the caller
    groups consecutive rows sharing (season, round_number) into one race. Returns
    fewer than `limit` races (or `[]`) when the circuit lacks that much history.
    """
    rr, rw = schema.race_results, schema.race_weekends
    weekend_ids = (
        conn.execute(
            select(rw.c.id)
            .where(
                rw.c.circuit_id == circuit_id,
                exists().where(rr.c.race_weekend_id == rw.c.id),
            )
            .order_by(rw.c.season.desc(), rw.c.round_number.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    if not weekend_ids:
        return []
    rows = conn.execute(
        _race_results_with_names()
        .where(rr.c.race_weekend_id.in_(weekend_ids), rr.c.position <= 3)
        .order_by(rw.c.season.desc(), rw.c.round_number.desc(), rr.c.position.asc())
    ).all()
    return [domain.RaceResult.model_validate(row._mapping) for row in rows]


def list_race_results(conn: Connection, season: int) -> list[domain.RaceResult]:
    """All race results for a season, ordered by round then finishing position."""
    rr, rw = schema.race_results, schema.race_weekends
    rows = conn.execute(
        _race_results_with_names()
        .where(rw.c.season == season)
        .order_by(rw.c.round_number, rr.c.position)
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
    """
    rw = schema.race_weekends
    rr = schema.race_results
    has_results = exists().where(rr.c.race_weekend_id == rw.c.id)
    rows = conn.execute(
        select(rw)
        .where(rw.c.race_date < before, ~has_results)
        .order_by(rw.c.race_date.asc())
    ).all()
    return [domain.RaceWeekend.model_validate(row._mapping) for row in rows]


def races_missing_fastf1_data(conn: Connection, season: int) -> list[tuple[int, int, str]]:
    """`(season, round_number, circuit_id)` of `season`'s races that have results but
    are still missing a race trace or a stored laps frame. Ordered by round.

    These are the FastF1-derived pieces of the post-race flow. Results come from Jolpica
    and can land while FastF1 is still unpublished, rate-limited or signed out, so
    the flow keys its FastF1 catch-up on what's missing rather than on which weekends
    got results this run. The round is the weekend's, which calendar_sync keeps equal
    to FastF1's; the laps check goes through it because derived_artifacts is keyed the
    way FastF1 keys races.
    """
    rw, rr = schema.race_weekends, schema.race_results
    rt, da = schema.race_traces, schema.derived_artifacts
    has_results = exists().where(rr.c.race_weekend_id == rw.c.id)
    has_trace = exists().where(rt.c.race_weekend_id == rw.c.id)
    has_laps = exists().where(
        da.c.kind == "laps",
        da.c.season == rw.c.season,
        da.c.round_number == rw.c.round_number,
    )
    rows = conn.execute(
        select(rw.c.season, rw.c.round_number, rw.c.circuit_id)
        .where(rw.c.season == season, has_results, ~(has_trace & has_laps))
        .order_by(rw.c.round_number)
    ).all()
    return [(int(s), int(r), str(c)) for s, r, c in rows]


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
    and the weekend has no postquali sim run. `now` must be timezone-aware (UTC),
    to compare against the timestamptz session start times. Drives the idempotent
    catch-up flow: safe to call repeatedly — a weekend drops out once its postquali runs.
    """
    cutoff = now - timedelta(minutes=POSTQUALI_DELAY_MIN)
    rw = schema.race_weekends
    quali = schema.sessions.alias("quali")
    race = schema.sessions.alias("race")
    runs = schema.strategy_runs
    postquali_done = exists().where(
        runs.c.race_weekend_id == rw.c.id,
        runs.c.source == "sim",
        runs.c.phase == "postquali",
    )
    rows = conn.execute(
        select(rw)
        .join(quali, and_(quali.c.race_weekend_id == rw.c.id, quali.c.kind == "quali"))
        .join(race, and_(race.c.race_weekend_id == rw.c.id, race.c.kind == "race"))
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


def results_due_at(kind: str, start_time: datetime) -> datetime:
    """The instant a session's results become due to save.

    Estimated as start + running length (SESSION_DURATION_MIN[kind]) +
    SESSION_RESULT_DELAY_MIN, since sessions store only a start time.
    """
    duration = SESSION_DURATION_MIN[kind]
    return start_time + timedelta(minutes=duration + SESSION_RESULT_DELAY_MIN)


def session_results_due(conn: Connection, now: datetime) -> list[domain.Session]:
    """Sessions whose results are due to be saved but haven't been yet.

    Due = `results_due_at(kind, start) <= now` and no session_results row exists yet.
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
        if results_due_at(sess.kind, sess.start_time) <= now:
            due.append(sess)
    return due


def get_lap_record_for_circuit(
    conn: Connection, circuit_id: str
) -> domain.LapRecord | None:
    """Fetch the lap record for a circuit, with the holder's names, or None if not set."""
    lr, d = schema.lap_records, schema.drivers
    row = conn.execute(
        select(lr, d.c.given_name, d.c.family_name)
        .join(d, d.c.driver_id == lr.c.driver_id)
        .where(lr.c.circuit_id == circuit_id)
    ).first()
    return domain.LapRecord.model_validate(row._mapping) if row else None


def list_strategies_for_weekend(
    conn: Connection, season: int, round_number: int, source: str | None = None
) -> list[domain.StrategyWithStints]:
    """The strategies (each with its ordered stints) from a weekend's current run.

    The current run is the latest per source (current_strategy_runs), so a postquali sim
    replaces prelim here while both stay stored. Pass `source` ("historical" / "sim") to
    scope to one; without it, both sources' current runs are returned, base strategy
    first, then by stop count. Returns `[]` when the weekend doesn't exist or has no run.
    """
    rw = get_race_weekend(conn, season, round_number)
    if rw is None:
        return []

    run, st = schema.current_strategy_runs, schema.strategies
    cond = [run.c.race_weekend_id == rw.id]
    if source is not None:
        cond.append(run.c.source == source)
    strat_rows = conn.execute(
        select(st, run.c.race_weekend_id, run.c.source, run.c.phase, run.c.generated_at)
        .join(run, run.c.id == st.c.run_id)
        .where(*cond)
        .order_by(run.c.source, st.c.is_base.desc(), st.c.num_stops, st.c.label)
    ).all()
    if not strat_rows:
        return []

    stint_rows = conn.execute(
        select(schema.strategy_stints)
        .where(schema.strategy_stints.c.strategy_id.in_([row.id for row in strat_rows]))
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


def list_race_traces_for_circuit(
    conn: Connection, circuit_id: str, limit: int = 5
) -> list[domain.RaceTrace]:
    """The most recent race traces for a circuit, newest first.

    Each driver in a trace carries the FastF1 team name it was built with; `team_id` is
    added here from team_seasons (None for a name that isn't on file), so the frontend
    colours by team without matching names.
    """
    rw = schema.race_weekends
    rows = conn.execute(
        _with_weekend(schema.race_traces)
        .where(rw.c.circuit_id == circuit_id)
        .order_by(rw.c.season.desc(), rw.c.round_number.desc())
        .limit(limit)
    ).all()
    traces = [domain.RaceTrace.model_validate(row._mapping) for row in rows]
    team_ids = fastf1_team_ids(conn, {t.season for t in traces})
    for t in traces:
        for driver in t.trace.get("drivers") or []:
            driver["team_id"] = team_ids.get((t.season, driver.get("team")))
    return traces


def get_race_overtakes(
    conn: Connection, season: int, round_number: int
) -> domain.RaceOvertakes | None:
    """One race's classified overtake blob, or None."""
    rw = schema.race_weekends
    row = conn.execute(
        _with_weekend(schema.race_overtakes).where(
            rw.c.season == season, rw.c.round_number == round_number
        )
    ).first()
    return domain.RaceOvertakes.model_validate(row._mapping) if row else None


def list_race_overtakes_for_circuit(
    conn: Connection, circuit_id: str, limit: int = 5
) -> list[domain.RaceOvertakes]:
    """The most recent overtake blobs for a circuit, newest first."""
    rw = schema.race_weekends
    rows = conn.execute(
        _with_weekend(schema.race_overtakes)
        .where(rw.c.circuit_id == circuit_id)
        .order_by(rw.c.season.desc(), rw.c.round_number.desc())
        .limit(limit)
    ).all()
    return [domain.RaceOvertakes.model_validate(row._mapping) for row in rows]


def calendar_avg_finish_by_grid(conn: Connection, season: int) -> dict[str, float]:
    """Mean finish per grid slot pooled across every circuit's race stats for a season.

    Reads each circuit's ``stats.grid.avg_finish_by_grid`` (itself a per-circuit mean of
    finishes for that grid slot) and averages those across all circuits, giving the
    calendar-wide baseline used as the grey reference on the quali scatterplot. Grid slots
    missing from a circuit simply don't contribute to that slot's average. Returns ``{}``
    when no circuit has race stats for the season.
    """
    rows = conn.execute(
        select(schema.circuit_race_stats.c.stats).where(
            schema.circuit_race_stats.c.season == season
        )
    ).all()
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for (stats,) in rows:
        by_grid = ((stats or {}).get("grid") or {}).get("avg_finish_by_grid") or {}
        for slot, mean_finish in by_grid.items():
            if mean_finish is None:
                continue
            totals[slot] = totals.get(slot, 0.0) + float(mean_finish)
            counts[slot] = counts.get(slot, 0) + 1
    return {slot: round(totals[slot] / counts[slot], 3) for slot in totals}


def get_sim_race_stats(
    conn: Connection, season: int, round_number: int
) -> domain.SimRaceStats | None:
    """The race-context stats blob from a weekend's current sim run, or None.

    `phase` says whether it came from the prelim or postquali run.
    The blob's `race_stats` is enriched at read time with `strategy_flexibility` and
    `chaos` — this weekend's flexibility and chaos ranks across the season's simulated
    circuits (see `strategy_flexibility_rank` / `chaos_rank`) — since those numbers are
    relative to the rest of the calendar and so can't be baked in when a single weekend
    is simulated.
    """
    rw = get_race_weekend(conn, season, round_number)
    if rw is None:
        return None
    run = schema.current_strategy_runs
    row = conn.execute(
        select(run.c.id, run.c.race_weekend_id, run.c.phase, run.c.generated_at, run.c.stats)
        .where(run.c.race_weekend_id == rw.id, run.c.source == "sim")
    ).first()
    if row is None or row.stats is None:
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


def _current_sim_runs(conn: Connection, season: int) -> list:
    """(id, round_number, stats) of the current sim run for each of a season's weekends."""
    run, rw = schema.current_strategy_runs, schema.race_weekends
    return conn.execute(
        select(run.c.id, rw.c.round_number, run.c.stats)
        .join(rw, rw.c.id == run.c.race_weekend_id)
        .where(rw.c.season == season, run.c.source == "sim", run.c.stats.is_not(None))
    ).all()


def strategy_flexibility_rank(
    conn: Connection, season: int, round_number: int
) -> dict | None:
    """Where this weekend's strategic flexibility ranks among the season's simulated
    weekends (rank 1 = most flexible), as `{"score", "rank", "of"}`; None when the weekend
    has no sim on record or the field can't be scored.

    Flexibility blends how spread the stop-count distribution (from each weekend's current
    sim run's stats blob) and the shown-strategy plausibilities (that run's strategies)
    are — see `formation_data.flexibility`. Ranked at read time over whatever
    circuits are currently simulated, so the value tracks the live calendar the same way
    the degradation rank tracks all known circuit profiles.
    """
    stat_rows = _current_sim_runs(conn, season)
    if not stat_rows:
        return None

    st = schema.strategies
    plaus_by_run: dict[int, list[float]] = {}
    for run_id, plausibility in conn.execute(
        select(st.c.run_id, st.c.plausibility).where(
            st.c.run_id.in_([r.id for r in stat_rows]),
            st.c.plausibility.is_not(None),
        )
    ).all():
        plaus_by_run.setdefault(run_id, []).append(float(plausibility))

    scores: dict[int, float] = {}
    target_id: int | None = None
    for r in stat_rows:
        if r.round_number == round_number:
            target_id = r.id
        race_stats = (r.stats or {}).get("race_stats") or {}
        score = flexibility.flexibility_score(
            race_stats.get("stop_count_distribution"),
            plaus_by_run.get(r.id, []),
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

    The raw `chaos_index_0to100` is baked into each sim run's stats blob, but
    it's an absolute figure — this ranks it across whatever circuits are currently
    simulated, mirroring `strategy_flexibility_rank` so chaos tracks the live calendar
    the same way flexibility does.
    """
    stat_rows = _current_sim_runs(conn, season)
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
