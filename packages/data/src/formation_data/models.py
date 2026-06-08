from __future__ import annotations

from datetime import date

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from formation_data.base import Base


class Circuit(Base):
    __tablename__ = "circuits"

    # following filled by seed_circuits
    circuit_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    event_name: Mapped[str]
    country: Mapped[str]
    track_length_km: Mapped[float]
    num_corners: Mapped[int]
    num_laps: Mapped[int]
    sm_zones: Mapped[int]

    # calculated
    lap_record: Mapped[LapRecord | None] = relationship(back_populates="circuit")
    stats: Mapped[list[CircuitStats]] = relationship(back_populates="circuit")
    race_weekends: Mapped[list[RaceWeekend]] = relationship(back_populates="circuit")
    race_results: Mapped[list[RaceResult]] = relationship(back_populates="circuit")


class LapRecord(Base):
    __tablename__ = "lap_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    circuit_id: Mapped[str] = mapped_column(
        ForeignKey("circuits.circuit_id"), unique=True
    )
    driver: Mapped[str]
    year: Mapped[int]
    lap_time_seconds: Mapped[float]

    circuit: Mapped[Circuit] = relationship(back_populates="lap_record")


class CircuitStats(Base):
    __tablename__ = "circuit_stats"
    __table_args__ = (UniqueConstraint("circuit_id", "season"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    circuit_id: Mapped[str] = mapped_column(ForeignKey("circuits.circuit_id"))
    season: Mapped[int]
    sc_probability: Mapped[int]
    red_flag_probability: Mapped[int]
    pit_loss_normal: Mapped[float]
    pit_loss_sc: Mapped[float]
    pit_loss_vsc: Mapped[float]
    undercut_strength: Mapped[float]
    overcut_strength: Mapped[float]

    circuit: Mapped[Circuit] = relationship(back_populates="stats")


class Driver(Base):
    __tablename__ = "drivers"
    __table_args__ = (UniqueConstraint("driver_id", "season"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[str] = mapped_column(String(10))
    full_name: Mapped[str]
    nationality: Mapped[str]
    team: Mapped[str]
    season: Mapped[int]


class RaceWeekend(Base):
    __tablename__ = "race_weekends"
    __table_args__ = (UniqueConstraint("circuit_id", "season"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    circuit_id: Mapped[str] = mapped_column(ForeignKey("circuits.circuit_id"))
    season: Mapped[int]
    round_number: Mapped[int]
    race_date: Mapped[date]
    is_sprint: Mapped[bool]
    soft_compound: Mapped[str] = mapped_column(String(5))
    medium_compound: Mapped[str] = mapped_column(String(5))
    hard_compound: Mapped[str] = mapped_column(String(5))

    circuit: Mapped[Circuit] = relationship(back_populates="race_weekends")
    weather_forecasts: Mapped[list[WeatherForecast]] = relationship(
        back_populates="race_weekend"
    )
    strategies: Mapped[list[Strategy]] = relationship(back_populates="race_weekend")


class WeatherForecast(Base):
    __tablename__ = "weather_forecasts"

    id: Mapped[int] = mapped_column(primary_key=True)
    race_weekend_id: Mapped[int] = mapped_column(ForeignKey("race_weekends.id"))
    session_name: Mapped[str]
    session_date: Mapped[date]
    condition: Mapped[str]
    temp_high_c: Mapped[float]
    temp_low_c: Mapped[float]
    rain_probability: Mapped[int]
    wind_speed_kph: Mapped[float]

    race_weekend: Mapped[RaceWeekend] = relationship(back_populates="weather_forecasts")


class Strategy(Base):
    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(primary_key=True)
    race_weekend_id: Mapped[int] = mapped_column(ForeignKey("race_weekends.id"))
    is_base: Mapped[bool]
    num_stops: Mapped[int]
    label: Mapped[str]

    race_weekend: Mapped[RaceWeekend] = relationship(back_populates="strategies")
    stints: Mapped[list[StrategyStint]] = relationship(back_populates="strategy")


class StrategyStint(Base):
    __tablename__ = "strategy_stints"

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id"))
    stint_order: Mapped[int]
    compound: Mapped[str] = mapped_column(String(15))
    pit_lap_window_start: Mapped[int]
    pit_lap_window_end: Mapped[int]

    strategy: Mapped[Strategy] = relationship(back_populates="stints")


class RaceResult(Base):
    __tablename__ = "race_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    circuit_id: Mapped[str] = mapped_column(ForeignKey("circuits.circuit_id"))
    season: Mapped[int]
    position: Mapped[int]
    driver_id: Mapped[str]
    team: Mapped[str]

    circuit: Mapped[Circuit] = relationship(back_populates="race_results")


class Standing(Base):
    __tablename__ = "standings"
    __table_args__ = (UniqueConstraint("season", "after_round", "type", "position"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    season: Mapped[int]
    after_round: Mapped[int]
    type: Mapped[str] = mapped_column(String(15))
    position: Mapped[int]
    name: Mapped[str]
    points: Mapped[float]
