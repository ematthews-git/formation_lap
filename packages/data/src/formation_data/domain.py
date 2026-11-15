"""Domain models.

Pydantic v2. Same types serve as repository return values, seed inputs, and
FastAPI response models. `from_attributes=True` lets them construct from SQLAlchemy
`Row._mapping` objects.

Auto-generated id columns default to None so the same model represents both
"about to insert" and "fetched" states.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class _Base(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Circuit(_Base):
    circuit_id: str
    country: str
    track_length_km: float
    num_corners: int
    num_laps: int
    sm_zones: int
    jolpica_id: str
    fastf1_location: str
    lat: float
    lon: float
    timezone: str  # IANA zone; session days and clocks are the circuit's local ones
    # First season of the *current* track layout. Used to scope the lap-record
    # search so laps set on a superseded configuration (e.g. Silverstone pre-2010)
    # aren't counted. None = layout stable across all available data.
    layout_since_year: int | None = None
    # SVG path (viewBox 0 0 400 248) of the circuit outline; None until generated
    # by jobs.pre_season.track_maps.
    track_outline: str | None = None


class LapRecord(_Base):
    """A circuit's race lap record. The holder's names are read from `drivers` and
    ignored on write."""

    id: int | None = None
    circuit_id: str
    driver_id: str
    given_name: str
    family_name: str
    year: int
    lap_time_seconds: float


class Team(_Base):
    """A team's lineage across rebrands; `team_id` also names its colour token."""

    team_id: str
    name: str


class TeamSeason(_Base):
    """What a team was called in one season, and each source's key for it then."""

    team_id: str
    season: int
    name: str
    jolpica_id: str
    fastf1_name: str | None = None


class Driver(_Base):
    """One person. `driver_id` is Jolpica's driverId."""

    driver_id: str
    given_name: str
    family_name: str
    code: str | None = None
    nationality: str | None = None


class Seat(_Base):
    """A driver's entry for a team, from `valid_from` until `valid_to` (None = the end of
    the season)."""

    driver_id: str
    team_id: str
    season: int
    valid_from: date
    valid_to: date | None = None


class GridDriver(_Base):
    """A driver on a season's grid with the seat they hold — API read shape."""

    driver_id: str
    given_name: str
    family_name: str
    full_name: str
    code: str | None = None
    nationality: str | None = None
    team_id: str
    team: str
    season: int


class RaceWeekend(_Base):
    id: int | None = None
    circuit_id: str
    season: int
    round_number: int
    event_name: str
    race_date: date
    is_sprint: bool
    # None when a past season has no Pirelli nomination on file (see schema.race_weekends).
    soft_compound: str | None = None
    medium_compound: str | None = None
    hard_compound: str | None = None


class Session(_Base):
    id: int | None = None
    race_weekend_id: int
    kind: str  # schema.SESSION_KINDS: fp1 .. race
    session_order: int
    name: str
    # UTC instant; consumers convert to circuit-local / viewer-local time.
    start_time: datetime


class SessionFinisher(_Base):
    """One top-3 slot in a completed session (driver code only)."""

    position: int
    driver_id: str


class SessionWithResults(_Base):
    """A session plus its top-3 finishers — API read shape (Session + a results summary).

    `top_finishers` is empty until the session's results have been saved (see
    jobs.post_session.session_results); the frontend shows it inline after the name.
    """

    id: int | None = None
    race_weekend_id: int
    kind: str
    session_order: int
    name: str
    start_time: datetime
    top_finishers: list[SessionFinisher] = []


class WeatherForecast(_Base):
    """One day's forecast for a race weekend, the day being the circuit's local one."""

    id: int | None = None
    race_weekend_id: int
    forecast_date: date
    condition: str  # schema.WEATHER_CONDITIONS
    temp_high_c: float
    temp_low_c: float
    rain_probability: int
    wind_speed_kph: float
    updated_at: datetime | None = None


class SessionWeather(_Base):
    """A session with the forecast for its local day — API read shape."""

    session_kind: str
    session_name: str
    start_time: datetime
    forecast_date: date
    condition: str
    temp_high_c: float
    temp_low_c: float
    rain_probability: int
    wind_speed_kph: float
    updated_at: datetime | None = None


class StrategyRun(_Base):
    """One generation of a weekend's strategies. Every run is kept; the latest per
    (race_weekend_id, source) is the one shown (the current_strategy_runs view)."""

    id: int | None = None
    race_weekend_id: int
    # "historical" (mined from the last dry running) or "sim" (simulated).
    source: str
    # Sim only: "prelim" | "postquali". None for historical.
    phase: str | None = None
    # Sim only: the race-context blob (meta, circuit_profile, race_stats).
    stats: dict | None = None
    generated_at: datetime | None = None


class Strategy(_Base):
    id: int | None = None
    run_id: int | None = None  # set when the run is stored
    is_base: bool
    num_stops: int
    label: str
    # Sim only: field-plausibility share and coarse tier. None for historical.
    plausibility: float | None = None
    tier: str | None = None


class StrategyStint(_Base):
    id: int | None = None
    strategy_id: int
    stint_order: int
    compound: str
    pit_lap_window_start: int
    pit_lap_window_end: int


