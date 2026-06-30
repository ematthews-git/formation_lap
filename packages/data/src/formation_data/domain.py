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
    pit_loss_normal: float
    pit_loss_sc: float
    pit_loss_vsc: float
    undercut_strength: float
    overcut_strength: float
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
    is_base: bool
    num_stops: int
    label: str
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
    is_base: bool
    num_stops: int
    label: str
    updated_at: datetime | None = None
    stints: list[StrategyStint] = []


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
    "WeatherForecast",
    "Strategy",
    "StrategyStint",
    "StrategyWithStints",
    "RaceResult",
    "Standing",
]
