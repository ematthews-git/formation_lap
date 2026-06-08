"""Jolpica/Ergast HTTP client — drivers, schedule, results, standings.

Base URL: https://api.jolpi.ca/ergast/f1
All endpoints documented at https://github.com/jolpica/jolpica-f1.

Used by:
- jobs.pre_season.drivers          GET /f1/{season}/drivers.json
- jobs.pre_season.race_weekends    GET /f1/{season}.json            (round_number, date, circuit)
- jobs.post_race.race_results      GET /f1/{season}/{round}/results.json
- jobs.post_race.standings         GET /f1/{season}/{round}/driverStandings.json
                                   GET /f1/{season}/{round}/constructorStandings.json
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

BASE_URL = "https://api.jolpi.ca/ergast/f1"


def get_drivers(season: int):
    # TODO: httpx.get(f"{BASE_URL}/{season}/drivers.json").json()["MRData"]["DriverTable"]["Drivers"]
    logger.info("jolpica.get_drivers season=%s (skeleton)", season)
    return []


def get_schedule(season: int):
    # TODO: httpx.get(f"{BASE_URL}/{season}.json").json()["MRData"]["RaceTable"]["Races"]
    logger.info("jolpica.get_schedule season=%s (skeleton)", season)
    return []


def get_race_results(season: int, round_number: int):
    # TODO: httpx.get(f"{BASE_URL}/{season}/{round_number}/results.json").json()["MRData"]["RaceTable"]["Races"][0]["Results"]
    logger.info("jolpica.get_race_results season=%s round=%s (skeleton)", season, round_number)
    return []


def get_driver_standings(season: int, round_number: int):
    # TODO: httpx.get(f"{BASE_URL}/{season}/{round_number}/driverStandings.json").json()...
    logger.info("jolpica.get_driver_standings season=%s round=%s (skeleton)", season, round_number)
    return []


def get_constructor_standings(season: int, round_number: int):
    # TODO: httpx.get(f"{BASE_URL}/{season}/{round_number}/constructorStandings.json").json()...
    logger.info("jolpica.get_constructor_standings season=%s round=%s (skeleton)", season, round_number)
    return []
