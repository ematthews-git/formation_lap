"""Static job — seed the Driver table for a season from a hand-curated grid.

Cadence: rare. Re-run when a seat changes hands. This is the v1 hand-written
counterpart to pre_season/drivers.py, which will pull the grid from Jolpica once
that source client is implemented.

Data is hand written and reflects the 2026 grid as best known at build time.
VERIFY before relying on it — several seats were unsettled and are flagged inline:
  - Red Bull second seat (Tsunoda here)
  - Racing Bulls pairing (Hadjar / Lawson here)
  - Alpine second seat (Colapinto here)

driver_id is a short lowercase surname (the column is String(10); Jolpica's
"max_verstappen"-style ids would overflow). It's our own stable key, not Jolpica's.
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection

from formation_data.domain import Driver

logger = logging.getLogger(__name__)


def run(conn: Connection, *, season: int) -> None:
    from formation_data import repositories, schema

    grid = _GRID_BY_SEASON.get(season)
    if grid is None:
        logger.warning(
            "static.drivers.run season=%s has no hand-curated grid (have: %s)",
            season,
            sorted(_GRID_BY_SEASON),
        )
        return

    repositories.upsert(
        conn, table=schema.drivers, items=grid, conflict_cols=["driver_id", "season"]
    )
    logger.info("static.drivers.run season=%s drivers=%d", season, len(grid))


def _driver(driver_id: str, full_name: str, nationality: str, team: str) -> Driver:
    # season is bound when the grid is materialised, below.
    return Driver(
        driver_id=driver_id,
        full_name=full_name,
        nationality=nationality,
        team=team,
        season=_SEASON,
    )


_SEASON = 2026

_DRIVERS_2026 = [
    # McLaren
    _driver("norris", "Lando Norris", "British", "McLaren"),
    _driver("piastri", "Oscar Piastri", "Australian", "McLaren"),
    # Ferrari
    _driver("leclerc", "Charles Leclerc", "Monégasque", "Ferrari"),
    _driver("hamilton", "Lewis Hamilton", "British", "Ferrari"),
    # Mercedes
    _driver("russell", "George Russell", "British", "Mercedes"),
    _driver("antonelli", "Kimi Antonelli", "Italian", "Mercedes"),
    # Red Bull Racing
    _driver("verstappen", "Max Verstappen", "Dutch", "Red Bull Racing"),
    _driver("tsunoda", "Yuki Tsunoda", "Japanese", "Red Bull Racing"),  # VERIFY seat
    # Aston Martin
    _driver("alonso", "Fernando Alonso", "Spanish", "Aston Martin"),
    _driver("stroll", "Lance Stroll", "Canadian", "Aston Martin"),
    # Alpine
    _driver("gasly", "Pierre Gasly", "French", "Alpine"),
    _driver("colapinto", "Franco Colapinto", "Argentine", "Alpine"),  # VERIFY seat
    # Williams
    _driver("albon", "Alexander Albon", "Thai", "Williams"),
    _driver("sainz", "Carlos Sainz", "Spanish", "Williams"),
    # Racing Bulls
    _driver("hadjar", "Isack Hadjar", "French", "Racing Bulls"),  # VERIFY pairing
    _driver("lawson", "Liam Lawson", "New Zealander", "Racing Bulls"),  # VERIFY pairing
    # Haas
    _driver("ocon", "Esteban Ocon", "French", "Haas"),
    _driver("bearman", "Oliver Bearman", "British", "Haas"),
    # Audi (formerly Kick Sauber)
    _driver("hulkenberg", "Nico Hülkenberg", "German", "Audi"),
    _driver("bortoleto", "Gabriel Bortoleto", "Brazilian", "Audi"),
    # Cadillac (new entry)
    _driver("perez", "Sergio Pérez", "Mexican", "Cadillac"),
    _driver("bottas", "Valtteri Bottas", "Finnish", "Cadillac"),
]

_GRID_BY_SEASON = {2026: _DRIVERS_2026}
