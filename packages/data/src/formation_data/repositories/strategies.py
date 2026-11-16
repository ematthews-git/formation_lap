"""Strategy runs: storing a generation, reading the current one, and ranking a
weekend's sim stats against the rest of the season."""

from __future__ import annotations

from sqlalchemy import Connection, select
from sqlalchemy.dialects.postgresql import insert

from formation_data import domain, flexibility, schema
from formation_data.repositories.weekends import get_race_weekend


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
