"""
Weather Fetch Router – On-demand Wetterdaten von Open-Meteo holen und speichern
"""
import logging
import threading
import requests
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from database import get_db
import chart_cache

router = APIRouter(prefix="/weather", tags=["Weather Fetch"])
logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

DAILY_VARIABLES = [
    "temperature_2m_max", "temperature_2m_min", "precipitation_sum",
    "snowfall_sum", "wind_speed_10m_max", "wind_gusts_10m_max",
    "weather_code", "uv_index_max", "sunrise", "sunset",
]

HOURLY_VARIABLES = [
    "temperature_2m", "apparent_temperature", "precipitation",
    "rain", "snowfall", "wind_speed_10m", "wind_direction_10m",
    "relative_humidity_2m", "sunshine_duration", "weather_code", "is_day",
    "soil_temperature_0cm", "soil_temperature_6cm", "soil_temperature_18cm",
    "soil_moisture_0_to_1cm", "soil_moisture_1_to_3cm", "soil_moisture_3_to_9cm",
]


def _safe(lst, i, default=None):
    try:
        v = lst[i]
        return v if v is not None else default
    except (IndexError, TypeError):
        return default


def _fetch(city: str, lat: float, lon: float) -> dict:
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": ",".join(DAILY_VARIABLES),
        "hourly": ",".join(HOURLY_VARIABLES),
        "timezone": "Europe/Berlin",
        "forecast_days": 7,
    }
    resp = requests.get(OPEN_METEO_URL, params=params, timeout=30)
    resp.raise_for_status()
    logger.info(f"Fetched Open-Meteo data for {city} ({lat}, {lon})")
    return resp.json()


