"""What the orchestrator's catch-up flows still have to do: results, FastF1 data,
postquali sims and session results that are due but not yet stored."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import Connection, and_, exists, select

from formation_data import domain, schema


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
