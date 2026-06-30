# formation-web

React + TypeScript frontend for Formation Lap — a single-page **Strategy
Briefing** for the next race weekend. Built with Vite, TanStack Query, and
vanilla CSS (design tokens + CSS Modules). Talks to the `formation-api` backend.

## Stack
- **Vite** + **React 19** + **TypeScript**
- **@tanstack/react-query** — data fetching / caching / loading & empty states
- **openapi-typescript** — generates `src/api/schema.d.ts` from the live OpenAPI
- Vanilla CSS: `src/styles/tokens.css` (design tokens) + per-component CSS Modules

## Prerequisites
- Node (installed via Homebrew: `brew install node`)
- The backend running on `http://localhost:8000` with seed data (see below).
  The dev server is pinned to port **5173** because that's the only origin in
  the API's CORS allowlist.

## Run
```bash
# 1. Backend (from repo root) — DB must be up, then seed and serve:
docker compose up -d db
uv sync --all-packages
uv run formation-data circuits seed
uv run formation-data drivers seed --season 2026
uv run formation-data weekends seed --season 2026
uv run uvicorn formation_api.main:app --port 8000

# 2. Frontend (from packages/web):
npm install
npm run gen:api   # regenerate API types from http://localhost:8000/openapi.json
npm run dev       # http://localhost:5173
```

## Data status (live-API-only)
The page renders strictly from live endpoints. Today these are populated:
**race weekends, circuits, drivers, circuit stats**. These sections show
labelled empty states until their backend job/endpoint lands: **lap record,
standings (driver points/form), weather, stint plan/strategies, legacy
results, editorial**.

Use `?round=<n>` to preview a specific round; otherwise the page shows the next
weekend whose race date is today or later.

## Layout
`src/App.tsx` composes the sections in `src/components/<Section>/`. Shared panel
chrome lives in `src/components/common/`. API hooks are in `src/api/queries.ts`.
The original design reference is `mockup.reference.html`.
