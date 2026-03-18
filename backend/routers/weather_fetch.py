"""
On-Demand Weather Fetch Router – ``POST /weather/fetch-now``
=============================================================

Provides a single endpoint that fetches fresh 7-day weather data from the
Open-Meteo API and stores it directly in the database. This endpoint exists
to support the frontend dashboard flow:

  1. User navigates to the dashboard with ``?city=X&lat=…&lon=…`` query params.
  2. The frontend calls ``GET /forecast/daily`` and receives a 404 if no data
     exists for that city yet.
  3. The frontend calls ``POST /weather/fetch-now`` to populate the database.
  4. Subsequent calls to ``/forecast/daily``, ``/forecast/hourly``, and the
     chart endpoints all succeed.

This router intentionally duplicates the Open-Meteo variable list and the
UPSERT SQL from the Airflow load task. The Airflow pipeline remains the
authoritative scheduled data source; this endpoint provides an on-demand
fallback so the dashboard is usable without waiting for the next Airflow run.

Side effects:
  - After a successful store, the in-memory chart cache is invalidated for the
    city so the next chart request generates a fresh image.
  - A background thread is spawned to pre-warm the default hourly chart
    (96 hours) by hitting ``GET /charts/hourly-plot`` internally. This avoids
    a slow first load for the user.

Dependencies:
  requests, sqlalchemy

Author: <project maintainer>
"""
import logging
import threading
import requests
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from database import get_db
from routers.auth import get_current_user
import chart_cache

router = APIRouter(prefix="/weather", tags=["Weather Fetch"])
logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# Daily variables to request from Open-Meteo.
# Matches the Airflow extract task variable list exactly.
DAILY_VARIABLES = [
    "temperature_2m_max", "temperature_2m_min", "precipitation_sum",
    "snowfall_sum", "wind_speed_10m_max", "wind_gusts_10m_max",
    "weather_code", "uv_index_max", "sunrise", "sunset",
]

# Hourly variables to request from Open-Meteo, including soil data.
HOURLY_VARIABLES = [
    "temperature_2m", "apparent_temperature", "precipitation",
    "rain", "snowfall", "wind_speed_10m", "wind_direction_10m",
    "relative_humidity_2m", "sunshine_duration", "weather_code", "is_day",
    "soil_temperature_0cm", "soil_temperature_6cm", "soil_temperature_18cm",
    "soil_moisture_0_to_1cm", "soil_moisture_1_to_3cm", "soil_moisture_3_to_9cm",
]


def _safe(lst, i, default=None):
    """Safely retrieve element ``i`` from a list, returning ``default`` on any error.

    Guards against two common failure modes when unpacking Open-Meteo API
    responses: the list being shorter than expected (``IndexError``) and the
    list value being ``None`` (which should not propagate to the database as a
    meaningful zero).

    Args:
        lst: Any list-like object, or ``None`` (in which case ``default`` is
             returned without raising).
        i: Zero-based index to retrieve.
        default: Value to return when ``lst[i]`` raises or is ``None``.
                 Defaults to ``None``.

    Returns:
        ``lst[i]`` when it exists and is not ``None``, otherwise ``default``.
    """
    try:
        v = lst[i]
        return v if v is not None else default
    except (IndexError, TypeError):
        return default


def _fetch(city: str, lat: float, lon: float) -> dict:
    """Call the Open-Meteo forecast API and return the raw JSON response.

    Requests 7 days of daily and hourly forecast data for the given coordinates.
    The timezone is fixed to ``"Europe/Berlin"`` so that time strings in the
    API response use local time.

    Args:
        city: City name (used only for log messages, not sent to the API).
        lat: Geographic latitude in decimal degrees (WGS-84).
        lon: Geographic longitude in decimal degrees (WGS-84).

    Returns:
        The parsed JSON response from Open-Meteo as a Python dict. The
        top-level keys include ``"daily"`` and ``"hourly"``, each containing
        a ``"time"`` list and one list per requested variable.

    Raises:
        requests.exceptions.Timeout: When the API does not respond within 30 s.
        requests.exceptions.HTTPError: When the API returns a non-2xx status.
    """
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
    """Persist Open-Meteo API data to the database using UPSERT statements.

    Iterates over the daily and hourly time arrays from the API response and
    executes one UPSERT per row. On conflict (same ``city`` + ``forecast_date``
    or ``forecast_time``) all mutable fields are overwritten with the latest
    values and ``created_at`` is reset to ``NOW()``.

    After storing the new data, all currently active alerts for the city are
    deactivated. Fresh alerts are generated by the Airflow pipeline; the
    on-demand fetch deliberately does not re-run alert evaluation to keep this
    endpoint fast.

    Args:
        city: City name used as the ``city`` column value in all inserted rows.
        lat: Latitude (logged; not stored by this function).
        lon: Longitude (logged; not stored by this function).
        api: Parsed Open-Meteo JSON response as returned by ``_fetch()``.
        db: SQLAlchemy session. The session is committed at the end of this
            function; the caller should not commit again.

    Side effects:
        - Inserts or updates rows in ``weather_daily`` and ``weather_hourly``.
        - Sets ``is_active = FALSE`` for all ``weather_alerts`` rows for the
          city.
        - Calls ``db.commit()``.
    """
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
    """Pre-generate the default hourly chart in a background thread.

    After storing fresh data, this function hits the hourly-plot chart endpoint
    to trigger rendering and populate the cache. This way the first user to load
    the dashboard sees the chart immediately rather than waiting for a
    potentially slow Matplotlib render.

    The function is designed to be run as a daemon thread; failures are logged
    at WARNING level but do not propagate.

    Args:
        city: City name passed as the ``?city=`` query parameter.
        hours: Number of hours for the default chart (default: 96 = 4 days).
    """
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
    _current_user = Depends(get_current_user),
):
    """Fetch fresh weather data from Open-Meteo and persist it to the database.

    This endpoint is called by the frontend dashboard when it detects that no
    data exists for the requested city or when the existing data is older than
    6 hours. It combines the extract and load steps of the ETL pipeline into a
    single synchronous HTTP call.

    Steps performed:
    1. Call Open-Meteo ``/v1/forecast`` for the given coordinates.
    2. UPSERT all daily and hourly records into the database.
    3. Invalidate the chart cache for the city.
    4. Spawn a background thread to pre-warm the 96-hour chart PNG.

    Args:
        city: Human-readable city name. Used as the key in the database and
              the chart cache.
        lat: Geographic latitude in decimal degrees (WGS-84).
        lon: Geographic longitude in decimal degrees (WGS-84).
        db: SQLAlchemy session injected by FastAPI's dependency system.
        _current_user: Authenticated user resolved by the ``get_current_user``
              dependency. The user object is not used in the function body;
              the dependency is present solely to enforce authentication.

    Returns:
        A JSON object confirming the operation::

            {"status": "ok", "city": "Freiburg", "fetched_at": "2025-06-01T12:00:00+00:00"}

    Raises:
        HTTPException(401): When no valid Bearer token is provided.
        HTTPException(504): When the Open-Meteo API does not respond within
            30 seconds.
        HTTPException(502): When the Open-Meteo API returns a non-2xx HTTP
            status code.
        HTTPException(500): For any other unexpected error during fetch or store.
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
