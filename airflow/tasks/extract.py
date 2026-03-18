"""
Airflow ETL – Extract Task
==========================

Fetches a 7-day weather forecast from the Open-Meteo public API for a single
city and pushes the raw API response into the Airflow XCom store so the
downstream ``transform`` task can process it.

Configuration is read from environment variables rather than DAG parameters so
that the Docker Compose setup can override the target city without modifying
DAG code:

  DEFAULT_CITY      – city name stored alongside the data (default: "Freiburg")
  DEFAULT_LATITUDE  – geographic latitude in decimal degrees (default: 47.9990)
  DEFAULT_LONGITUDE – geographic longitude in decimal degrees (default: 7.8421)

Data requested from Open-Meteo:
  Daily (7 days)  – temperature max/min, precipitation, snowfall, wind speed,
                    wind gusts, WMO code, UV index, sunrise/sunset times
  Hourly (168 h)  – temperature, apparent temperature, precipitation, rain,
                    snowfall, wind speed/direction, relative humidity, sunshine
                    duration, WMO code, is_day flag, soil temperature at 0/6/18 cm,
                    soil moisture at 0-1/1-3/3-9 cm layers

XCom output (key ``"raw_weather"``):
  A dict with the structure::

      {
        "city":       "Freiburg",
        "latitude":   47.999,
        "longitude":  7.8421,
        "fetched_at": "2025-06-01T12:00:00+00:00",
        "data": { <full Open-Meteo JSON response> }
      }

Dependencies:
  requests

Author: <project maintainer>
"""

import os
import json
import logging
import requests
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# Daily forecast variables to request. These correspond to the columns in the
# ``weather_daily`` database table.
DAILY_VARIABLES = [
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "snowfall_sum",
    "wind_speed_10m_max",
    "wind_gusts_10m_max",
    "weather_code",
    "uv_index_max",
    "sunrise",
    "sunset",
]

# Hourly forecast variables to request. These correspond to the columns in the
# ``weather_hourly`` database table, including the soil data added in Session 3.
HOURLY_VARIABLES = [
    "temperature_2m",
    "apparent_temperature",
    "precipitation",
    "rain",
    "snowfall",
    "wind_speed_10m",
    "wind_direction_10m",
    "relative_humidity_2m",
    "sunshine_duration",
    "weather_code",
    "is_day",
    "soil_temperature_0cm",
    "soil_temperature_6cm",
    "soil_temperature_18cm",
    "soil_moisture_0_to_1cm",
    "soil_moisture_1_to_3cm",
    "soil_moisture_3_to_9cm",
]


def fetch_weather(city: str, latitude: float, longitude: float) -> dict:
    """Call the Open-Meteo forecast API and return a structured result dict.

    Builds the request parameters from the module-level variable lists and
    sends a GET request to the Open-Meteo ``/v1/forecast`` endpoint. The
    response is wrapped in a metadata envelope (city, coordinates, timestamp)
    before being returned.

    All errors are logged and re-raised so Airflow can mark the task as failed
    and apply the DAG's retry policy.

    Args:
        city: Human-readable city name. Not sent to the API; stored as metadata
              for downstream tasks to identify the origin of the data.
        latitude: Geographic latitude in decimal degrees (WGS-84).
        longitude: Geographic longitude in decimal degrees (WGS-84).

    Returns:
        A dict with the following structure::

            {
              "city":       "Freiburg",
              "latitude":   47.999,
              "longitude":  7.8421,
              "fetched_at": "2025-06-01T12:00:00+00:00",
              "data": {
                "daily":  {"time": [...], "temperature_2m_max": [...], ...},
                "hourly": {"time": [...], "temperature_2m": [...], ...},
                ...
              }
            }

    Raises:
        requests.exceptions.Timeout: When the API does not respond within
            30 seconds.
        requests.exceptions.HTTPError: When the API returns a non-2xx HTTP
            status code (e.g. 429 rate-limited, 500 server error).
        Exception: Any other unexpected error during the request.
    """
    logger.info(f"Fetching weather data for {city} ({latitude}, {longitude})")

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": ",".join(DAILY_VARIABLES),
        "hourly": ",".join(HOURLY_VARIABLES),
        "timezone": "Europe/Berlin",  # Returns local time strings; simplifies transform logic
        "forecast_days": 7,
    }

    try:
        response = requests.get(OPEN_METEO_URL, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        result = {
            "city": city,
            "latitude": latitude,
            "longitude": longitude,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }

        logger.info(
            f"Successfully fetched {len(data.get('daily', {}).get('time', []))} daily "
            f"and {len(data.get('hourly', {}).get('time', []))} hourly records for {city}"
        )
        return result

    except requests.exceptions.Timeout:
        logger.error(f"Timeout fetching weather data for {city}")
        raise
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error fetching weather data for {city}: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error fetching weather data for {city}: {e}")
        raise


def extract(**context) -> dict:
    """Airflow task entry point for the extract step.

    Reads the target city and coordinates from environment variables, calls
    ``fetch_weather()``, and pushes the result into Airflow XCom under the key
    ``"raw_weather"`` so the downstream ``transform`` task can pull it.

    This function is registered as a ``PythonOperator`` callable in
    ``airflow/dags/weather_dag.py``.

    Args:
        **context: Airflow task context dict injected by the
            ``PythonOperator``. Must contain ``context["ti"]`` (TaskInstance)
            to enable XCom operations.

    Returns:
        The raw weather data dict (same object that was pushed to XCom).
        Airflow also stores the return value in XCom automatically under the
        key ``"return_value"``.

    Side effects:
        Pushes the raw weather data to XCom under the key ``"raw_weather"``
        via ``context["ti"].xcom_push()``.
    """
    city      = os.getenv("DEFAULT_CITY",      "Freiburg")
    latitude  = float(os.getenv("DEFAULT_LATITUDE",  "47.9990"))
    longitude = float(os.getenv("DEFAULT_LONGITUDE", "7.8421"))

    raw_data = fetch_weather(city, latitude, longitude)

    # Push to XCom so the transform task can retrieve it by task_id + key
    context["ti"].xcom_push(key="raw_weather", value=raw_data)
    logger.info("Raw weather data pushed to XCom.")
    return raw_data
