"""Race weekends: lookups by key, date windows, and placing a source's race."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import Connection, select

from formation_data import domain, schema


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
