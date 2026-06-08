"""Pre-race job — load the weather forecast for an upcoming race weekend.

Cadence: T-7 with refreshes at T-3 and T-1 as the forecast firms up.

Source: sources.weather_client.get_forecast(circuit_id, start_date, end_date).

Rows produced: one WeatherForecast per session in the weekend.
- Regular weekend: FP1, FP2, FP3, Qualifying, Race      (5 rows)
- Sprint weekend : FP1, Sprint Qualifying, Sprint, Qualifying, Race  (5 rows)

Open-Meteo returns daily forecasts; we map each F1 session to the corresponding day
relative to race_date.

Upsert key: WeatherForecast UniqueConstraint(race_weekend_id, session_name).
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection

logger = logging.getLogger(__name__)


def run(conn: Connection, *, season: int, round_number: int) -> None:
    # TODO:
    #   from formation_data import domain, repositories, schema
    #   from formation_data.sources import weather_client
    #   rw = repositories.get_race_weekend(conn, season, round_number)
    #   sessions_by_day = _expand_session_schedule(rw)   # list[(session_name, session_date)]
    #   forecast = weather_client.get_forecast(
    #       rw.circuit_id, sessions_by_day[0][1], sessions_by_day[-1][1],
    #   )
    #   items = [domain.WeatherForecast(
    #       race_weekend_id=rw.id, session_name=name, session_date=d,
    #       condition=_classify(day["weathercode"]),
    #       temp_high_c=day["temperature_2m_max"], temp_low_c=day["temperature_2m_min"],
    #       rain_probability=day["precipitation_probability_max"],
    #       wind_speed_kph=day["wind_speed_10m_max"],
    #   ) for (name, d), day in zip(sessions_by_day, _pick_days(forecast, sessions_by_day))]
    #   repositories.upsert(
    #       conn, schema.weather_forecasts, items, ["race_weekend_id", "session_name"],
    #   )
    logger.info(
        "pre_race.weather.run season=%s round=%s (skeleton)", season, round_number
    )