def _store(city: str, lat: float, lon: float, api: dict, db: Session):
    daily  = api.get("daily", {})
    hourly = api.get("hourly", {})

    # ── Upsert daily ─────────────────────────────────────────────────
    daily_sql = text("""
        INSERT INTO weather_daily (
            city, forecast_date,
            temperature_max, temperature_min,
            precipitation_sum, snowfall_sum,
            wind_speed_max, wind_gusts_max,
            weather_code, uv_index_max,
            sunrise, sunset
        ) VALUES (
            :city, :forecast_date,
            :temperature_max, :temperature_min,
            :precipitation_sum, :snowfall_sum,
            :wind_speed_max, :wind_gusts_max,
            :weather_code, :uv_index_max,
            :sunrise, :sunset
        )
        ON CONFLICT (city, forecast_date) DO UPDATE SET
            temperature_max   = EXCLUDED.temperature_max,
            temperature_min   = EXCLUDED.temperature_min,
            precipitation_sum = EXCLUDED.precipitation_sum,
            snowfall_sum      = EXCLUDED.snowfall_sum,
            wind_speed_max    = EXCLUDED.wind_speed_max,
            wind_gusts_max    = EXCLUDED.wind_gusts_max,
            weather_code      = EXCLUDED.weather_code,
            uv_index_max      = EXCLUDED.uv_index_max,
            sunrise           = EXCLUDED.sunrise,
            sunset            = EXCLUDED.sunset,
            created_at        = NOW()
    """)

    for i, date_str in enumerate(daily.get("time", [])):
        db.execute(daily_sql, {
            "city":             city,
            "forecast_date":    date_str,
            "temperature_max":  _safe(daily.get("temperature_2m_max"), i),
            "temperature_min":  _safe(daily.get("temperature_2m_min"), i),
            "precipitation_sum": _safe(daily.get("precipitation_sum"), i, 0.0),
            "snowfall_sum":     _safe(daily.get("snowfall_sum"), i, 0.0),
            "wind_speed_max":   _safe(daily.get("wind_speed_10m_max"), i),
            "wind_gusts_max":   _safe(daily.get("wind_gusts_10m_max"), i),
            "weather_code":     _safe(daily.get("weather_code"), i),
            "uv_index_max":     _safe(daily.get("uv_index_max"), i),
            "sunrise":          _safe(daily.get("sunrise"), i),
            "sunset":           _safe(daily.get("sunset"), i),
        })

    # ── Upsert hourly ────────────────────────────────────────────────
    hourly_sql = text("""
        INSERT INTO weather_hourly (
            city, forecast_time,
            temperature, feels_like,
            precipitation, rain, snowfall,
            wind_speed, wind_direction,
            humidity, sunshine_duration,
            weather_code, is_day,
            soil_temperature_0cm, soil_temperature_6cm, soil_temperature_18cm,
            soil_moisture_0_1cm, soil_moisture_1_3cm, soil_moisture_3_9cm
        ) VALUES (
            :city, :forecast_time,
            :temperature, :feels_like,
            :precipitation, :rain, :snowfall,
            :wind_speed, :wind_direction,
            :humidity, :sunshine_duration,
            :weather_code, :is_day,
            :soil_temperature_0cm, :soil_temperature_6cm, :soil_temperature_18cm,
            :soil_moisture_0_1cm, :soil_moisture_1_3cm, :soil_moisture_3_9cm
        )
        ON CONFLICT (city, forecast_time) DO UPDATE SET
            temperature           = EXCLUDED.temperature,
            feels_like            = EXCLUDED.feels_like,
            precipitation         = EXCLUDED.precipitation,
            rain                  = EXCLUDED.rain,
            snowfall              = EXCLUDED.snowfall,
            wind_speed            = EXCLUDED.wind_speed,
            wind_direction        = EXCLUDED.wind_direction,
            humidity              = EXCLUDED.humidity,
            sunshine_duration     = EXCLUDED.sunshine_duration,
            weather_code          = EXCLUDED.weather_code,
            is_day                = EXCLUDED.is_day,
            soil_temperature_0cm  = EXCLUDED.soil_temperature_0cm,
            soil_temperature_6cm  = EXCLUDED.soil_temperature_6cm,
            soil_temperature_18cm = EXCLUDED.soil_temperature_18cm,
            soil_moisture_0_1cm   = EXCLUDED.soil_moisture_0_1cm,
            soil_moisture_1_3cm   = EXCLUDED.soil_moisture_1_3cm,
            soil_moisture_3_9cm   = EXCLUDED.soil_moisture_3_9cm,
            created_at            = NOW()
    """)

    for i, time_str in enumerate(hourly.get("time", [])):
        db.execute(hourly_sql, {
            "city":               city,
            "forecast_time":      time_str,
            "temperature":        _safe(hourly.get("temperature_2m"), i),
            "feels_like":         _safe(hourly.get("apparent_temperature"), i),
            "precipitation":      _safe(hourly.get("precipitation"), i, 0.0),
            "rain":               _safe(hourly.get("rain"), i, 0.0),
            "snowfall":           _safe(hourly.get("snowfall"), i, 0.0),
            "wind_speed":         _safe(hourly.get("wind_speed_10m"), i),
            "wind_direction":     _safe(hourly.get("wind_direction_10m"), i),
            "humidity":           _safe(hourly.get("relative_humidity_2m"), i),
            "sunshine_duration":    _safe(hourly.get("sunshine_duration"), i, 0.0),
            "weather_code":         _safe(hourly.get("weather_code"), i),
            "is_day":               bool(_safe(hourly.get("is_day"), i, 1)),
            "soil_temperature_0cm":  _safe(hourly.get("soil_temperature_0cm"), i),
            "soil_temperature_6cm":  _safe(hourly.get("soil_temperature_6cm"), i),
            "soil_temperature_18cm": _safe(hourly.get("soil_temperature_18cm"), i),
            "soil_moisture_0_1cm":   _safe(hourly.get("soil_moisture_0_to_1cm"), i),
            "soil_moisture_1_3cm":   _safe(hourly.get("soil_moisture_1_to_3cm"), i),
            "soil_moisture_3_9cm":   _safe(hourly.get("soil_moisture_3_to_9cm"), i),
        })

    # Deactivate old alerts (no alert config in backend – Airflow handles those)
    db.execute(
        text("UPDATE weather_alerts SET is_active = FALSE WHERE city = :city AND is_active = TRUE"),
        {"city": city},
    )

    db.commit()
    n_daily  = len(daily.get("time", []))
    n_hourly = len(hourly.get("time", []))
    logger.info(f"Stored {n_daily} daily + {n_hourly} hourly records for {city}")


def _prewarm_chart(city: str, hours: int = 96):
    """Background thread: hit the chart endpoint so it gets generated + cached."""
    try:
        resp = requests.get(
            "http://localhost:8000/charts/hourly-plot",
            params={"city": city, "hours": hours},
            timeout=120,
        )
        logger.info(f"Chart pre-warm for {city}: HTTP {resp.status_code}")
    except Exception as e:
        logger.warning(f"Chart pre-warm failed for {city}: {e}")


# ── Endpoint ─────────────────────────────────────────────────────────────────

@router.post("/fetch-now")
def fetch_now(
    city: str   = Query(..., description="Stadtname"),
    lat:  float = Query(..., description="Breitengrad"),
    lon:  float = Query(..., description="Längengrad"),
    db: Session = Depends(get_db),
):
    """
    Ruft Wetterdaten von Open-Meteo ab und speichert sie direkt in der DB.
    Wird vom Dashboard aufgerufen, wenn noch keine Daten für eine Stadt vorhanden sind.
    """
    try:
        api_data = _fetch(city, lat, lon)
        _store(city, lat, lon, api_data, db)

        # Invalidate any stale chart cache and pre-warm in the background
        chart_cache.invalidate(city)
        threading.Thread(target=_prewarm_chart, args=(city,), daemon=True).start()

        return {"status": "ok", "city": city, "fetched_at": datetime.now(timezone.utc).isoformat()}
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="Open-Meteo API Timeout – bitte nochmal versuchen.")
    except requests.exceptions.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Open-Meteo Fehler: {e}")
    except Exception as e:
        logger.error(f"fetch-now failed for {city}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
