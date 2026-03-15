"""
Extract Task – Wetterdaten von Open-Meteo API abrufen
"""
import os
import json
import logging
import requests
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# Welche Felder wir von der API wollen
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
    """
    Ruft Wetterdaten für eine Stadt von der Open-Meteo API ab.
    Gibt ein dict mit den Rohdaten zurück.
    """
    logger.info(f"Fetching weather data for {city} ({latitude}, {longitude})")

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": ",".join(DAILY_VARIABLES),
        "hourly": ",".join(HOURLY_VARIABLES),
        "timezone": "Europe/Berlin",
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
    """
    Airflow Task Function – liest Konfiguration aus Env-Variablen
    und schreibt Ergebnis in XCom.
    """
    city = os.getenv("DEFAULT_CITY", "Freiburg")
    latitude = float(os.getenv("DEFAULT_LATITUDE", "47.9990"))
    longitude = float(os.getenv("DEFAULT_LONGITUDE", "7.8421"))

    raw_data = fetch_weather(city, latitude, longitude)

    # XCom Push – Airflow übergibt die Daten an den nächsten Task
    context["ti"].xcom_push(key="raw_weather", value=raw_data)
    logger.info("Raw weather data pushed to XCom.")
    return raw_data