class StrategyWithStints(_Base):
    """A strategy plus its ordered stints and the run it came from — API read shape."""

    id: int | None = None
    run_id: int
    race_weekend_id: int
    source: str
    phase: str | None = None
    is_base: bool
    num_stops: int
    label: str
    plausibility: float | None = None
    tier: str | None = None
    generated_at: datetime
    stints: list[StrategyStint] = []


class SimRaceStats(_Base):
    """Race-context numbers from a sim run (its `stats` blob), API read shape. `id` is
    the run's id."""

    id: int | None = None
    race_weekend_id: int
    phase: str
    generated_at: datetime | None = None
    stats: dict


class CircuitRaceStats(_Base):
    """Empirical per-circuit race analytics over a trailing window (the JSONB `stats` blob).

    API read shape. Computed from every race (wet included) in the last few seasons — the
    observed-history counterpart to the sim's dry-only context numbers. Keyed (circuit_id,
    season); `stats` groups the feed (incidents, grid/finish, tyres, weather, timing …).
    """

    id: int | None = None
    circuit_id: str
    season: int
    updated_at: datetime | None = None
    stats: dict


class SessionResults(_Base):
    """One session's ordered per-driver classification (the JSONB `results` blob).

    API read shape. `results` is an ordered list of per-driver dicts whose keys vary
    by session type (see jobs.post_session.session_results for the normalized shape).
    """

    id: int | None = None
    session_id: int
    updated_at: datetime | None = None
    results: list[dict]


class RaceTrace(_Base):
    """Lap-by-lap trace of one historical race (the JSONB `trace` blob), API read shape.

    `trace` carries per-lap track-status / weather / excitement / overtakes arrays plus
    every starter's lap times, pit laps and the team they drove for in that race (a
    snapshot, so lookbacks never show a driver's current team). Built by
    formation_data.race_trace; each driver's `team_id` is added on read from the FastF1
    team name it was built with (see repositories.list_race_traces_for_circuit). One per race weekend; `circuit_id`, `season` and
    `round_number` are read from the weekend.
    """

    id: int | None = None
    race_weekend_id: int
    circuit_id: str
    season: int
    round_number: int
    updated_at: datetime | None = None
    trace: dict


class RaceOvertakes(_Base):
    """Every change of on-track order in one race (the JSONB `overtakes` blob).

    `overtakes` carries `totals` (`racing` — the headline count of genuine racing passes —
    plus a broadcast-comparable `gross` and the full per-kind breakdown), a per-lap array
    of racing passes, a per-corner histogram, and the individual `events` with the two
    drivers, the lap, the corner and why the position changed. Built by
    formation_data.overtakes. One per race weekend; `circuit_id`, `season` and
    `round_number` are read from the weekend.
    """

    id: int | None = None
    race_weekend_id: int
    circuit_id: str
    season: int
    round_number: int
    updated_at: datetime | None = None
    overtakes: dict


class RaceResult(_Base):
    """One finishing position, stored as (race_weekend_id, position, driver_id, team_id).

    The rest is joined in on read and ignored on write: `circuit_id`, `season` and
    `round_number` from the weekend, the driver's names from `drivers`, and `team`, the
    team's name that season, from `team_seasons`.
    """

    id: int | None = None
    race_weekend_id: int
    circuit_id: str
    season: int
    round_number: int
    position: int
    driver_id: str
    given_name: str
    family_name: str
    code: str | None = None
    team_id: str
    team: str


class DriverStanding(_Base):
    race_weekend_id: int
    driver_id: str
    position: int
    points: float


class ConstructorStanding(_Base):
    race_weekend_id: int
    team_id: str
    position: int
    points: float


class Standing(_Base):
    """One championship position after a race — API read shape for both championships.

    `name` is the driver's full name or the team's name that season. `driver_id` is set
    for the drivers' championship and `team_id` for the constructors'.
    """

    race_weekend_id: int
    season: int
    after_round: int
    type: str  # "driver" | "constructor"
    position: int
    name: str
    points: float
    driver_id: str | None = None
    team_id: str | None = None


class DerivedArtifact(_Base):
    """One per-race derived table serialized to bytes (Parquet), keyed (kind, season, round).

    Lets the sim read cleaned laps from the DB instead of local pkl / live FastF1 in CI.
    `data` is the DataFrame serialized in `data_format`.
    """

    id: int | None = None
    kind: str
    season: int
    round_number: int
    data: bytes
    data_format: str = "parquet"
    updated_at: datetime | None = None


__all__ = [
    "Circuit",
    "LapRecord",
    "Team",
    "TeamSeason",
    "Driver",
    "Seat",
    "GridDriver",
    "RaceWeekend",
    "Session",
    "SessionFinisher",
    "SessionWithResults",
    "WeatherForecast",
    "SessionWeather",
    "Strategy",
    "StrategyStint",
    "StrategyRun",
    "StrategyWithStints",
    "SimRaceStats",
    "CircuitRaceStats",
    "SessionResults",
    "RaceTrace",
    "RaceOvertakes",
    "RaceResult",
    "DriverStanding",
    "ConstructorStanding",
    "Standing",
    "DerivedArtifact",
]
