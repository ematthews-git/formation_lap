"""Open-Meteo forecast client.

Used by:
- jobs.pre_race.weather    GET https://api.open-meteo.com/v1/forecast
                            params: latitude, longitude, daily=temperature_2m_max,temperature_2m_min,
                            precipitation_probability_max, wind_speed_10m_max, weathercode
                            start_date / end_date span the race weekend.

Circuit lat/lon are not in `Circuit` today — either add columns there or keep a static map here.
The skeleton keeps an in-memory map so the model schema doesn't need another column for now.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

BASE_URL = "https://api.open-meteo.com/v1/forecast"

# TODO: fill out the rest of the calendar — kept short for the skeleton.
CIRCUIT_COORDS: dict[str, tuple[float, float]] = {
    # circuit_id: (lat, lon)
    "melbourne": (-37.8497, 144.9680),
    "monaco": (43.7347, 7.4206),
    "silverstone": (52.0786, -1.0169),
}


def get_forecast(circuit_id: str, start_date, end_date):
    """Return a list of per-day forecast dicts spanning the race weekend."""
    # TODO:
    #   lat, lon = CIRCUIT_COORDS[circuit_id]
    #   params = {"latitude": lat, "longitude": lon, "daily": "...", "start_date": ..., "end_date": ...}
    #   return httpx.get(BASE_URL, params=params).json()["daily"]
    logger.info(
        "weather.get_forecast %s %s..%s (skeleton)", circuit_id, start_date, end_date
    )
    return []
