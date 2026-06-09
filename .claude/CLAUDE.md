# Formation Lap

F1 race-strategy data app. Collects circuit info, weather, tire data, and historical stats to generate pre-race strategy recommendations.

## Stack

- **Python 3.12+**, managed with **uv** (workspace mode)
- **PostgreSQL 16** via Docker Compose (local), Supabase (prod planned)
- **SQLAlchemy Core** (no ORM) with `psycopg2` sync driver
- **Pydantic v2** domain models shared across data layer and API
- **FastAPI** + uvicorn for the API (`formation-api`)
- **Typer** CLI for the data pipeline (`formation-data`)
- **FastF1** for historical F1 timing/lap data
- **Jolpica** (Ergast successor) for schedule, results, standings
- **Open-Meteo** for weather forecasts
- Build system: hatchling

## Repo structure

```
formation-lap/               # uv workspace root
├── packages/
│   ├── data/                # formation-data — CLI pipeline + domain models + schema
│   │   └── src/formation_data/
│   │       ├── cli.py              # Typer CLI — one subcommand per job + orchestrator flows
│   │       ├── db.py               # sync engine + connection_scope() context manager
│   │       ├── domain.py           # Pydantic v2 models (10 types, shared with API)
│   │       ├── schema.py           # SQLAlchemy Core table defs (9 tables)
│   │       ├── repositories.py     # generic upsert() + per-table read helpers
│   │       ├── orchestrator.py     # run_pre_season / run_pre_race / run_post_race flows
│   │       ├── sources/            # external API adapters
│   │       │   ├── fastf1_client.py
│   │       │   ├── jolpica_client.py
│   │       │   └── weather_client.py
│   │       └── jobs/               # one module per job
│   │           ├── static/circuits.py         # hand-curated 22 circuits
│   │           ├── pre_season/                # drivers, race_weekends, lap_records, circuit_stats
│   │           ├── pre_race/                  # weather, strategies
│   │           └── post_race/                 # race_results, standings, lap_records
│   ├── api/                 # formation-api — FastAPI app
│   │   └── src/formation_api/
│   │       ├── main.py
│   │       ├── config.py
│   │       └── routers/    # health, circuits (minimal — most endpoints not yet built)
│   └── web/                 # planned React frontend (empty)
├── docker-compose.yml       # postgres + one-shot worker container
└── pyproject.toml           # workspace config
```

## Database tables

9 tables, all using `UniqueConstraint` for upsert conflict resolution:

| Table | Key columns | Upsert key |
|---|---|---|
| `circuits` | circuit_id (PK), event_name, country, track_length_km, num_corners, num_laps, sm_zones | circuit_id |
| `race_weekends` | circuit_id (FK), season, round_number, race_date, is_sprint, soft/medium/hard_compound | (circuit_id, season) |
| `circuit_stats` | circuit_id (FK), season, sc_probability, red_flag_probability, pit_loss_*, undercut/overcut_strength | (circuit_id, season) |
| `lap_records` | circuit_id (FK, unique), driver, year, lap_time_seconds | circuit_id |
| `drivers` | driver_id, full_name, nationality, team, season | (driver_id, season) |
| `weather_forecasts` | race_weekend_id (FK), session_name, session_date, condition, temps, rain_probability, wind | (race_weekend_id, session_name) |
| `strategies` | race_weekend_id (FK), is_base, num_stops, label | (race_weekend_id, label) |
| `strategy_stints` | strategy_id (FK), stint_order, compound, pit_lap_window_start/end | (strategy_id, stint_order) |
| `race_results` | circuit_id (FK), season, position, driver_id, team | (circuit_id, season, position) |
| `standings` | season, after_round, type ("driver"/"constructor"), position, name, points | (season, after_round, type, position) |

Schema lives in `schema.py`, mirrored by Pydantic models in `domain.py`.

## Data pipeline

Three orchestrated flows in `orchestrator.py`, triggered by CLI or scheduler:

**Pre-season** (`formation-data run-pre-season --season YYYY`): run once before round 1.
1. Static circuits seed (idempotent)
2. Drivers refresh (Jolpica)
3. Race weekends refresh (Jolpica schedule + Pirelli compound lookup)
4. Lap records refresh (FastF1 historical)
5. Circuit stats recompute (FastF1, aggregates last 3 seasons)

**Pre-race** (`formation-data run-pre-race`): cron, T-7 with refreshes T-3 and T-1.
1. Weather forecast (Open-Meteo, mapped to F1 session schedule)
2. Strategy generation (1-stop, 2-stop, undercut variant, SC gamble)

**Post-race** (`formation-data run-post-race`): cron, T+1 day after race.
1. Race results (Jolpica)
2. Standings (Jolpica driver + constructor)
3. Lap records update (FastF1, compare to existing record)

## Implementation status

Most jobs are **skeletons** — they log intent but don't fetch or write data yet. What's implemented:
- `circuits seed` — fully working, hand-curated data
- `list_circuits` repository read + API endpoint
- Generic `upsert()` in repositories.py
- CLI wiring (all subcommands registered)
- Docker Compose for local Postgres
- FastF1 cache setup

What's skeleton/TODO:
- All source client methods (Jolpica, weather, most of FastF1)
- All pre-season jobs except circuits
- All pre-race and post-race jobs
- Most repository read functions
- API endpoints beyond `/circuits/` and `/health`
- Frontend (empty `packages/web/`)

## Architecture patterns

- **No ORM.** SQLAlchemy Core only. Repositories accept a `Connection`; callers own transaction lifecycle via `connection_scope()`.
- **Single `upsert()` function** handles all tables — pass the table, items, and conflict columns.
- **Domain models are Pydantic v2** with `from_attributes=True`. Same type serves as seed input, repo return value, and API response model. Auto-id fields default to `None`.
- **Jobs are plain functions** with signature `run(conn, *, season=..., round_number=...)`. No classes, no registration framework.
- **Orchestrator composes jobs** in dependency order within a single `connection_scope`.
- **API wraps sync DB calls** with `asyncio.to_thread()`.

## Running locally

```bash
# Start Postgres
docker compose up -d db

# Install dependencies
uv sync

# Create tables (Postgres must be running)
uv run python -c "from formation_data.schema import metadata; from formation_data.db import engine; metadata.create_all(engine)"

# Seed circuits
uv run formation-data circuits seed

# Run API
uv run uvicorn formation_api.main:app --reload
```

## Environment variables

| Variable | Default | Used by |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg2://formation:formation@localhost:5432/formation_lap` | data + API |
| `FASTF1_CACHE_DIR` | `~/.cache/fastf1` | data |
| `POSTGRES_USER` | `formation` | docker-compose |
| `POSTGRES_PASSWORD` | `formation` | docker-compose |
| `POSTGRES_DB` | `formation_lap` | docker-compose |

## External data sources

- **FastF1** (`fastf1_client.py`): timing/lap data, event schedule. `get_event_schedule(season)` returns a DataFrame with `EventFormat` column ("conventional", "sprint_shootout", etc.) and `Session1`-`Session5` names/dates. `get_race_session(season, round)` loads race laps.
- **Jolpica** (`jolpica_client.py`): REST API at `https://api.jolpi.ca/ergast/f1`. Schedule, drivers, results, standings. Sprint weekends have a `"Sprint"` key in the race object.
- **Open-Meteo** (`weather_client.py`): free weather forecast API. Circuit lat/lon stored in a partial in-memory map (needs expansion).
