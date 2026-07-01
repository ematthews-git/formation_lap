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
# Jolpica's unauthenticated burst limit is ~4 req/s; pause between requests to
# stay under it. The sustained hourly limit is handled by 429 retry/backoff.
_REQUEST_DELAY_S = 0.34
_MAX_RETRIES = 5
_MAX_BACKOFF_S = 60.0


def _get_json(path: str, params: dict | None = None) -> dict:
    """GET {BASE_URL}{path} and return parsed JSON.

    Retries on 429 with backoff (honouring a Retry-After header when present) so
    a batch job rides through Jolpica's sustained rate limit instead of dropping
    requests. Raises httpx.HTTPError on non-429 failures or once retries are
    exhausted.
    """
    for attempt in range(_MAX_RETRIES + 1):
        resp = httpx.get(f"{BASE_URL}{path}", params=params, timeout=_TIMEOUT)
        if resp.status_code == 429 and attempt < _MAX_RETRIES:
            retry_after = resp.headers.get("Retry-After")
            wait = (
                min(float(retry_after), _MAX_BACKOFF_S)
                if retry_after and retry_after.isdigit()
                else min(2**attempt, _MAX_BACKOFF_S)
            )
            logger.warning(
                "jolpica 429 on %s; backing off %.1fs (attempt %d/%d)",
                path,
                wait,
                attempt + 1,
                _MAX_RETRIES,
            )
            time.sleep(wait)
            continue
        resp.raise_for_status()
        time.sleep(_REQUEST_DELAY_S)
        return resp.json()
    resp.raise_for_status()  # retries exhausted on a 429
    return resp.json()


def get_drivers(season: int):
    # TODO: httpx.get(f"{BASE_URL}/{season}/drivers.json").json()["MRData"]["DriverTable"]["Drivers"]
    logger.info("jolpica.get_drivers season=%s (skeleton)", season)
    return []


def get_schedule(season: int):
    # TODO: httpx.get(f"{BASE_URL}/{season}.json").json()["MRData"]["RaceTable"]["Races"]
    logger.info("jolpica.get_schedule season=%s (skeleton)", season)
    return []


def get_race(season: int, round_number: int) -> dict | None:
    """The race object for a round (Circuit + Results + ...), or None if absent.

    Returning the whole race lets callers read the actual Circuit.circuitId
    rather than trusting a round number to line up with our seed calendar.
    """
    races = _get_json(f"/{season}/{round_number}/results.json")["MRData"][
        "RaceTable"
    ]["Races"]
    return races[0] if races else None


def get_circuit_race(season: int, jolpica_circuit_id: str) -> dict | None:
    """The race (Circuit + Results) held at a circuit in a season, or None.

    Lets callers backfill a circuit's history without knowing each season's
    round number.
    """
    races = _get_json(f"/{season}/circuits/{jolpica_circuit_id}/results.json")[
        "MRData"
    ]["RaceTable"]["Races"]
    return races[0] if races else None


def get_driver_standings(season: int, round_number: int) -> list[dict]:
    lists = _get_json(f"/{season}/{round_number}/driverStandings.json")["MRData"][
        "StandingsTable"
    ]["StandingsLists"]
    return lists[0]["DriverStandings"] if lists else []


def get_constructor_standings(season: int, round_number: int) -> list[dict]:
    lists = _get_json(f"/{season}/{round_number}/constructorStandings.json")[
        "MRData"
    ]["StandingsTable"]["StandingsLists"]
    return lists[0]["ConstructorStandings"] if lists else []


def get_race_fastest_laps(circuit_id: str) -> list[dict]:
    """Each race's fastest lap set at a circuit (its Ergast/Jolpica circuitId).

    Uses the `fastest/1/results` filter, so each race contributes the single
    result whose driver set that race's fastest lap. Each row:
    {season:int, race:str, driver:str, best_time:str}. Rows with no fastest-lap
    time (pre-2004 races predate the data) are skipped. Raises httpx.HTTPError
    on a network/HTTP failure (incl. 429 rate limiting).
    """
    rows: list[dict] = []
    offset = 0
    while True:
        resp = httpx.get(
            f"{BASE_URL}/circuits/{circuit_id}/fastest/1/results.json",
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
            for result in race.get("Results", []):
                best_time = result.get("FastestLap", {}).get("Time", {}).get("time")
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
        "jolpica.get_race_fastest_laps circuit=%s rows=%d", circuit_id, len(rows)
    )
    return rows
