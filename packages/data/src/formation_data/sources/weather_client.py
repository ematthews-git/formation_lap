"""Open-Meteo forecast client.

Used by:
- jobs.pre_race.weather    GET https://api.open-meteo.com/v1/forecast
                            params: latitude, longitude, daily=temperature_2m_max,temperature_2m_min,
                            precipitation_probability_max, wind_speed_10m_max, weathercode
                            start_date / end_date span the race weekend.

Circuit lat/lon live on the `circuits` table (hand-curated seed); callers look the
circuit up and pass coordinates in.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

BASE_URL = "https://api.open-meteo.com/v1/forecast"


def get_forecast(lat: float, lon: float, start_date, end_date):
    """Return a list of per-day forecast dicts spanning the race weekend."""
    # TODO:
    #   params = {"latitude": lat, "longitude": lon, "daily": "...", "start_date": ..., "end_date": ...}
    #   return httpx.get(BASE_URL, params=params).json()["daily"]
    logger.info(
        "weather.get_forecast lat=%s lon=%s %s..%s (skeleton)",
        lat, lon, start_date, end_date,
    )
    return []
