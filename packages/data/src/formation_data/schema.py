"""SQLAlchemy Core schema.

Domain types live in `formation_data.domain` (Pydantic). Repositories in
`formation_data.repositories`.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
)

metadata = MetaData()


circuits = Table(
    "circuits",
    metadata,
    Column("circuit_id", String(50), primary_key=True),
    Column("event_name", String, nullable=False),
    Column("country", String, nullable=False),
    Column("track_length_km", Float, nullable=False),
    Column("num_corners", Integer, nullable=False),
    Column("num_laps", Integer, nullable=False),
    Column("sm_zones", Integer, nullable=False),
)


lap_records = Table(
    "lap_records",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "circuit_id", ForeignKey("circuits.circuit_id"), nullable=False, unique=True
    ),
    Column("driver", String, nullable=False),
    Column("year", Integer, nullable=False),
    Column("lap_time_seconds", Float, nullable=False),
)


circuit_stats = Table(
    "circuit_stats",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("circuit_id", ForeignKey("circuits.circuit_id"), nullable=False),
    Column("season", Integer, nullable=False),
    Column("sc_probability", Integer, nullable=False),
    Column("red_flag_probability", Integer, nullable=False),
    Column("pit_loss_normal", Float, nullable=False),
    Column("pit_loss_sc", Float, nullable=False),
    Column("pit_loss_vsc", Float, nullable=False),
    Column("undercut_strength", Float, nullable=False),
    Column("overcut_strength", Float, nullable=False),
    UniqueConstraint("circuit_id", "season"),
)


drivers = Table(
    "drivers",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("driver_id", String(10), nullable=False),
    Column("full_name", String, nullable=False),
    Column("nationality", String, nullable=False),
    Column("team", String, nullable=False),
    Column("season", Integer, nullable=False),
    UniqueConstraint("driver_id", "season"),
)


race_weekends = Table(
    "race_weekends",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("circuit_id", ForeignKey("circuits.circuit_id"), nullable=False),
    Column("season", Integer, nullable=False),
    Column("round_number", Integer, nullable=False),
    Column("race_date", Date, nullable=False),
    Column("is_sprint", Boolean, nullable=False),
    Column("soft_compound", String(5), nullable=False),
    Column("medium_compound", String(5), nullable=False),
    Column("hard_compound", String(5), nullable=False),
    UniqueConstraint("circuit_id", "season"),
)


weather_forecasts = Table(
    "weather_forecasts",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("race_weekend_id", ForeignKey("race_weekends.id"), nullable=False),
    Column("session_name", String, nullable=False),
    Column("session_date", Date, nullable=False),
    Column("condition", String, nullable=False),
    Column("temp_high_c", Float, nullable=False),
    Column("temp_low_c", Float, nullable=False),
    Column("rain_probability", Integer, nullable=False),
    Column("wind_speed_kph", Float, nullable=False),
    UniqueConstraint("race_weekend_id", "session_name"),
)


strategies = Table(
    "strategies",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("race_weekend_id", ForeignKey("race_weekends.id"), nullable=False),
    Column("is_base", Boolean, nullable=False),
    Column("num_stops", Integer, nullable=False),
    Column("label", String, nullable=False),
    UniqueConstraint("race_weekend_id", "label"),
)


strategy_stints = Table(
    "strategy_stints",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("strategy_id", ForeignKey("strategies.id"), nullable=False),
    Column("stint_order", Integer, nullable=False),
    Column("compound", String(15), nullable=False),
    Column("pit_lap_window_start", Integer, nullable=False),
    Column("pit_lap_window_end", Integer, nullable=False),
    UniqueConstraint("strategy_id", "stint_order"),
)


race_results = Table(
    "race_results",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("circuit_id", ForeignKey("circuits.circuit_id"), nullable=False),
    Column("season", Integer, nullable=False),
    Column("position", Integer, nullable=False),
    Column("driver_id", String, nullable=False),
    Column("team", String, nullable=False),
    UniqueConstraint("circuit_id", "season", "position"),
)


standings = Table(
    "standings",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("season", Integer, nullable=False),
    Column("after_round", Integer, nullable=False),
    Column("type", String(15), nullable=False),
    Column("position", Integer, nullable=False),
    Column("name", String, nullable=False),
    Column("points", Float, nullable=False),
    UniqueConstraint("season", "after_round", "type", "position"),
)


__all__ = [
    "metadata",
    "circuits",
    "lap_records",
    "circuit_stats",
    "drivers",
    "race_weekends",
    "weather_forecasts",
    "strategies",
    "strategy_stints",
    "race_results",
    "standings",
]
