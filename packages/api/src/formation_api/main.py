from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from formation_api.routers import (
    circuits,
    drivers,
    health,
    race_results,
    race_weekends,
    standings,
    strategies,
    weather,
)

app = FastAPI(title="Formation Lap API", version="0.1.0")

# Allow the local React dev server to call the API from the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
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
