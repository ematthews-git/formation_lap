"""Static job: seed a season's grid, the drivers entered and the seat each holds.

Cadence: once a season, when the lineups are announced, and whenever a seat changes
hands. Run `teams seed` first: each seat names a team's row for that season.

Drivers who race are also added from Jolpica's results as they load, so this list only
has to cover the announced grid (which the site shows before round 1). A one-off
substitute needs no seat; race_results records who drove each race.

A mid-season swap is two seats: end the first with `valid_to` and start the next on the
same date.

Upsert keys: drivers (driver_id), seats (driver_id, valid_from).
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import Connection

from formation_data.domain import Driver, Seat

logger = logging.getLogger(__name__)


def run(conn: Connection, *, season: int) -> None:
    from formation_data import repositories, schema

    seats = [s for s in SEATS if s.season == season]
    if not seats:
        logger.warning(
            "static.drivers.run season=%s has no seats on file (have: %s)",
            season,
            sorted({s.season for s in SEATS}),
        )
        return
    entered = {s.driver_id for s in seats}
    repositories.upsert_drivers(conn, [d for d in DRIVERS if d.driver_id in entered])
    repositories.upsert(conn, schema.seats, seats, ["driver_id", "valid_from"])
    logger.info("static.drivers.run season=%s seats=%d", season, len(seats))


def _driver(driver_id: str, given: str, family: str, code: str, nationality: str) -> Driver:
    return Driver(
        driver_id=driver_id,
        given_name=given,
        family_name=family,
        code=code,
        nationality=nationality,
    )


# Names, codes and nationalities as Jolpica has them; driver_id is Jolpica's driverId.
DRIVERS = [
    _driver("norris", "Lando", "Norris", "NOR", "British"),
    _driver("piastri", "Oscar", "Piastri", "PIA", "Australian"),
    _driver("leclerc", "Charles", "Leclerc", "LEC", "Monegasque"),
    _driver("hamilton", "Lewis", "Hamilton", "HAM", "British"),
    _driver("russell", "George", "Russell", "RUS", "British"),
    _driver("antonelli", "Andrea Kimi", "Antonelli", "ANT", "Italian"),
    _driver("max_verstappen", "Max", "Verstappen", "VER", "Dutch"),
    _driver("hadjar", "Isack", "Hadjar", "HAD", "French"),
    _driver("alonso", "Fernando", "Alonso", "ALO", "Spanish"),
    _driver("stroll", "Lance", "Stroll", "STR", "Canadian"),
    _driver("gasly", "Pierre", "Gasly", "GAS", "French"),
    _driver("colapinto", "Franco", "Colapinto", "COL", "Argentine"),
    _driver("albon", "Alexander", "Albon", "ALB", "Thai"),
    _driver("sainz", "Carlos", "Sainz", "SAI", "Spanish"),
    _driver("arvid_lindblad", "Arvid", "Lindblad", "LIN", "British"),
    _driver("lawson", "Liam", "Lawson", "LAW", "New Zealander"),
    _driver("ocon", "Esteban", "Ocon", "OCO", "French"),
    _driver("bearman", "Oliver", "Bearman", "BEA", "British"),
    _driver("hulkenberg", "Nico", "Hülkenberg", "HUL", "German"),
    _driver("bortoleto", "Gabriel", "Bortoleto", "BOR", "Brazilian"),
    _driver("perez", "Sergio", "Pérez", "PER", "Mexican"),
    _driver("bottas", "Valtteri", "Bottas", "BOT", "Finnish"),
]


def _seats(season: int, pairs: list[tuple[str, str]]) -> list[Seat]:
    start = date(season, 1, 1)
    return [
        Seat(driver_id=driver_id, team_id=team_id, season=season, valid_from=start)
        for team_id, driver_id in pairs
    ]


SEATS = _seats(
    2026,
    [
        ("mclaren", "norris"),
        ("mclaren", "piastri"),
        ("ferrari", "leclerc"),
        ("ferrari", "hamilton"),
        ("mercedes", "russell"),
        ("mercedes", "antonelli"),
        ("red_bull", "max_verstappen"),
        ("red_bull", "hadjar"),
        ("aston_martin", "alonso"),
        ("aston_martin", "stroll"),
        ("alpine", "gasly"),
        ("alpine", "colapinto"),
        ("williams", "albon"),
        ("williams", "sainz"),
        ("racing_bulls", "arvid_lindblad"),
        ("racing_bulls", "lawson"),
        ("haas", "ocon"),
        ("haas", "bearman"),
        ("audi", "hulkenberg"),
        ("audi", "bortoleto"),
        ("cadillac", "perez"),
        ("cadillac", "bottas"),
    ],
)
