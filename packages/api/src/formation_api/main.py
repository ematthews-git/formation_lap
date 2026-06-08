from fastapi import FastAPI

from formation_api.routers import circuits, health

app = FastAPI(title="Formation Lap API", version="0.1.0")

app.include_router(health.router)
app.include_router(circuits.router)
