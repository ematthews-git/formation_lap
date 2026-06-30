"""Open-Meteo forecast client.

Used by:
- jobs.pre_race.weather    GET https://api.open-meteo.com/v1/forecast
                            params: latitude, longitude, daily=temperature_2m_max,
                            temperature_2m_min, precipitation_probability_max,
                            wind_speed_10m_max, weather_code; start_date / end_date
                            span the race weekend.

Circuit lat/lon live on the `circuits` table (hand-curated seed); callers look the
circuit up and pass coordinates in.

Note: Open-Meteo's free forecast only reaches ~16 days ahead. Days outside that
horizon come back as null and are filtered out by the caller — fine for the
T-7/T-3/T-1 refresh cadence.
"""

from __future__ import annotations

import logging
from datetime import date

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.open-meteo.com/v1/forecast"

# Open-Meteo daily variables we request, in snake_case (current API).
_DAILY_FIELDS = [
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_probability_max",
    "wind_speed_10m_max",
    "weather_code",
]

_TIMEOUT = httpx.Timeout(30.0)


def get_forecast(
    lat: float, lon: float, start_date: date, end_date: date
) -> list[dict]:
    """Per-day forecast dicts spanning [start_date, end_date] for a location.

    Each dict: {date (ISO str), temperature_2m_max, temperature_2m_min,
    precipitation_probability_max, wind_speed_10m_max, weather_code}. Values may
    be None when Open-Meteo has no data for a day (e.g. beyond the forecast
    horizon). Raises httpx.HTTPError on a network/HTTP failure.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": ",".join(_DAILY_FIELDS),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "timezone": "auto",
    }
    resp = httpx.get(BASE_URL, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    daily = resp.json().get("daily", {})

    times = daily.get("time", [])
    out: list[dict] = []
    for i, day in enumerate(times):
        out.append(
            {"date": day, **{f: _nth(daily.get(f), i) for f in _DAILY_FIELDS}}
        )
    logger.info(
        "weather.get_forecast lat=%s lon=%s %s..%s days=%d",
        lat,
        lon,
        start_date,
        end_date,
        len(out),
    )
    return out


def _nth(seq, i):
    """seq[i] if present, else None — tolerant of a missing/short field array."""
    if seq is None or i >= len(seq):
        return None
    return seq[i]
