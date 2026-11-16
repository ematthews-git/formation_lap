"""Repository layer — generic upsert + table-specific reads, one module per topic.

Every job writes rows the same way: build a list of domain models, then upsert keyed
on a unique constraint with `base.upsert`. Tables with a rule it can't express, or a
JSONB blob, get their own write next to their reads. The one bundled write is
`strategies.insert_strategy_run`, because a run's and each strategy's auto-id have to
land before the rows beneath them can be inserted.

    base           the shared upsert
    circuits       circuits, lap records, per-circuit race stats
    weekends       race weekends, and placing a source's race on one
    due            what the orchestrator's catch-up flows still have to do
    drivers_teams  drivers, teams and seats, and matching a source's names to them
    results        race results and standings
    sessions       sessions, their results, and each one's weather
    race_data      per-race FastF1 blobs: traces, overtakes, derived tables
    strategies     strategy runs and the sim stats ranks

Everything public is re-exported here, so callers use `repositories.<name>`.
"""

from formation_data.repositories.base import upsert
from formation_data.repositories.circuits import (
    calendar_avg_finish_by_grid,
    get_circuit,
    get_circuit_race_stats,
    get_lap_record_for_circuit,
    list_circuits,
    upsert_circuit_race_stats,
)
from formation_data.repositories.drivers_teams import (
    DriverNotFound,
    TeamNotFound,
    driver_for_code,
    fastf1_team_ids,
    list_season_grid,
    require_fastf1_teams,
    team_for_jolpica,
    upsert_drivers,
)
from formation_data.repositories.due import (
    POSTQUALI_DELAY_MIN,
    SESSION_DURATION_MIN,
    SESSION_RESULT_DELAY_MIN,
    SESSION_RESULTS_LOOKBACK,
    race_weekends_missing_results,
    races_missing_fastf1_data,
    results_due_at,
    session_results_due,
    weekends_postquali_due,
)
from formation_data.repositories.race_data import (
    get_derived_artifact,
    get_race_overtakes,
    list_race_overtakes_for_circuit,
    list_race_traces_for_circuit,
    upsert_derived_artifact,
    upsert_race_overtakes,
    upsert_race_trace,
)
from formation_data.repositories.results import (
    list_circuit_podiums,
    list_race_results,
    list_standings,
    replace_standings,
)
from formation_data.repositories.sessions import (
    get_session,
    get_session_by_kind,
    list_sessions_for_weekend,
    list_weather_for_weekend,
    upsert_session_results,
)
from formation_data.repositories.strategies import (
    chaos_rank,
    get_sim_race_stats,
    insert_strategy_run,
    list_strategies_for_weekend,
    strategy_flexibility_rank,
)
from formation_data.repositories.weekends import (
    RaceWeekendNotFound,
    get_race_weekend,
    get_race_weekend_by_id,
    list_race_weekends,
    most_recent_race_weekend_before,
    next_race_weekend_after,
    next_race_weekend_within,
    remaining_race_weekends,
    resolve_race_weekend,
)

__all__ = [
    # base
    "upsert",
    # circuits
    "calendar_avg_finish_by_grid",
    "get_circuit",
    "get_circuit_race_stats",
    "get_lap_record_for_circuit",
    "list_circuits",
    "upsert_circuit_race_stats",
    # drivers_teams
    "DriverNotFound",
    "TeamNotFound",
    "driver_for_code",
    "fastf1_team_ids",
    "list_season_grid",
    "require_fastf1_teams",
    "team_for_jolpica",
    "upsert_drivers",
    # due
    "POSTQUALI_DELAY_MIN",
    "SESSION_DURATION_MIN",
    "SESSION_RESULT_DELAY_MIN",
    "SESSION_RESULTS_LOOKBACK",
    "race_weekends_missing_results",
    "races_missing_fastf1_data",
    "results_due_at",
    "session_results_due",
    "weekends_postquali_due",
    # race_data
    "get_derived_artifact",
    "get_race_overtakes",
    "list_race_overtakes_for_circuit",
    "list_race_traces_for_circuit",
    "upsert_derived_artifact",
    "upsert_race_overtakes",
    "upsert_race_trace",
    # results
    "list_circuit_podiums",
    "list_race_results",
    "list_standings",
    "replace_standings",
    # sessions
    "get_session",
    "get_session_by_kind",
    "list_sessions_for_weekend",
    "list_weather_for_weekend",
    "upsert_session_results",
    # strategies
    "chaos_rank",
    "get_sim_race_stats",
    "insert_strategy_run",
    "list_strategies_for_weekend",
    "strategy_flexibility_rank",
    # weekends
    "RaceWeekendNotFound",
    "get_race_weekend",
    "get_race_weekend_by_id",
    "list_race_weekends",
    "most_recent_race_weekend_before",
    "next_race_weekend_after",
    "next_race_weekend_within",
    "remaining_race_weekends",
    "resolve_race_weekend",
]
