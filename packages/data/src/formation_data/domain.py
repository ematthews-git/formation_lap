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
    # First season of the *current* track layout. Used to scope the lap-record
    # search so laps set on a superseded configuration (e.g. Silverstone pre-2010)
    # aren't counted. None = layout stable across all available data.
    layout_since_year: int | None = None
    # SVG path (viewBox 0 0 400 248) of the circuit outline; None until generated
    # by jobs.pre_season.track_maps.
    track_outline: str | None = None


class LapRecord(_Base):
    id: int | None = None
    circuit_id: str
    driver: str
    year: int
    lap_time_seconds: float


class CircuitStats(_Base):
    id: int | None = None
    circuit_id: str
    season: int
    sc_probability: int
    red_flag_probability: int
    updated_at: datetime | None = None


class Driver(_Base):
    id: int | None = None
    driver_id: str
    full_name: str
    nationality: str
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
    soft_compound: str
    medium_compound: str
    hard_compound: str


class Session(_Base):
    id: int | None = None
    race_weekend_id: int
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
    session_order: int
    name: str
    start_time: datetime
    top_finishers: list[SessionFinisher] = []


class WeatherForecast(_Base):
    id: int | None = None
    race_weekend_id: int
    session_name: str
    session_date: date
    condition: str
    temp_high_c: float
    temp_low_c: float
    rain_probability: int
    wind_speed_kph: float
    updated_at: datetime | None = None


class Strategy(_Base):
    id: int | None = None
    race_weekend_id: int
    # "historical" (mined) or "sim" (simulated). Defaults keep pre-sim callers valid.
    source: str = "historical"
    # Sim only: "prelim" | "postquali". None for historical.
    phase: str | None = None
    is_base: bool
    num_stops: int
    label: str
    # Sim only: field-plausibility share and coarse tier. None for historical.
    plausibility: float | None = None
    tier: str | None = None
    updated_at: datetime | None = None


class StrategyStint(_Base):
    id: int | None = None
    strategy_id: int
    stint_order: int
    compound: str
    pit_lap_window_start: int
    pit_lap_window_end: int


class StrategyWithStints(_Base):
    """A strategy plus its ordered stints — API read shape (not a seed/upsert type)."""

    id: int | None = None
    race_weekend_id: int
    source: str = "historical"
    phase: str | None = None
    is_base: bool
    num_stops: int
    label: str
    plausibility: float | None = None
    tier: str | None = None
    updated_at: datetime | None = None
    stints: list[StrategyStint] = []


class SimRaceStats(_Base):
    """Race-context numbers from a sim run (the JSONB `stats` blob), API read shape."""

    id: int | None = None
    race_weekend_id: int
    phase: str
    generated_at: datetime | None = None
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


class RaceResult(_Base):
    id: int | None = None
    circuit_id: str
    season: int
    round_number: int
    position: int
    driver_id: str
    team: str


class Standing(_Base):
    id: int | None = None
    season: int
    after_round: int
    type: str
    position: int
    name: str
    points: float


__all__ = [
    "Circuit",
    "LapRecord",
    "CircuitStats",
    "Driver",
    "RaceWeekend",
    "Session",
    "SessionFinisher",
    "SessionWithResults",
    "WeatherForecast",
    "Strategy",
    "StrategyStint",
    "StrategyWithStints",
    "SimRaceStats",
    "SessionResults",
    "RaceResult",
    "Standing",
]
