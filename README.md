# Formation Lap

A full-stack F1 race-strategy app. It gathers circuit information, weather forecasts,
tire allocations, and historical timing data, runs a Monte-Carlo strategy simulator over
each Grand Prix, and presents a per-weekend Strategy Briefing: circuit profile, session
schedule, weather, standings, past results, and the recommended pit strategies.

![Header preview](img.png)

## What it does

- **Collects** the season schedule, drivers, sessions, standings, and results
  (Jolpica/Ergast), historical lap and timing data plus generated track outlines
  (FastF1), and per-session weather forecasts (Open-Meteo).
- **Simulates** race strategies with a Monte-Carlo race model — generating candidate
  one/two/three-stop plans, evaluating each across many simulated races, and selecting the
  strongest. It runs twice per weekend: a *prelim* pass on season form before the weekend,
  and a *postquali* pass once the grid and qualifying pace are known.
- **Serves** everything through a FastAPI backend and a React front end that renders the
  briefing for the upcoming (or most recent) round.

## Architecture

```
                        ┌─────────────────────┐
  GitHub Actions cron ─▶│  formation-data CLI │─┐
  (scheduled pipeline)  │   + formation-sim   │ │  upserts
                        └─────────────────────┘ │
                                                 ▼
  Vercel ─────────┐                     ┌──────────────────┐
  formation-web   │──▶  formation-api ──▶│ Supabase Postgres│
  (React SPA)     │     (FastAPI, VM)   └──────────────────┘
                  └────────HTTP─────────┘
```

- **`formation-web`** — a Vite + React + TypeScript single-page app, deployed on Vercel.
- **`formation-api`** — a FastAPI service, containerized and deployed to a VM (image built
  and pushed to GHCR by CI). Wraps sync DB reads with `asyncio.to_thread()`.
- **`formation-data`** — a Typer CLI that runs the data pipeline. Scheduled via GitHub
  Actions cron against the hosted database; every job is an idempotent upsert, so re-runs
  are cheap no-ops.
- **`formation-sim`** — the strategy simulator, invoked by the pipeline (and runnable
  standalone). Bundled into the API image alongside `formation-data`.
- **PostgreSQL 16** — Docker Compose locally, **Supabase** in production.

### Design conventions

- **No ORM.** SQLAlchemy Core only. Repositories accept a `Connection`; callers own the
  transaction lifecycle via `connection_scope()`.
- **Single `upsert()` function** handles every table — pass the table, the items, and the
  conflict columns.
- **Domain models are Pydantic v2** (`from_attributes=True`); the same type serves as seed
  input, repo return value, and API response model.
- **Jobs are plain functions** with the signature `run(conn, *, season=..., round_number=...)` —
  no classes, no registration framework. The orchestrator composes them in dependency order
  within a single `connection_scope`.

## Stack

- **Python 3.12+**, managed with **uv** (workspace mode)
- **PostgreSQL 16** (Docker Compose local / Supabase prod)
- **SQLAlchemy Core** (no ORM) with the `psycopg2` sync driver
- **Pydantic v2** domain models, shared across the data layer and API
- **FastAPI** + uvicorn for the API
- **Typer** CLI for the data pipeline
- **NumPy / SciPy / pandas** for the strategy simulator
- **FastF1** (historical timing/lap data), **Jolpica** (schedule, drivers, results,
  standings), **Open-Meteo** (weather)
- **Vite + React + TypeScript**, TanStack Query, vanilla CSS front end
- Build system: hatchling · CI: GitHub Actions · deploy: GHCR + VM (API), Vercel (web)

## Repo structure

