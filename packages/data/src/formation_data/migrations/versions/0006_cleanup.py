"""cleanup: one home per fact, keys code can rely on, and constraints on status strings

- `circuit_stats` is dropped. Its safety-car and red-flag numbers duplicated
  circuit_race_stats' incidents block on a different window and scale, and nothing read
  them. circuit_race_stats is their one home.
- `circuits.timezone` (IANA) moves the zones out of the frontend, so the API can work in
  a circuit's local days.
- `sessions.kind` (fp1 .. race) says what a session is whatever FastF1 calls it that
  season, and is unique per weekend; session lengths and "has quali happened" key on it.
- `weather_forecasts` is keyed on (race_weekend_id, forecast_date), the grain Open-Meteo
  returns: one row per local day instead of one per guessed session name. Same-day
  sessions held copies of one forecast, so nothing is lost; the latest copy is kept.
- `derived_artifacts.year` is renamed `season`, as everywhere else.
- race_results, both standings tables and lap_records gain `updated_at`.
- CHECK constraints on the status strings (session kind, weather condition, strategy
  tier, tyre compound, Pirelli compound, artifact kind and format), and indexes on
  race_weekends.circuit_id, race_results.driver_id, sessions.start_time and the column set
  current_strategy_runs sorts on.
- A weekend's sessions, weather and strategy runs, and a session's results, are deleted
  with it (ON DELETE CASCADE); race history is not.

Every existing row is checked first: a circuit with no known zone, a session name with no
kind, or a status value outside its list stops the upgrade before anything changes.

Downgrading recreates circuit_stats empty (`formation-data circuit-stats recompute` refills
it) and turns each forecast day back into the session rows the old job wrote for it.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-15 22:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from formation_data.migrate import MigrationError

revision: str = '0006'
down_revision: str | Sequence[str] | None = '0005'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# The circuits seed's zones (jobs.static.circuits) as of this revision.
_TIMEZONES = {
    "melbourne": "Australia/Melbourne",
    "shanghai": "Asia/Shanghai",
    "suzuka": "Asia/Tokyo",
    "miami": "America/New_York",
    "montreal": "America/Toronto",
    "monaco": "Europe/Monaco",
    "barcelona": "Europe/Madrid",
    "red_bull_ring": "Europe/Vienna",
    "silverstone": "Europe/London",
    "spa": "Europe/Brussels",
    "hungaroring": "Europe/Budapest",
    "zandvoort": "Europe/Amsterdam",
    "monza": "Europe/Rome",
    "madrid": "Europe/Madrid",
    "baku": "Asia/Baku",
    "sepang": "Asia/Kuala_Lumpur",
    "singapore": "Asia/Singapore",
    "austin": "America/Chicago",
    "mexico_city": "America/Mexico_City",
    "sao_paulo": "America/Sao_Paulo",
    "las_vegas": "America/Los_Angeles",
    "lusail": "Asia/Qatar",
    "abu_dhabi": "Asia/Dubai",
}

# FastF1 session name -> kind, as of this revision (jobs.pre_season.sessions.session_kind).
_KIND_BY_NAME = {
    "Practice 1": "fp1",
    "Practice 2": "fp2",
    "Practice 3": "fp3",
    "Sprint Qualifying": "sprint_quali",
    "Sprint Shootout": "sprint_quali",
    "Sprint": "sprint",
    "Qualifying": "quali",
    "Race": "race",
}


def _kind(name: str, season: int) -> str | None:
    # 2021's sprint race was named "Sprint Qualifying".
    if season == 2021 and name == "Sprint Qualifying":
        return "sprint"
    return _KIND_BY_NAME.get(name)


def _quoted(values) -> str:
    return ", ".join(f"'{v}'" for v in values)


# (table, constraint name, condition). Frozen copies of schema.py's vocabularies.
_PIRELLI = _quoted(f"C{n}" for n in range(7))
_CHECKS = [
    *(
        ("race_weekends", f"race_weekends_{c}_compound_check", f"{c}_compound IN ({_PIRELLI})")
        for c in ("soft", "medium", "hard")
    ),
    (
        "sessions",
        "sessions_kind_check",
        f"kind IN ({_quoted(('fp1', 'fp2', 'fp3', 'sprint_quali', 'sprint', 'quali', 'race'))})",
    ),
    (
        "weather_forecasts",
        "weather_forecasts_condition_check",
        "condition IN ({})".format(
            _quoted(
                (
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
            )
        ),
    ),
    (
        "strategies",
        "strategies_tier_check",
        f"tier IN ({_quoted(('Most likely', 'Alternative', 'Long-shot'))})",
    ),
    (
        "strategy_stints",
        "strategy_stints_compound_check",
        f"compound IN ({_quoted(('SOFT', 'MEDIUM', 'HARD', 'INTERMEDIATE', 'WET'))})",
    ),
    ("derived_artifacts", "derived_artifacts_kind_check", "kind IN ('laps', 'results', 'lap1')"),
    ("derived_artifacts", "derived_artifacts_data_format_check", "data_format = 'parquet'"),
]

# (table, column, referenced table.column) whose FK gains ON DELETE CASCADE.
_CASCADES = [
    ("sessions", "race_weekend_id", "race_weekends", "id"),
    ("weather_forecasts", "race_weekend_id", "race_weekends", "id"),
    ("strategy_runs", "race_weekend_id", "race_weekends", "id"),
    ("session_results", "session_id", "sessions", "id"),
]

_INDEXES = [
    ("race_weekends_circuit_id_idx", "race_weekends", ["circuit_id"]),
    ("race_results_driver_id_idx", "race_results", ["driver_id"]),
    ("sessions_start_time_idx", "sessions", ["start_time"]),
    (
        "strategy_runs_race_weekend_id_source_generated_at_idx",
        "strategy_runs",
        ["race_weekend_id", "source", "generated_at"],
    ),
]

_UPDATED_AT = ("race_results", "driver_standings", "constructor_standings", "lap_records")

# What the old weather job wrote for each day: (is_sprint, days before the race, name).
_OLD_WEATHER_SESSIONS = [
    (False, 2, "FP1"),
    (False, 2, "FP2"),
    (False, 1, "FP3"),
    (False, 1, "Qualifying"),
    (False, 0, "Race"),
    (True, 2, "FP1"),
    (True, 2, "Sprint Qualifying"),
    (True, 1, "Sprint"),
    (True, 1, "Qualifying"),
    (True, 0, "Race"),
]


def _problems(bind) -> list[str]:
    problems = [
        f"circuits {cid}: no time zone on file"
        for (cid,) in bind.exec_driver_sql("SELECT circuit_id FROM circuits ORDER BY 1")
        if cid not in _TIMEZONES
    ]
    seen: dict[tuple[int, str], str] = {}
    for weekend_id, season, rnd, name in bind.exec_driver_sql(
        "SELECT s.race_weekend_id, rw.season, rw.round_number, s.name FROM sessions s "
        "JOIN race_weekends rw ON rw.id = s.race_weekend_id ORDER BY 2, 3, s.session_order"
    ):
        kind = _kind(name, season)
        if kind is None:
            problems.append(f"sessions {season} R{rnd}: no kind for {name!r}")
        elif (weekend_id, kind) in seen:
            problems.append(
                f"sessions {season} R{rnd}: {seen[weekend_id, kind]!r} and {name!r} "
                f"are both {kind}"
            )
        else:
            seen[weekend_id, kind] = name
    for table, name, condition in _CHECKS:
        if name == "sessions_kind_check":
            continue  # a new column; the names it's filled from are checked above
        column = condition.split()[0]
        for (value,) in bind.exec_driver_sql(
            f"SELECT DISTINCT {column} FROM {table} WHERE NOT ({condition}) ORDER BY 1"
        ):
            problems.append(f"{table}.{column}: {value!r} isn't an allowed value")
    return problems


def _replace_fk(table: str, column: str, ref_table: str, ref_column: str, ondelete) -> None:
    name = f"{table}_{column}_fkey"
    op.drop_constraint(name, table, type_="foreignkey")
    op.create_foreign_key(name, table, ref_table, [column], [ref_column], ondelete=ondelete)


def upgrade() -> None:
    bind = op.get_bind()
    problems = _problems(bind)
    if problems:
        listed = "\n".join(f"  {p}" for p in problems)
        raise MigrationError(
            f"Some rows don't fit 0006's rules, so it wasn't applied and nothing changed:\n"
            f"{listed}\n"
            "Fix or delete those rows (or add the value to 0006 and schema.py if it's a "
            "real one), then run `formation-data db upgrade` again."
        )

    op.drop_table("circuit_stats")

    op.add_column("circuits", sa.Column("timezone", sa.String(length=50), nullable=True))
    bind.execute(
        sa.text("UPDATE circuits SET timezone = :tz WHERE circuit_id = :cid"),
        [{"cid": cid, "tz": tz} for cid, tz in _TIMEZONES.items()],
    )
    op.alter_column("circuits", "timezone", existing_type=sa.String(length=50), nullable=False)

    op.add_column("sessions", sa.Column("kind", sa.String(length=15), nullable=True))
    kinds = [
        {"id": sid, "kind": _kind(name, season)}
        for sid, name, season in bind.exec_driver_sql(
            "SELECT s.id, s.name, rw.season FROM sessions s "
            "JOIN race_weekends rw ON rw.id = s.race_weekend_id"
        )
    ]
    if kinds:
        bind.execute(sa.text("UPDATE sessions SET kind = :kind WHERE id = :id"), kinds)
    op.alter_column("sessions", "kind", existing_type=sa.String(length=15), nullable=False)
    op.drop_constraint("sessions_race_weekend_id_session_order_key", "sessions", type_="unique")
    op.create_unique_constraint(
        "sessions_race_weekend_id_kind_key", "sessions", ["race_weekend_id", "kind"]
    )

    # One forecast per local day: keep each day's most recently written row.
    bind.exec_driver_sql(
        "DELETE FROM weather_forecasts w USING ("
        "  SELECT id, row_number() OVER (PARTITION BY race_weekend_id, session_date "
        "                                ORDER BY updated_at DESC, id DESC) AS n "
        "  FROM weather_forecasts"
        ") ranked WHERE ranked.id = w.id AND ranked.n > 1"
    )
    op.drop_constraint(
        "weather_forecasts_race_weekend_id_session_name_key", "weather_forecasts", type_="unique"
    )
    op.drop_column("weather_forecasts", "session_name")
    op.alter_column("weather_forecasts", "session_date", new_column_name="forecast_date")
    op.create_unique_constraint(
        "weather_forecasts_race_weekend_id_forecast_date_key",
        "weather_forecasts",
        ["race_weekend_id", "forecast_date"],
    )

    op.alter_column("derived_artifacts", "year", new_column_name="season")
    op.execute(
        "ALTER TABLE derived_artifacts RENAME CONSTRAINT derived_artifacts_kind_year_round_number_key "
        "TO derived_artifacts_kind_season_round_number_key"
    )

    for table in _UPDATED_AT:
        op.add_column(
            table,
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )
    for table, name, condition in _CHECKS:
        op.create_check_constraint(op.f(name), table, condition)
    for table, column, ref_table, ref_column in _CASCADES:
        _replace_fk(table, column, ref_table, ref_column, "CASCADE")
    for name, table, columns in _INDEXES:
        op.create_index(name, table, columns)


def downgrade() -> None:
    bind = op.get_bind()
    for name, table, _ in _INDEXES:
        op.drop_index(name, table_name=table)
    for table, column, ref_table, ref_column in _CASCADES:
        _replace_fk(table, column, ref_table, ref_column, None)
    for table, name, _ in _CHECKS:
        op.drop_constraint(op.f(name), table, type_="check")
    for table in _UPDATED_AT:
        op.drop_column(table, "updated_at")

    op.execute(
        "ALTER TABLE derived_artifacts RENAME CONSTRAINT derived_artifacts_kind_season_round_number_key "
        "TO derived_artifacts_kind_year_round_number_key"
    )
    op.alter_column("derived_artifacts", "season", new_column_name="year")

    # Each forecast day becomes the session rows the old job wrote for it.
    op.drop_constraint(
        "weather_forecasts_race_weekend_id_forecast_date_key", "weather_forecasts", type_="unique"
    )
    op.alter_column("weather_forecasts", "forecast_date", new_column_name="session_date")
    op.add_column("weather_forecasts", sa.Column("session_name", sa.String(), nullable=True))
    slots = " UNION ALL ".join(
        f"SELECT {str(sprint).lower()} AS is_sprint, {days} AS days, '{name}' AS name"
        for sprint, days, name in _OLD_WEATHER_SESSIONS
    )
    bind.exec_driver_sql(
        "INSERT INTO weather_forecasts (race_weekend_id, session_name, session_date, condition, "
        "temp_high_c, temp_low_c, rain_probability, wind_speed_kph, updated_at) "
        "SELECT w.race_weekend_id, slot.name, w.session_date, w.condition, w.temp_high_c, "
        "w.temp_low_c, w.rain_probability, w.wind_speed_kph, w.updated_at "
        "FROM weather_forecasts w JOIN race_weekends rw ON rw.id = w.race_weekend_id "
        f"JOIN ({slots}) slot ON slot.is_sprint = rw.is_sprint "
        "AND w.session_date = rw.race_date - slot.days "
        "ORDER BY w.race_weekend_id, w.session_date"
    )
    bind.exec_driver_sql("DELETE FROM weather_forecasts WHERE session_name IS NULL")
    op.alter_column("weather_forecasts", "session_name", existing_type=sa.String(), nullable=False)
    op.create_unique_constraint(
        "weather_forecasts_race_weekend_id_session_name_key",
        "weather_forecasts",
        ["race_weekend_id", "session_name"],
    )

    op.drop_constraint("sessions_race_weekend_id_kind_key", "sessions", type_="unique")
    op.drop_column("sessions", "kind")
    op.create_unique_constraint(
        "sessions_race_weekend_id_session_order_key",
        "sessions",
        ["race_weekend_id", "session_order"],
    )

    op.drop_column("circuits", "timezone")

    op.create_table(
        "circuit_stats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("circuit_id", sa.String(length=50), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("sc_probability", sa.Integer(), nullable=False),
        sa.Column("red_flag_probability", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["circuit_id"], ["circuits.circuit_id"], name=op.f("circuit_stats_circuit_id_fkey")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("circuit_stats_pkey")),
        sa.UniqueConstraint(
            "circuit_id", "season", name=op.f("circuit_stats_circuit_id_season_key")
        ),
    )
