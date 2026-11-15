"""Pre-race job — load the weather forecast for an upcoming race weekend.

Cadence: T-7 with refreshes at T-3 and T-1 as the forecast firms up.

Source: sources.weather_client.get_forecast(lat, lon, start_date, end_date).

Rows produced: one WeatherForecast per day of the weekend, the days being the circuit's
local days its sessions fall on (Friday to Sunday when its timetable isn't loaded).
Open-Meteo returns daily forecasts in the location's own time zone, so they line up; the
API attaches each session to its day (repositories.list_weather_for_weekend).

Safety: no-op (logs and returns) when the weekend/circuit is missing, when the
forecast is empty or the race is beyond Open-Meteo's ~16-day horizon, or when the
provider call fails — so a flaky forecast never sinks the pre-race flow.

Upsert key: WeatherForecast UniqueConstraint(race_weekend_id, forecast_date).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import Connection

from formation_data import domain, repositories, schema
from formation_data.domain import Circuit, RaceWeekend, Session
from formation_data.sources import weather_client

logger = logging.getLogger(__name__)


def run(conn: Connection, *, season: int, round_number: int) -> None:
    """Fetch and persist the daily forecast for (season, round_number)."""
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

    days = _forecast_days(
        rw, repositories.list_sessions_for_weekend(conn, season, round_number), circuit
    )
    start_date, end_date = days[0], days[-1]

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
    for forecast_date in days:
        day = by_date.get(forecast_date.isoformat())
        # Skip days with no usable forecast (beyond the forecast horizon → nulls).
        if day is None or day["temperature_2m_max"] is None:
            continue
        items.append(
            domain.WeatherForecast(
                race_weekend_id=rw.id,
                forecast_date=forecast_date,
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
        conn, schema.weather_forecasts, items, ["race_weekend_id", "forecast_date"]
    )
    logger.info(
        "pre_race.weather.run season=%s round=%s circuit=%s days=%d",
        season,
        round_number,
        circuit.circuit_id,
        len(items),
    )


def _forecast_days(
    rw: RaceWeekend, sessions: list[Session], circuit: Circuit
) -> list[date]:
    """The circuit-local days the weekend's sessions fall on, in order. Friday to Sunday
    (race day) when the timetable isn't loaded."""
    if not sessions:
        return [rw.race_date - timedelta(days=n) for n in (2, 1, 0)]
    tz = ZoneInfo(circuit.timezone)
    return sorted({s.start_time.astimezone(tz).date() for s in sessions})


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