```
formation-lap/                # uv workspace root
├── packages/
│   ├── data/                 # formation-data — CLI pipeline, domain models, DB schema
│   │   └── src/formation_data/
│   │       ├── cli.py                # Typer CLI — one subcommand per job + orchestrator flows
│   │       ├── db.py                 # sync engine + connection_scope() context manager
│   │       ├── domain.py             # Pydantic v2 models (shared with the API)
│   │       ├── schema.py             # SQLAlchemy Core table defs
│   │       ├── repositories.py       # generic upsert() + per-table read helpers
│   │       ├── orchestrator.py       # scheduled flows (pre-season / pre-race / post-race / post-session)
│   │       ├── sources/              # external API adapters (fastf1, jolpica, weather)
│   │       └── jobs/                 # one module per job (static / pre_season / pre_race / post_race / post_session)
│   ├── sim/                  # formation-sim — Monte-Carlo strategy simulator
│   │   └── src/formation_sim/
│   │       ├── params/               # circuit / pace / degradation / DNF parameter estimation (FastF1)
│   │       ├── generation/           # candidate strategy generation + plausibility
│   │       ├── sim/                  # race model (pitstops, overtaking, safety car)
│   │       ├── evaluation/           # Monte-Carlo evaluation + outcome aggregation
│   │       ├── selection/            # picks and tiers the recommended strategy set
│   │       ├── context/              # prelim (pre-quali) vs postquali contexts
│   │       ├── validation/           # backtesting against historical races
│   │       └── report/               # human-readable run reports
│   ├── api/                  # formation-api — FastAPI app
│   │   └── src/formation_api/
│   │       ├── main.py
│   │       └── routers/              # health, circuits, drivers, race_weekends, sessions,
│   │                                #   weather, strategies, standings, race_results
│   └── web/                  # formation-web — Vite + React + TS Strategy Briefing page
├── docker-compose.yml        # local: postgres + one-shot worker container
├── docker-compose.prod.yml   # prod: API service on the VM
└── pyproject.toml            # workspace config
```

## Data model

Thirteen tables, all keyed by a `UniqueConstraint` for upsert conflict resolution. The
schema lives in `schema.py`, mirrored by the Pydantic models in `domain.py`.

| Table | Purpose | Upsert key |
|---|---|---|
| `circuits` | Static per-circuit reference: geometry, cross-source ids (`jolpica_id`, `fastf1_location`), `lat`/`lon`, and a generated SVG `track_outline` | `circuit_id` |
| `race_weekends` | One row per round: circuit, season, round, event name, race date, sprint flag, tire compounds | `(season, round_number)` |
| `sessions` | Session schedule per weekend (FP1 → Race), start times as UTC instants | `(race_weekend_id, session_order)` |
| `session_results` | Per-session classification / timesheet, stored as JSONB | `session_id` |
| `circuit_stats` | Safety-car / red-flag probabilities per circuit-season (int percent) | `(circuit_id, season)` |
| `lap_records` | Fastest race lap per circuit | `circuit_id` |
| `drivers` | Driver entry list per season | `(driver_id, season)` |
| `weather_forecasts` | Per-session forecast (condition, temps, rain %, wind) | `(race_weekend_id, session_name)` |
| `strategies` | Recommended strategies per weekend, tagged by `source` (historical / sim) and `phase` (prelim / postquali), with plausibility + tier | `(race_weekend_id, source, label)` |
| `strategy_stints` | Ordered stints (compound + pit-lap window) for a strategy | `(strategy_id, stint_order)` |
| `sim_race_stats` | The simulator's derived race-context stats for a weekend, stored as JSONB | `race_weekend_id` |
| `race_results` | Finishing order per round | `(season, round_number, position)` |
| `standings` | Driver and constructor standings after each round | `(season, after_round, type, position)` |

Notes:

- Circuit identity lives on `circuit_id`, never on an event name — event labels are
  season-unstable (e.g. "Spanish Grand Prix" = Barcelona pre-2026, Madrid from 2026).
  `jolpica_id` and `fastf1_location` map `circuit_id` onto each source's stable key.
- `race_weekends` and `race_results` are keyed on `(season, round_number)`, not
  `(circuit_id, season)` — double-header seasons visit a circuit twice.
- `updated_at` columns are server-managed: `server_default` on insert, explicitly set to
  `now()` in the `upsert()` `ON CONFLICT` clause (Postgres upserts don't run SQLAlchemy
  `onupdate`).
