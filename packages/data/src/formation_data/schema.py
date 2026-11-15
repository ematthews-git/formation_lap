"""SQLAlchemy Core schema.

Domain types live in `formation_data.domain` (Pydantic). Repositories in
`formation_data.repositories`.

This module is the source of truth for the database's shape. Changing it needs a
matching Alembic revision in `formation_data/migrations/versions/`: generate one with
`formation-data db revision -m "..."` and review it before committing. The migration
test fails while the two disagree.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    column,
    func,
    table,
)
from sqlalchemy.dialects.postgresql import JSONB

# Postgres's own default constraint names, made explicit. Migrations drop and alter
# constraints by name, so the names have to be predictable rather than left to the
# database. These match what Postgres chose for every constraint `create_all` built
# before Alembic was adopted, so existing databases already carry these names.
# Postgres truncates names over 63 characters differently from SQLAlchemy; pass an
# explicit `name=` for a constraint that long.
NAMING_CONVENTION = {
    "pk": "%(table_name)s_pkey",
    "fk": "%(table_name)s_%(column_0_N_name)s_fkey",
    "uq": "%(table_name)s_%(column_0_N_name)s_key",
    "ix": "%(table_name)s_%(column_0_N_name)s_idx",
    "ck": "%(table_name)s_%(constraint_name)s_check",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)


# The values each status column may hold, enforced with CHECK constraints rather than
# Postgres enums, which are awkward to change in a migration. Adding a value means a new
# revision that replaces the constraint.
SESSION_KINDS = ("fp1", "fp2", "fp3", "sprint_quali", "sprint", "quali", "race")
WEATHER_CONDITIONS = (
    "Clear",
    "Partly Cloudy",
    "Overcast",
    "Fog",
    "Drizzle",
    "Rain",
    "Snow",
    "Showers",
    "Thunderstorm",
    "Unknown",
)
STRATEGY_TIERS = ("Most likely", "Alternative", "Long-shot")
TYRE_COMPOUNDS = ("SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET")
ARTIFACT_KINDS = ("laps", "results", "lap1")  # formation_sim.data.artifacts


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


PIRELLI_COMPOUNDS = _quoted(tuple(f"C{n}" for n in range(7)))  # C0 (hardest) .. C6


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
    # IANA zone ("Europe/London"). Session days are the circuit's local days: the weather
    # forecast is stored per local day and matched to sessions through this, and the
    # frontend shows session clocks in it.
    Column("timezone", String(50), nullable=False),
    # First season of the current layout — scopes the lap-record search so laps
    # from a superseded configuration aren't counted. Nullable: null = stable.
    Column("layout_since_year", Integer, nullable=True),
    # SVG path (viewBox 0 0 400 248) of the circuit outline, generated from
    # FastF1 fastest-lap telemetry by jobs.pre_season.track_maps. Nullable:
    # new venues without prior telemetry stay null until backfilled.
    Column("track_outline", Text, nullable=True),
)


lap_records = Table(
    "lap_records",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "circuit_id", ForeignKey("circuits.circuit_id"), nullable=False, unique=True
    ),
    Column("driver_id", ForeignKey("drivers.driver_id"), nullable=False),
    Column("year", Integer, nullable=False),  # the season the record was set in
    Column("lap_time_seconds", Float, nullable=False),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
)


# A team's lineage across rebrands: the entry that was Toro Rosso, AlphaTauri, RB and is
# now Racing Bulls is one team. `team_id` is our own key, named after the current entry,
# and it names the frontend's colour token (`--team-<team_id>`).
teams = Table(
    "teams",
    metadata,
    Column("team_id", String(30), primary_key=True),
    Column("name", String, nullable=False),  # current name, e.g. "Racing Bulls"
)


# What a team was called in one season, and the key each source uses for it then, the
# same pattern as circuits' jolpica_id / fastf1_location. Ingest resolves a source's team
# through these keys, and an unknown key is an error to fix in the teams seed
# (jobs.static.teams), not a new spelling. fastf1_name is NULL where FastF1's name for
# that season isn't on file (2020, which no stored race trace covers).
team_seasons = Table(
    "team_seasons",
    metadata,
    Column("team_id", ForeignKey("teams.team_id"), primary_key=True),
    Column("season", Integer, primary_key=True),
    Column("name", String, nullable=False),  # that season's name, e.g. "AlphaTauri"
    Column("jolpica_id", String(50), nullable=False),  # Jolpica constructorId
    Column("fastf1_name", String, nullable=True),  # FastF1 TeamName
    UniqueConstraint("season", "jolpica_id"),
    UniqueConstraint("season", "fastf1_name"),
)


# One row per person. driver_id is Jolpica's driverId ("max_verstappen", "leclerc"): it's
# stable, already unique across every season (Mick and Michael Schumacher are
# "mick_schumacher" and "michael_schumacher"), and every Jolpica payload carries it, so
# ingest can add a driver it hasn't seen without curating anything. FastF1 identifies
# drivers by `code`, which is only unique within a season (both Schumachers are MSC).
drivers = Table(
    "drivers",
    metadata,
    Column("driver_id", String(50), primary_key=True),
    Column("given_name", String, nullable=False),
    Column("family_name", String, nullable=False),
    Column("code", String(3), nullable=True),
    Column("nationality", String, nullable=True),
)


# Who is entered for which team: the season's grid, as announced (jobs.static.drivers).
# Dated so a mid-season swap is two rows, and dates rather than rounds so a calendar
# renumber can't move a seat. valid_to NULL = to the end of the season. Who actually
# drove in each race, substitutes included, is in race_results.
seats = Table(
    "seats",
    metadata,
    Column("driver_id", ForeignKey("drivers.driver_id"), primary_key=True),
    Column("valid_from", Date, primary_key=True),
    Column("valid_to", Date, nullable=True),
    Column("team_id", String(30), nullable=False),
    Column("season", Integer, nullable=False),
    ForeignKeyConstraint(
        ["team_id", "season"], ["team_seasons.team_id", "team_seasons.season"]
    ),
    CheckConstraint("valid_to > valid_from", name="valid_range"),
)


race_weekends = Table(
    "race_weekends",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("circuit_id", ForeignKey("circuits.circuit_id"), nullable=False, index=True),
    Column("season", Integer, nullable=False),
    Column("round_number", Integer, nullable=False),
    # Jolpica's raceName for this round, stored verbatim — the season-specific event
    # label (e.g. "Styrian Grand Prix", "Bahrain Grand Prix in Malaysia"); it is NOT a
    # stable circuit key, which is why circuit identity lives on circuit_id, not here.
    # (FastF1's own EventName can differ — "São Paulo" vs Jolpica's "Brazilian".)
    Column("event_name", String, nullable=False),
    Column("race_date", Date, nullable=False),
    Column("is_sprint", Boolean, nullable=False),
    # Pirelli's allocation ("C1".."C6"), from the shared nomination table. NULL when a past
    # season has no nomination on file (the table starts in 2021); current and future
    # seasons fall back to a default instead, so a new venue stays usable.
    Column("soft_compound", String(5), nullable=True),
    Column("medium_compound", String(5), nullable=True),
    Column("hard_compound", String(5), nullable=True),
    # Every race from 2020 on, not just the current calendar: race results, standings, race
    # traces and overtakes reference these rows, so season, round and circuit live only
    # here and a mid-season renumber (calendar_sync) changes one row.
    # Keyed on (season, round_number), not (circuit_id, season): double-header
    # seasons (2020: Red Bull Ring, Silverstone, Bahrain ×2) visit a circuit twice.
    UniqueConstraint("season", "round_number"),
    *(
        CheckConstraint(f"{c}_compound IN ({PIRELLI_COMPOUNDS})", name=f"{c}_compound")
        for c in ("soft", "medium", "hard")
    ),
)


# A weekend's sessions, and what hangs off them (results, weather, strategy runs), belong
# to the weekend: deleting a weekend that never raced (a cancelled round) takes them with
# it. Race history (results, standings, traces, overtakes) has no cascade, so a weekend
# that raced can't be deleted by accident.
sessions = Table(
    "sessions",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "race_weekend_id",
        ForeignKey("race_weekends.id", ondelete="CASCADE"),
        nullable=False,
    ),
    # What the session is, whatever FastF1 calls it that season; code keys on this.
    Column("kind", String(15), nullable=False),
    # 1..5 in running order (FP1 → Race), for sorting.
    Column("session_order", Integer, nullable=False),
    Column("name", String, nullable=False),  # FastF1's name, e.g. "Practice 1"
    # Session start, stored as a UTC instant (timestamptz). The frontend renders
    # it in both the circuit's local zone and the viewer's local zone.
    Column("start_time", DateTime(timezone=True), nullable=False, index=True),
    UniqueConstraint("race_weekend_id", "kind"),
    CheckConstraint(f"kind IN ({_quoted(SESSION_KINDS)})", name="kind"),
)


# Open-Meteo's daily forecast for each day of a race weekend, in the circuit's local time.
# Stored per day, the grain the forecast comes in; the API matches each session to its
# local day (circuits.timezone), so a sprint weekend's sessions label themselves.
weather_forecasts = Table(
    "weather_forecasts",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "race_weekend_id",
        ForeignKey("race_weekends.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("forecast_date", Date, nullable=False),
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
    UniqueConstraint("race_weekend_id", "forecast_date"),
    CheckConstraint(f"condition IN ({_quoted(WEATHER_CONDITIONS)})", name="condition"),
)


# One row per strategy generation, so a later run adds to the record instead of replacing
# it (prelim, then postquali, can be compared with each other and with the race).
# "historical" = mined from the last dry running of the circuit (jobs.pre_race.strategies);
# "sim" = produced by the strategy simulator (jobs.pre_race.sim_strategies), with `phase`
# saying which run: "prelim" (pre-weekend, season form) or "postquali" (grid and quali pace
# known). A sim run also carries the race-context numbers it produced (tyre life, undercut,
# pit loss, SC/VSC probability, stop-count split, chaos index, ..., plus the circuit
# profile and run meta) as one JSONB blob, so that feed can evolve without a schema change.
# Readers that want the strategy currently on show use the current_strategy_runs view.
strategy_runs = Table(
    "strategy_runs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "race_weekend_id",
        ForeignKey("race_weekends.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("source", String, nullable=False),
    Column("phase", String, nullable=True),
    Column("stats", JSONB, nullable=True),
    Column(
        "generated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    # A CHECK passes when it evaluates to NULL, hence the explicit IS NOT NULL.
    CheckConstraint(
        "(source = 'historical' AND phase IS NULL) OR "
        "(source = 'sim' AND phase IS NOT NULL AND phase IN ('prelim', 'postquali'))",
        name="source_phase",
    ),
    # current_strategy_runs picks the latest per (race_weekend_id, source)
    Index(None, "race_weekend_id", "source", "generated_at"),
)


# The latest run for each (race_weekend_id, source): what the API shows. A view, created
# by migration 0005, so it isn't part of `metadata`; this mirrors its columns for queries.
current_strategy_runs = table(
    "current_strategy_runs", *(column(c.name, c.type) for c in strategy_runs.c)
)


strategies = Table(
    "strategies",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "run_id", ForeignKey("strategy_runs.id", ondelete="CASCADE"), nullable=False
    ),
    Column("is_base", Boolean, nullable=False),
    Column("num_stops", Integer, nullable=False),
    Column("label", String, nullable=False),
    # Sim only: this strategy's share of field-aggregated plausibility mass, and its
    # coarse tier ("Most likely" / "Alternative" / "Long-shot"). Null for historical.
    Column("plausibility", Float, nullable=True),
    Column("tier", String, nullable=True),
    UniqueConstraint("run_id", "label"),
    CheckConstraint(f"tier IN ({_quoted(STRATEGY_TIERS)})", name="tier"),
)


strategy_stints = Table(
    "strategy_stints",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "strategy_id", ForeignKey("strategies.id", ondelete="CASCADE"), nullable=False
    ),
    Column("stint_order", Integer, nullable=False),
    Column("compound", String(15), nullable=False),
    Column("pit_lap_window_start", Integer, nullable=False),
    Column("pit_lap_window_end", Integer, nullable=False),
    UniqueConstraint("strategy_id", "stint_order"),
    CheckConstraint(f"compound IN ({_quoted(TYRE_COMPOUNDS)})", name="compound"),
)


# Empirical per-circuit race analytics, mined from EVERY race (wet included) in the trailing
# few seasons — the observed-history counterpart to the sim's dry-only, model-derived context
# numbers. Like a sim run's stats it's a single JSONB blob (incidents, grid/finish, tyres,
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
# so, like a sim run's stats, the whole ordered per-driver list is stored as a single JSONB
# blob rather than a rigid column-per-field schema. Sourced from FastF1 ~45 min after the
# session ends (see jobs.post_session.session_results). This is the provisional timesheet,
# shown until the official classification lands; for a race, race_results (Jolpica, the
# Monday after) is the official result.
session_results = Table(
    "session_results",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("session_id", ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    Column("results", JSONB, nullable=False),
    UniqueConstraint("session_id"),
)


# Lap-by-lap trace of one historical race — the RACE_TRACE panel's data. Like the other
# derived feeds it's a single JSONB document (per-lap track status / weather / excitement /
# overtakes arrays plus every starter's lap times, pit laps and — crucially — the team they
# drove for in THAT race, so the frontend never joins against the current season's lineup).
# One per race; season, round and circuit come from the race weekend.
race_traces = Table(
    "race_traces",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("race_weekend_id", ForeignKey("race_weekends.id"), nullable=False, unique=True),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    Column("trace", JSONB, nullable=False),
)


# Every change of on-track order in one race, each labelled with why it happened (racing /
# attrition / pit / lapped / neutralised / start) plus where on the circuit it occurred.
# Kept out of race_traces deliberately: that blob is served whole, five at a time, to the
# race-trace panel, and an event list runs to a couple of hundred rows per race. The
# per-lap counts and per-corner histogram are precomputed into the blob so the common reads
# never have to unpack `events`.
race_overtakes = Table(
    "race_overtakes",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("race_weekend_id", ForeignKey("race_weekends.id"), nullable=False, unique=True),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    Column("overtakes", JSONB, nullable=False),
)


# Official finishing order (Jolpica, the Monday after the race), which supersedes the
# provisional FastF1 timesheet in session_results. Season, round and circuit come from the
# race weekend. team_id is the team the driver raced for in that race; its name that season
# is in team_seasons.
race_results = Table(
    "race_results",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("race_weekend_id", ForeignKey("race_weekends.id"), nullable=False),
    Column("position", Integer, nullable=False),
    Column("driver_id", ForeignKey("drivers.driver_id"), nullable=False, index=True),
    Column("team_id", ForeignKey("teams.team_id"), nullable=False),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    UniqueConstraint("race_weekend_id", "position"),
    UniqueConstraint("race_weekend_id", "driver_id"),
)


# Championship standings after a race, one table per championship.
driver_standings = Table(
    "driver_standings",
    metadata,
    Column("race_weekend_id", ForeignKey("race_weekends.id"), primary_key=True),
    Column("driver_id", ForeignKey("drivers.driver_id"), primary_key=True),
    Column("position", Integer, nullable=False),
    Column("points", Float, nullable=False),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
)


constructor_standings = Table(
    "constructor_standings",
    metadata,
    Column("race_weekend_id", ForeignKey("race_weekends.id"), primary_key=True),
    Column("team_id", ForeignKey("teams.team_id"), primary_key=True),
    Column("position", Integer, nullable=False),
    Column("points", Float, nullable=False),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
)


# Per-race derived tables the simulator reads, serialized to bytes so CI can read them from
# the DB instead of re-fetching ~110 FastF1 sessions (which blows the hourly rate limit). Each
# row is one DataFrame as Parquet (version-portable, unlike pickle). `kind` = "laps" (cleaned
# lap frame consumed by the strategy prior + season form) now; "results"/"lap1" reserved for
# paramset rebuilds. Keyed (kind, season, round_number): one blob per derived file per race.
# Unlike the race tables above this doesn't reference race_weekends: it's the simulator's
# cache, addressed in FastF1's (season, round) terms, and it covers races at venues with no
# `circuits` row that the simulator still learns from.
derived_artifacts = Table(
    "derived_artifacts",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("kind", String(15), nullable=False),
    Column("season", Integer, nullable=False),
    Column("round_number", Integer, nullable=False),
    Column("data", LargeBinary, nullable=False),
    Column("data_format", String(15), nullable=False, server_default="parquet"),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    UniqueConstraint("kind", "season", "round_number"),
    CheckConstraint(f"kind IN ({_quoted(ARTIFACT_KINDS)})", name="kind"),
    CheckConstraint("data_format = 'parquet'", name="data_format"),
)


__all__ = [
    "metadata",
    "circuits",
    "lap_records",
    "teams",
    "team_seasons",
    "drivers",
    "seats",
    "race_weekends",
    "sessions",
    "weather_forecasts",
    "strategy_runs",
    "current_strategy_runs",
    "strategies",
    "strategy_stints",
    "circuit_race_stats",
    "session_results",
    "race_traces",
    "race_results",
    "driver_standings",
    "constructor_standings",
    "derived_artifacts",
]
