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
import time

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.jolpi.ca/ergast/f1"

_TIMEOUT = httpx.Timeout(30.0)
_PAGE_SIZE = 100
# Jolpica's unauthenticated burst limit is ~4 req/s; pause between paged
# requests to stay comfortably under it (a 429 would abort a circuit).
_REQUEST_DELAY_S = 0.34


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


def get_qualifying_results(circuit_id: str) -> list[dict]:
    """Every qualifying result on record for a circuit (its Ergast/Jolpica
    circuitId), paginating through all seasons.

    Each row: {season:int, race:str, driver:str, best_time:str} where best_time
    is the driver's best of Q3/Q2/Q1 (results with no Q time are skipped — e.g.
    the pre-2006 single-lap qualifying era exposes no Q1/Q2/Q3). Raises
    httpx.HTTPError on a network/HTTP failure (incl. 429 rate limiting).
    """
    rows: list[dict] = []
    offset = 0
    while True:
        resp = httpx.get(
            f"{BASE_URL}/circuits/{circuit_id}/qualifying.json",
            params={"limit": _PAGE_SIZE, "offset": offset},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        time.sleep(_REQUEST_DELAY_S)
        mrdata = resp.json()["MRData"]
        races = mrdata["RaceTable"]["Races"]
        if not races:
            break
        for race in races:
            for result in race.get("QualifyingResults", []):
                best_time = result.get("Q3") or result.get("Q2") or result.get("Q1")
                if not best_time:
                    continue
                rows.append(
                    {
                        "season": int(race["season"]),
                        "race": race["raceName"],
                        "driver": result["Driver"]["familyName"],
                        "best_time": best_time,
                    }
                )
        offset += _PAGE_SIZE
        if offset >= int(mrdata["total"]):
            break

    logger.info(
        "jolpica.get_qualifying_results circuit=%s rows=%d", circuit_id, len(rows)
    )
    return rows
