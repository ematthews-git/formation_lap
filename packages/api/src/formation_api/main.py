import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from formation_api.routers import (
    circuits,
    drivers,
    health,
    race_results,
    race_weekends,
    sessions,
    standings,
    strategies,
    weather,
)

app = FastAPI(title="Formation Lap API", version="0.1.0")

# Browser origins allowed to call the API. Comma-separated ALLOWED_ORIGINS env
# var in deployed environments (e.g. "https://app.example.com"); defaults to the
# local Vite dev server so nothing changes for local development.
_origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(circuits.router)
app.include_router(race_weekends.router)
app.include_router(drivers.router)
app.include_router(standings.router)
app.include_router(strategies.router)
app.include_router(weather.router)
app.include_router(race_results.router)
app.include_router(sessions.router)
