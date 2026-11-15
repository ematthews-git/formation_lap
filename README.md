# Formation Lap

Formation Lap is a Formula 1 race-strategy app. For each Grand Prix weekend it builds a
Strategy Briefing: the circuit profile, session schedule, weather forecast, championship
standings, recent results at the track, and the pit strategies a Monte-Carlo race simulator
expects to be run.

**Live site:** [formationlap.dev](https://www.formationlap.dev)

![Strategy Briefing header](img.png)

## Features

- **Strategy simulator.** Generates every rule-legal one-, two- and three-stop plan, weights
  each by how often similar strategies have been run before, simulates full races with
  traffic, safety cars and degradation, and shows the most plausible few with their expected
  finishing positions. It runs before the weekend on season form (`prelim`) and again once
  qualifying sets the grid (`postquali`).
- **Circuit analytics.** Safety-car and red-flag rates, pit loss, tyre life, overtaking and
  grid-to-finish statistics mined from recent seasons at each track.
- **Race history.** Lap-by-lap race traces and every classified overtake for past races at
  the circuit, with each driver shown in the team they raced for at the time.
- **Weekend data.** Session timetable in local and viewer time, per-session results, weather
  forecasts, standings and podiums.

## Architecture

```
  FastF1 · Jolpica · Open-Meteo
               │
               ▼
  ┌──────────────────────────┐   upserts   ┌────────────┐
  │ formation-data (CLI)     │────────────▶│ PostgreSQL │
  │   uses formation-sim     │             └─────┬──────┘
  └──────────────────────────┘                   │
                                                 ▼
                                      ┌────────────────────┐  JSON  ┌────────────────────┐
                                      │ formation-api      │───────▶│ formation-web      │
                                      │ (FastAPI)          │        │ (React SPA)        │
                                      └────────────────────┘        └────────────────────┘
```

| Package | What it is |
|---|---|
| [`packages/data`](packages/data) (`formation-data`) | Typer CLI that fetches source data, runs the simulator and writes to Postgres. Owns the schema, domain models and migrations. |
| [`packages/sim`](packages/sim) (`formation-sim`) | The strategy simulator: candidate generation, Monte-Carlo evaluation and selection. See its [README](packages/sim/README.md). |
| [`packages/api`](packages/api) (`formation-api`) | Read-only FastAPI service over the database. |
| [`packages/web`](packages/web) (`formation-web`) | Vite + React + TypeScript front end. See its [README](packages/web/README.md). |

### Conventions

- **SQLAlchemy Core, no ORM.** Repositories take a `Connection`; callers own the transaction
  through `connection_scope()`.
- **Pydantic v2 domain models** (`domain.py`) are shared by the data layer and the API, so a
  table row, a job's output and an API response use the same type.
- **Jobs are plain functions** and every write is an idempotent upsert, so re-running a job
  is safe.

## Tech stack

- Python 3.12, [uv](https://docs.astral.sh/uv/) workspace, hatchling
- PostgreSQL 16+, SQLAlchemy Core, psycopg2, Alembic
- FastAPI and uvicorn; Typer
- pandas, NumPy and SciPy for the simulator
- Vite, React 19, TypeScript, TanStack Query, vanilla CSS modules
- GitHub Actions for CI and image builds; GHCR; Vercel for the front end

## Repository layout

```
formation_lap/
├── packages/
│   ├── data/src/formation_data/
│   │   ├── cli.py              # formation-data CLI: one command per job, plus flows
│   │   ├── orchestrator.py     # flows that chain jobs (pre-season, pre-race, post-race, ...)
│   │   ├── jobs/               # one module per job, grouped by when it runs
│   │   ├── sources/            # FastF1, Jolpica and Open-Meteo clients
│   │   ├── schema.py           # table definitions (source of truth for the schema)
│   │   ├── migrations/         # Alembic revisions
│   │   ├── domain.py           # Pydantic models
│   │   └── repositories.py     # reads and the shared upsert
│   ├── sim/src/formation_sim/  # params, generation, sim, evaluation, selection, validation
│   ├── api/src/formation_api/  # FastAPI app and routers
│   └── web/                    # front end
├── deploy/ scripts/            # deployment and job-runner helpers
├── docker-compose.yml          # local Postgres (and an optional one-shot worker)
└── pyproject.toml              # uv workspace
```

## Getting started

### Prerequisites

- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- Docker, for the local database
- A current Node.js LTS release, for the front end
- An [F1TV](https://f1tv.formula1.com) Access subscription, only for jobs that download F1
  timing data through FastF1 (lap times, telemetry, session results). The API and front end
  run without it.

### Backend

```bash
cp .env.example .env
docker compose up -d db
uv sync --all-packages                 # installs every workspace package
uv run formation-data db upgrade       # create or update the tables

# reference data and a season's calendar
uv run formation-data circuits seed
uv run formation-data teams seed
uv run formation-data drivers seed --season 2026
uv run formation-data weekends refresh --season 2026
uv run formation-data sessions refresh --season 2026

uv run uvicorn formation_api.main:app --reload    # http://localhost:8000/docs
```

### Front end

```bash
cd packages/web
npm install
npm run dev        # http://localhost:5173
```

The dev server uses port 5173 because that is the API's default allowed CORS origin. With the
API running, `npm run gen:api` regenerates `src/api/schema.d.ts` from its OpenAPI schema.

### Configuration

| Variable | Default | Used by |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg2://formation:formation@localhost:5432/formation_lap` | data, API |
| `FASTF1_CACHE_DIR` | `~/.cache/fastf1` | data |
| `F1_USERNAME`, `F1_PASSWORD` | unset | data: F1TV account FastF1 signs in with |
| `ALLOWED_ORIGINS` | `http://localhost:5173` | API: comma-separated CORS origins |
| `VITE_API_BASE_URL` | `http://localhost:8000` | web |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `formation` / `formation` / `formation_lap` | docker compose |

## Data pipeline

All data is loaded through the `formation-data` CLI (`uv run formation-data --help`). Each
job can be run on its own, and flows chain them for each point in a race weekend:

| Flow | Does |
|---|---|
| `run-pre-season --season YYYY` | Circuits, teams, the announced grid, calendar, session timetable and lap records for a season |
| `run-weather` | Refreshes the forecast once the next race is within ten days |
| `run-prelim` | Runs the pre-qualifying strategy simulation in race week |
| `run-post-session` | Saves each session's results after it ends, and runs the post-qualifying simulation once qualifying is done |
| `run-post-race` | Loads results and standings, then the race's lap record, laps and race trace |

The intended schedule for each flow is in `.github/workflows/scheduled-data.yml`.

FastF1 needs an F1TV sign-in to download timing data. Sign in once with
`uv run formation-data f1tv login` (or set `F1_USERNAME` and `F1_PASSWORD` for unattended
runs) and check it with `formation-data f1tv status`. FastF1's on-disk cache makes repeated
loads free, which keeps long backfills inside its hourly request limit.

Common tasks:

```bash
# re-sync a season's calendar after it changes (preview first)
uv run formation-data weekends refresh --season 2026 --dry-run

# load an earlier season's history: its calendar first, then results
uv run formation-data weekends refresh --season 2019
uv run formation-data results backfill --start 2019 --count 1

# simulate one round and store the result
uv run formation-data sim-strategies generate --season 2026 --round 8 --mode postquali

# run the simulator on its own and print a report (no database writes)
uv run python -m formation_sim.run --mode postquali --year 2026 --round 8 --sims 400
```

## Database

[`schema.py`](packages/data/src/formation_data/schema.py) defines the schema, and Alembic
migrations apply it.

| Area | Tables |
|---|---|
| Reference | `circuits`, `lap_records`, `teams`, `team_seasons`, `drivers`, `seats` |
| Calendar | `race_weekends` (every race from 2020), `sessions`, `weather_forecasts` |
| Results and history | `race_results`, `driver_standings`, `constructor_standings`, `session_results`, `race_traces`, `race_overtakes` |
| Circuit analytics | `circuit_race_stats` |
| Strategy | `strategy_runs` (one row per generation), `strategies`, `strategy_stints`; the `current_strategy_runs` view picks the latest run per weekend and source |
| Simulator cache | `derived_artifacts` (cleaned lap frames as Parquet) |

A circuit is identified by `circuit_id`, never by an event name, since event names change
between seasons. Race history references its `race_weekends` row, so a calendar renumber
updates one row. Each circuit carries its IANA time zone: the weather forecast is stored
per local day and the API matches each session to its day, so a sprint weekend's sessions
label themselves. Code keys sessions on `kind` (`fp1` to `race`) rather than on FastF1's
name for them, which changes between seasons.

Deleting a race weekend that never raced takes its sessions, weather and strategy runs with
it; one with results can't be deleted. Status columns (session kind, weather condition,
tyre and Pirelli compounds, strategy tier) are limited to known values by CHECK
constraints, so a new value needs a migration.

Drivers are keyed on Jolpica's `driverId`, and teams on a lineage id that stays the same
through rebrands (`racing_bulls` covers AlphaTauri, RB and Racing Bulls). `team_seasons`
holds each team's name and source keys per season, so results, standings and race traces
resolve the team a source names through it, and a team that isn't there stops the load.
A new season needs its teams added to `jobs/static/teams.py` before its first results
load, and its announced grid to `jobs/static/drivers.py`.

Every strategy generation is kept as a `strategy_runs` row: each run of the historical
miner, and each sim run (prelim, then postquali) with the race-context numbers it produced.
The API shows the latest run per weekend and source through the `current_strategy_runs`
view, and earlier runs stay stored for comparison.

Derived feeds whose shape is still evolving (race traces, overtakes, circuit analytics,
simulator output) are stored as JSONB.

To change the schema, edit `schema.py`, then generate and review a migration:

```bash
uv run formation-data db upgrade                   # local database at the newest revision
uv run formation-data db revision -m "describe the change"
# review the file in migrations/versions/: autogenerate writes a rename as a drop plus an add
uv run formation-data db upgrade
uv run formation-data db check                     # schema.py and migrations agree
```

`db current` shows a database's revision and `db downgrade --to <revision>` steps back. All
commands act on `DATABASE_URL`.

## Testing

```bash
uv run ruff check .
uv run pytest packages/data/tests packages/sim/tests
```

The migration tests need a throwaway Postgres database whose name contains `test`; they are
skipped otherwise:

```bash
docker exec formation_lap_db createdb -U formation formation_lap_test
FORMATION_TEST_DATABASE_URL=postgresql+psycopg2://formation:formation@localhost:5432/formation_lap_test \
  uv run pytest packages/data/tests/test_migrations.py
```

For the front end, `npm run lint` and `npm run build` (which type-checks) in `packages/web`.

CI runs ruff and the data tests, including the migration tests against a Postgres service, on
every pull request and push to `main`.

## Deployment

- **API:** `.github/workflows/deploy-api.yml` builds the `formation-api` image, which bundles
  the data and simulator packages, publishes it to GHCR and deploys it with
  `docker-compose.prod.yml`.
- **Front end:** Vercel, from `packages/web`.
- **Database:** hosted PostgreSQL. Apply migrations with `formation-data db upgrade` against
  its `DATABASE_URL`.

## Data sources

- [FastF1](https://github.com/theOehrly/Fast-F1): lap timing, telemetry, session results and
  event schedules.
- [Jolpica F1 API](https://github.com/jolpica/jolpica-f1) (the Ergast successor): calendar,
  results and standings.
- [Open-Meteo](https://open-meteo.com): weather forecasts, licensed under
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
- Pirelli tyre nominations, curated in
  [`nominations.yaml`](packages/sim/src/formation_sim/config/nominations.yaml).

## Disclaimer

Formation Lap is an unofficial project and is not associated in any way with the Formula 1
companies. F1, FORMULA ONE, FORMULA 1, FIA FORMULA ONE WORLD CHAMPIONSHIP, GRAND PRIX and
related marks are trade marks of Formula One Licensing B.V.
