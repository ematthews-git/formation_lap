"""Pre-race job — load the weather forecast for an upcoming race weekend.

Cadence: T-7 with refreshes at T-3 and T-1 as the forecast firms up.

Source: sources.weather_client.get_forecast(lat, lon, start_date, end_date).

Rows produced: one WeatherForecast per session in the weekend.
- Regular weekend: FP1, FP2, FP3, Qualifying, Race                  (5 rows)
- Sprint weekend : FP1, Sprint Qualifying, Sprint, Qualifying, Race (5 rows)

Open-Meteo returns daily forecasts; each F1 session is mapped to the matching
day relative to race_date (sessions run Fri/Sat/Sun → race_date-2 / -1 / 0).

Safety: no-op (logs and returns) when the weekend/circuit is missing, when the
forecast is empty or the race is beyond Open-Meteo's ~16-day horizon, or when the
provider call fails — so a flaky forecast never sinks the pre-race flow.

Upsert key: WeatherForecast UniqueConstraint(race_weekend_id, session_name).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import httpx
from sqlalchemy import Connection

from formation_data import domain, repositories, schema
from formation_data.domain import RaceWeekend
from formation_data.sources import weather_client

logger = logging.getLogger(__name__)


def run(conn: Connection, *, season: int, round_number: int) -> None:
    """Fetch and persist the per-session forecast for (season, round_number)."""
    rw = repositories.get_race_weekend(conn, season, round_number)
    if rw is None:
        logger.warning(
            "pre_race.weather.run: no race weekend %s R%s; nothing to do",
            season,
            round_number,
        )
        return

    circuit = repositories.get_circuit(conn, rw.circuit_id)
    if circuit is None:
        logger.warning(
            "pre_race.weather.run: race weekend %s R%s references unknown circuit "
            "%s; nothing to do",
            season,
            round_number,
            rw.circuit_id,
        )
        return

    sessions = _session_schedule(rw)
    start_date = min(d for _, d in sessions)
    end_date = max(d for _, d in sessions)

    try:
        forecast = weather_client.get_forecast(
            circuit.lat, circuit.lon, start_date, end_date
        )
    except httpx.HTTPError as exc:
        logger.error(
            "pre_race.weather.run: Open-Meteo request failed for %s (%s); "
            "no forecast written",
            circuit.circuit_id,
            exc,
        )
        return

    by_date = {day["date"]: day for day in forecast}
    items: list[domain.WeatherForecast] = []
    for session_name, session_date in sessions:
        day = by_date.get(session_date.isoformat())
        # Skip sessions with no usable day (beyond the forecast horizon → nulls).
        if day is None or day["temperature_2m_max"] is None:
            continue
        items.append(
            domain.WeatherForecast(
                race_weekend_id=rw.id,
                session_name=session_name,
                session_date=session_date,
                condition=_classify(day["weather_code"]),
                temp_high_c=day["temperature_2m_max"],
                temp_low_c=day["temperature_2m_min"],
                rain_probability=int(day["precipitation_probability_max"] or 0),
                wind_speed_kph=day["wind_speed_10m_max"] or 0.0,
            )
        )

    if not items:
        logger.warning(
            "pre_race.weather.run: no forecast days available for %s %s (race is "
            "likely beyond Open-Meteo's ~16-day horizon); nothing written",
            circuit.circuit_id,
            rw.race_date,
        )
        return

    repositories.upsert(
        conn, schema.weather_forecasts, items, ["race_weekend_id", "session_name"]
    )
    logger.info(
        "pre_race.weather.run season=%s round=%s circuit=%s sessions=%d",
        season,
        round_number,
        circuit.circuit_id,
        len(items),
    )


def _session_schedule(rw: RaceWeekend) -> list[tuple[str, date]]:
    """Session names and dates for the weekend (Fri/Sat/Sun = race-2/-1/0)."""
    race = rw.race_date
    fri = race - timedelta(days=2)
    sat = race - timedelta(days=1)
    if rw.is_sprint:
        return [
            ("FP1", fri),
            ("Sprint Qualifying", fri),
            ("Sprint", sat),
            ("Qualifying", sat),
            ("Race", race),
        ]
    return [
        ("FP1", fri),
        ("FP2", fri),
        ("FP3", sat),
        ("Qualifying", sat),
        ("Race", race),
    ]


# WMO weather-code buckets (Open-Meteo). Coarse, race-relevant labels.
def _classify(code: int | None) -> str:
    """Map a WMO weather code to a short human condition."""
    if code is None:
        return "Unknown"
    if code == 0:
        return "Clear"
    if code in (1, 2):
        return "Partly Cloudy"
    if code == 3:
        return "Overcast"
    if code in (45, 48):
        return "Fog"
    if code in (51, 53, 55, 56, 57):
        return "Drizzle"
    if code in (61, 63, 65, 66, 67):
        return "Rain"
    if code in (71, 73, 75, 77, 85, 86):
        return "Snow"
    if code in (80, 81, 82):
        return "Showers"
    if code in (95, 96, 99):
        return "Thunderstorm"
    return "Unknown"
