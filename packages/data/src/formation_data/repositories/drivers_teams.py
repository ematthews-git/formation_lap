"""Drivers, teams and seats, and matching a source's driver or team to ours."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from sqlalchemy import Connection, and_, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert

from formation_data import domain, schema


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
