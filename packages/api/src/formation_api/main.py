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

# Browser origins allowed to call the API.
#   ALLOWED_ORIGINS       — comma-separated exact-match list (e.g.
#                           "https://formationlap.dev,https://www.formationlap.dev").
#                           Defaults to the local Vite dev server, so local dev is
#                           unchanged.
#   ALLOWED_ORIGIN_REGEX  — optional regex for dynamic origins; set it to
#                           "https://.*\.vercel\.app" so Vercel preview deploys
#                           (unique per-deploy URLs) can call the API too.
_origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins.split(",") if o.strip()],
    allow_origin_regex=os.environ.get("ALLOWED_ORIGIN_REGEX") or None,
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