- Heterogeneous, evolving payloads (`session_results`, `sim_race_stats`) are stored as a
  single JSONB blob rather than a rigid column-per-field schema.

## Data pipeline

Scheduled flows in `orchestrator.py`, driven by the `formation-data` CLI and run on a
GitHub Actions cron table against the hosted database:

| Flow | Command | Cadence |
|---|---|---|
| **Pre-season** | `run-pre-season --season YYYY` | Once (15 Jan) — seed circuits, refresh drivers, schedule, sessions, track maps, lap records, circuit stats |
| **Weather** | `run-weather` | Daily — refreshes forecasts once a race is within ~10 days |
| **Prelim sim** | `run-prelim` | Monday of a race week — pre-quali strategy sim on season form |
| **Post-race** | `run-post-race` | Monday after a race — results, standings, fastest-lap update |
| **Post-session** | `run-post-session` | Hourly on race weekends — saves each session's results ~45 min after it ends, and runs the postquali sim once Qualifying is done |

Every job is idempotent, so firing outside its intended window is a cheap no-op. A single
round can be forced with:

```bash
formation-data sim-strategies generate --season YYYY --round N --mode {prelim,postquali}
```

The simulator can also be run standalone for a human-readable report (no DB writes):

```bash
uv run python -m formation_sim.run --mode postquali --year 2026 --round 8 --sims 400
```

## Getting started (local development)

### Backend (data + API)

```bash
# Start Postgres
docker compose up -d db

# Install workspace dependencies (--all-packages installs every workspace member;
# plain `uv sync` does not)
uv sync --all-packages

# Create tables (Postgres must be running; the engine is created lazily)
uv run python -c "from formation_data.schema import metadata; from formation_data.db import get_engine; metadata.create_all(get_engine())"

# Seed static data + a season (idempotent upserts)
uv run formation-data circuits seed
uv run formation-data drivers seed --season 2026
uv run formation-data weekends seed --season 2026

# Run the API
uv run uvicorn formation_api.main:app --reload
```

### Frontend (packages/web)

```bash
cd packages/web
npm install
npm run gen:api   # regenerate API types from http://localhost:8000/openapi.json (API must be running)
npm run dev       # http://localhost:5173 (port is fixed — it's the only CORS-allowed origin)
```

## Environment variables

Copy `.env.example` to `.env` to get started.

| Variable | Default | Used by |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg2://formation:formation@localhost:5432/formation_lap` | data + API |
| `FASTF1_CACHE_DIR` | `~/.cache/fastf1` | data |
| `POSTGRES_USER` | `formation` | docker-compose |
| `POSTGRES_PASSWORD` | `formation` | docker-compose |
| `POSTGRES_DB` | `formation_lap` | docker-compose |

## Deployment

- **API** — `.github/workflows/deploy-api.yml` builds the `formation-api` image (which
  bundles `formation-data` and `formation-sim`), pushes it to GHCR, and rolls it out to
  the VM over SSH via `docker-compose.prod.yml`. It only fires when a change actually
  affects the image (Python packages, lockfile, or the workflow itself).
- **Web** — deployed on Vercel from `packages/web`.
- **Scheduled data jobs** — `.github/workflows/scheduled-data.yml` runs the pipeline cron
  table against the Supabase database using the `DATABASE_URL` repo secret. Any command can
  also be triggered manually via `workflow_dispatch`.

## Development

CI (`.github/workflows/ci.yml`) runs on every push to `main` and every pull request:

```bash
uv sync --all-packages
uv run ruff check .
uv run pytest packages/data/tests
```

## External data sources

- **FastF1** — timing/lap data, event schedule, and telemetry for track outlines.
- **Jolpica** (Ergast successor) — REST API at `https://api.jolpi.ca/ergast/f1` for
  schedule, drivers, results, and standings.
- **Open-Meteo** — free weather forecast API, keyed by each circuit's stored lat/lon.
