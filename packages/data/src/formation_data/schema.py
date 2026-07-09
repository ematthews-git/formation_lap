"""SQLAlchemy Core schema.

Domain types live in `formation_data.domain` (Pydantic). Repositories in
`formation_data.repositories`.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()


circuits = Table(
    "circuits",
    metadata,
    Column("circuit_id", String(50), primary_key=True),
    Column("country", String, nullable=False),
    Column("track_length_km", Float, nullable=False),
    Column("num_corners", Integer, nullable=False),
    Column("num_laps", Integer, nullable=False),
    Column("sm_zones", Integer, nullable=False),
    # Cross-source identity + location, hand-curated alongside the rest of the row.
    # These map our circuit_id onto the keys other sources use, so we never have to
    # match on a season-unstable event name (e.g. "Spanish Grand Prix" = Barcelona
    # pre-2026, Madrid from 2026). jolpica_id joins against Jolpica's Circuit.circuitId;
    # fastf1_location joins against FastF1's get_event_schedule().Location (stable per
    # track, unlike EventName); lat/lon feed Open-Meteo.
    Column("jolpica_id", String(50), nullable=False, unique=True),
    Column("fastf1_location", String(50), nullable=False, unique=True),
    Column("lat", Float, nullable=False),
    Column("lon", Float, nullable=False),
    # First season of the current layout — scopes the lap-record search so laps
    # from a superseded configuration aren't counted. Nullable: null = stable.
    Column("layout_since_year", Integer, nullable=True),
    # SVG path (viewBox 0 0 400 248) of the circuit outline, generated from
    # FastF1 fastest-lap telemetry by jobs.pre_season.track_maps. Nullable:
    # new venues without prior telemetry stay null until backfilled.
    Column("track_outline", String, nullable=True),
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
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
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
    # FastF1's EventName for this round, stored verbatim. This is the season-
    # specific event label (e.g. "Styrian Grand Prix"); it is NOT a stable circuit
    # key, which is why circuit identity lives on circuit_id, not here.
    Column("event_name", String, nullable=False),
    Column("race_date", Date, nullable=False),
    Column("is_sprint", Boolean, nullable=False),
    Column("soft_compound", String(5), nullable=False),
    Column("medium_compound", String(5), nullable=False),
    Column("hard_compound", String(5), nullable=False),
    # Keyed on (season, round_number), not (circuit_id, season): double-header
    # seasons (2020: Red Bull Ring, Silverstone, Bahrain ×2) visit a circuit twice,
    # and circuit_stats backfills historical seasons.
    UniqueConstraint("season", "round_number"),
)


sessions = Table(
    "sessions",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("race_weekend_id", ForeignKey("race_weekends.id"), nullable=False),
    # 1..5 in running order (FP1 → Race). Sprint weekends reuse the same slots
    # for different session *names* ("Sprint Qualifying", "Sprint"), so the name
    # carries the format, not the order.
    Column("session_order", Integer, nullable=False),
    Column("name", String, nullable=False),
    # Session start, stored as a UTC instant (timestamptz). The frontend renders
    # it in both the circuit's local zone and the viewer's local zone.
    Column("start_time", DateTime(timezone=True), nullable=False),
    UniqueConstraint("race_weekend_id", "session_order"),
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
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    UniqueConstraint("race_weekend_id", "session_name"),
)


strategies = Table(
    "strategies",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("race_weekend_id", ForeignKey("race_weekends.id"), nullable=False),
    # Provenance. "historical" = mined from the last dry running of the circuit
    # (jobs.pre_race.strategies); "sim" = produced by the strategy simulator
    # (jobs.pre_race.sim_strategies). Both coexist per weekend, hence source is
    # part of the uniqueness key so a shared label doesn't collide across sources.
    Column("source", String, nullable=False, server_default="historical"),
    # Sim only: which run produced these rows. "prelim" (pre-weekend, season form)
    # is superseded by "postquali" (grid + quali pace known). Null for historical.
    Column("phase", String, nullable=True),
    Column("is_base", Boolean, nullable=False),
    Column("num_stops", Integer, nullable=False),
    Column("label", String, nullable=False),
    # Sim only: this strategy's share of field-aggregated plausibility mass, and its
    # coarse tier ("Most likely" / "Alternative" / "Long-shot"). Null for historical.
    Column("plausibility", Float, nullable=True),
    Column("tier", String, nullable=True),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    UniqueConstraint(
        "race_weekend_id", "source", "label", name="uq_strategies_weekend_source_label"
    ),
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


# Race-context numbers a sim run produces (tyre life, undercut power, pit loss, SC/VSC
# probability, overtaking difficulty, stop-count split, chaos index, degradation rank,
# pole-to-win, plus the circuit profile and run meta). Stored as a single JSONB blob —
# the whole derived-stats feed — rather than a column per number, so the fan-facing set
# can evolve without a schema change. One row per weekend; the latest phase wins.
sim_race_stats = Table(
    "sim_race_stats",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("race_weekend_id", ForeignKey("race_weekends.id"), nullable=False),
    Column("phase", String, nullable=False),  # "prelim" | "postquali"
    Column(
        "generated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    Column("stats", JSONB, nullable=False),
    UniqueConstraint("race_weekend_id"),
)


# Empirical per-circuit race analytics, mined from EVERY race (wet included) in the trailing
# few seasons — the observed-history counterpart to the sim's dry-only, model-derived context
# numbers. Like sim_race_stats it's a single JSONB blob (incidents, grid/finish, tyres,
# weather, timing … a large, still-evolving set) rather than a column per metric, so the feed
# can grow without a migration. Keyed (circuit_id, season): one rollup per circuit per season
# the job is run for, the season fixing the trailing window it was computed over.
circuit_race_stats = Table(
    "circuit_race_stats",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("circuit_id", ForeignKey("circuits.circuit_id"), nullable=False),
    Column("season", Integer, nullable=False),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    Column("stats", JSONB, nullable=False),
    UniqueConstraint("circuit_id", "season"),
)


# Per-session finishing order / timesheet, one row per session. Session classifications
# are heterogeneous — a practice timesheet (fastest lap + gap), a qualifying sheet
# (Q1/Q2/Q3), and a race classification (points, status, time) share almost no columns —
# so, like sim_race_stats, the whole ordered per-driver list is stored as a single JSONB
# blob rather than a rigid column-per-field schema. Sourced from FastF1 ~45 min after the
# session ends (see jobs.post_session.session_results); the frontend renders it later.
session_results = Table(
    "session_results",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("session_id", ForeignKey("sessions.id"), nullable=False),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    Column("results", JSONB, nullable=False),
    UniqueConstraint("session_id"),
)


race_results = Table(
    "race_results",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("circuit_id", ForeignKey("circuits.circuit_id"), nullable=False),
    Column("season", Integer, nullable=False),
    Column("round_number", Integer, nullable=False),
    Column("position", Integer, nullable=False),
    Column("driver_id", String, nullable=False),
    Column("team", String, nullable=False),
    # Keyed on (season, round_number) rather than (circuit_id, season): a circuit
    # can host two rounds in one season (2020 double-headers), which would collide
    # on circuit_id. circuit_id stays as a denormalized FK for convenient joins.
    UniqueConstraint("season", "round_number", "position"),
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
    "sessions",
    "weather_forecasts",
    "strategies",
    "strategy_stints",
    "sim_race_stats",
    "circuit_race_stats",
    "session_results",
    "race_results",
    "standings",
]
