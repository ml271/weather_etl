"""
Weather ETL – FastAPI Backend Application
==========================================

Architecture Overview
---------------------
This module is the central entry point for the Weather ETL REST API. It ties
together all routers and owns the chart-generation endpoints, which are the
most complex part of the backend.

Request flow:
  Browser / Nginx
      │
      ▼
  FastAPI (this file + routers/)
      │   ├─ /auth/*          → routers/auth.py       (JWT register/login/me)
      │   ├─ /stations/*      → routers/stations.py   (city search autocomplete)
      │   ├─ /weather/*       → routers/weather_fetch.py (on-demand data fetch)
      │   ├─ /warnings/*      → routers/warnings.py   (user-defined alert rules)
      │   └─ /forecast, /alerts, /stats, /charts (defined here)
      │
      ▼
  PostgreSQL (via SQLAlchemy ORM + psycopg2)

Chart generation:
  /charts/hourly-plot  – 8-panel Matplotlib figure rendered to PNG in-process
  /charts/day-detail   – 6-panel single-day detail figure rendered to PNG
  Both endpoints use an in-memory TTL cache (chart_cache.py, TTL = 15 min) to
  avoid regenerating identical images on every page load.

Data pipeline (Airflow, separate process):
  extract.py → transform.py → load.py (runs hourly via weather_etl_pipeline DAG)
  check_warnings.py                    (runs every 2 h via check_weather_warnings DAG)

Environment variables consumed here:
  DEFAULT_CITY     – city used when the ?city= query parameter is absent
  ALLOWED_ORIGINS  – comma-separated list of permitted CORS origins

Author: <project maintainer>
"""

import io
import os
import logging
import yaml
from datetime import date, datetime, timezone
from typing import Optional

import matplotlib
import matplotlib.gridspec as mgs
matplotlib.use("Agg")  # Use the non-interactive Agg backend; must be set before importing pyplot
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
import numpy as np

from fastapi import FastAPI, Depends, HTTPException, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import desc, func, text, case

from database import get_db, engine
from models import WeatherDaily, WeatherHourly, WeatherAlert
from schemas import WeatherDailySchema, WeatherHourlySchema, WeatherAlertSchema, ForecastSummary
from routers import stations, weather_fetch, auth, warnings
from routers.auth import get_current_user
import chart_cache

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Weather ETL API",
    description="REST API für die Weather ETL Pipeline",
    version="1.0.0",
)

# Build the allowed-origins list at startup from the environment variable.
# The variable is expected to be a comma-separated string, e.g.:
#   ALLOWED_ORIGINS=http://localhost,http://localhost:80,https://myapp.example.com
_ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost,http://localhost:80").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(stations.router)
app.include_router(weather_fetch.router)
app.include_router(auth.router)
app.include_router(warnings.router)

# Fallback city used by every endpoint that accepts an optional ?city= param.
DEFAULT_CITY = os.getenv("DEFAULT_CITY", "Freiburg")

# ── General Alert helpers (dynamic, config-driven) ────────────────────────────

_ALERT_CONFIG_PATH = os.getenv("ALERT_CONFIG_PATH", "/app/config/alerts_config.yaml")

_OPS = {
    ">":  lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<":  lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
}


def _load_alert_rules() -> list:
    """Load enabled alert rules from alerts_config.yaml."""
    try:
        with open(_ALERT_CONFIG_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        return [r for r in config.get("alerts", []) if r.get("enabled", True)]
    except FileNotFoundError:
        logger.warning(f"Alert config not found at {_ALERT_CONFIG_PATH}")
        return []


def _evaluate_general_alerts(city: str, db: Session) -> list:
    """Evaluate alerts_config.yaml rules against the next 7 days of weather_daily
    for the given city. Returns a list of WeatherAlertSchema-compatible dicts."""
    rules = _load_alert_rules()
    if not rules:
        return []

    today = date.today()
    records = (
        db.query(WeatherDaily)
        .filter(WeatherDaily.city == city, WeatherDaily.forecast_date >= today)
        .order_by(WeatherDaily.forecast_date.asc())
        .limit(7)
        .all()
    )

    results = []
    alert_id = 1
    for record in records:
        for rule in rules:
            conditions = rule.get("conditions", {})
            triggered = {}
            all_met = True

            for field, spec in conditions.items():
                op        = spec.get("operator", ">")
                threshold = float(spec.get("value", 0))
                actual    = getattr(record, field, None)
                if actual is None:
                    all_met = False
                    break
                fn = _OPS.get(op)
                if fn and fn(float(actual), threshold):
                    triggered[field] = {"value": float(actual), "operator": op, "threshold": threshold}
                else:
                    all_met = False
                    break

            if all_met and triggered:
                results.append(WeatherAlertSchema(
                    id=alert_id,
                    city=city,
                    alert_name=rule["name"],
                    severity=rule["severity"],
                    message=rule["message"],
                    condition_met=triggered,
                    forecast_date=record.forecast_date,
                    is_active=True,
                    created_at=None,
                ))
                alert_id += 1

    return results


# ── Cache Management ──────────────────────────────────

_INTERNAL_TOKEN = os.getenv("INTERNAL_API_TOKEN", "")

def _require_internal_token(x_internal_token: str = Header(default="")):
    """FastAPI dependency that validates the internal API token.

    Used to restrict the ``POST /charts/cache-clear`` endpoint to trusted
    callers (the Airflow load task) rather than allowing any authenticated user
    to clear the cache. The token is compared using a plain string comparison;
    an empty ``INTERNAL_API_TOKEN`` disables the check and allows all callers.

    Args:
        x_internal_token: Value of the ``X-Internal-Token`` HTTP header,
            injected by FastAPI.

    Raises:
        HTTPException(403): When ``INTERNAL_API_TOKEN`` is set and the header
            value does not match.
    """
    if _INTERNAL_TOKEN and x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")

@app.post("/charts/cache-clear", tags=["Charts"])
def clear_chart_cache(city: str = Query(...), _auth = Depends(_require_internal_token)):
    """Invalidate all cached chart PNGs for a given city.

    Called by the Airflow load task after a successful data update so that the
    next dashboard request triggers a fresh chart render instead of serving a
    stale image.

    Args:
        city: The city name whose cache entries should be dropped. All cache
              keys that start with ``<city>:`` are removed atomically.

    Returns:
        A JSON object ``{"status": "ok", "city": "<city>"}`` confirming the
        invalidation.
    """
    chart_cache.invalidate(city)
    return {"status": "ok", "city": city}


# ── Health Check ──────────────────────────────────────

@app.get("/health", tags=["System"])
def health_check(db: Session = Depends(get_db)):
    """Return the liveness status of the API and its database connection.

    Executes a trivial ``SELECT 1`` against the database to confirm that the
    connection pool is operational. Intended for use by Docker health checks,
    load balancers, and uptime monitors.

    Args:
        db: SQLAlchemy session injected by FastAPI's dependency system.

    Returns:
        A JSON object with the following fields:

        - ``status`` (str): Always ``"ok"`` when the API process is alive.
        - ``timestamp`` (str): Current UTC time in ISO-8601 format.
        - ``database`` (str): ``"ok"`` if the DB ping succeeded, or an error
          message string if it failed.
        - ``default_city`` (str): The city name configured via ``DEFAULT_CITY``.
    """
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {str(e)}"
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": db_status,
        "default_city": DEFAULT_CITY,
    }


# ── Summary ───────────────────────────────────────────

@app.get("/summary", response_model=ForecastSummary, tags=["Forecast"])
def get_summary(
    city: str = Query(default=None),
    db: Session = Depends(get_db),
):
    """Return a dashboard summary for the given city.

    Aggregates today's daily forecast record, all currently active weather
    alerts (sorted by severity: danger first, then warning, then info), and
    the timestamp of the most recent data import.

    Args:
        city: City name to query. Falls back to ``DEFAULT_CITY`` when omitted.
        db: SQLAlchemy session injected by FastAPI's dependency system.

    Returns:
        A ``ForecastSummary`` object containing:

        - ``city`` (str): The resolved city name.
        - ``today`` (WeatherDailySchema | None): The nearest future daily
          forecast record. ``None`` if no data has been loaded for this city.
        - ``alerts_count`` (int): Total number of active alerts.
        - ``active_alerts`` (list[WeatherAlertSchema]): Active alerts sorted
          by severity (danger → warning → info) then by forecast date ascending.
        - ``last_updated`` (datetime | None): UTC timestamp of the newest row
          in ``weather_daily`` for this city. ``None`` if the city has no data.
    """
    city = city or DEFAULT_CITY

    # Fetch the nearest upcoming (or today's) daily record.
    today_record = (
        db.query(WeatherDaily)
        .filter(
            WeatherDaily.city == city,
            WeatherDaily.forecast_date >= date.today(),
        )
        .order_by(WeatherDaily.forecast_date.asc())
        .first()
    )

    # Evaluate general alerts dynamically from config for the requested city
    severity_order = {"danger": 0, "warning": 1, "info": 2}
    active_alerts = sorted(
        _evaluate_general_alerts(city, db),
        key=lambda a: (severity_order.get(a.severity, 9), a.forecast_date or date.min),
    )

    last_updated = (
        db.query(func.max(WeatherDaily.created_at))
        .filter(WeatherDaily.city == city)
        .scalar()
    )

    return ForecastSummary(
        city=city,
        today=WeatherDailySchema.model_validate(today_record) if today_record else None,
        alerts_count=len(active_alerts),
        active_alerts=active_alerts,
        last_updated=last_updated,
    )


# ── Daily Forecast ────────────────────────────────────

@app.get("/forecast/daily", response_model=list[WeatherDailySchema], tags=["Forecast"])
def get_daily_forecast(
    city: str = Query(default=None),
    days: int = Query(default=4, ge=1, le=7),
    db: Session = Depends(get_db),
):
    """Return the daily weather forecast for the next N days.

    Only returns records whose ``forecast_date`` is today or in the future,
    ordered chronologically. The default of 4 days matches the dashboard card
    strip; the maximum of 7 corresponds to one full week of Open-Meteo data.

    Args:
        city: City name to query. Falls back to ``DEFAULT_CITY`` when omitted.
        days: Number of daily records to return. Must be between 1 and 7
              inclusive (default: 4).
        db: SQLAlchemy session injected by FastAPI's dependency system.

    Returns:
        A list of ``WeatherDailySchema`` objects ordered by ``forecast_date``
        ascending. Each object includes computed fields ``weather_description``
        and ``weather_icon`` derived from the WMO weather code.

    Raises:
        HTTPException(404): When no daily records exist for ``city``. This
            typically means the Airflow ETL pipeline has not run yet for this
            city, or the city name does not match any stored data.
    """
    city = city or DEFAULT_CITY

    records = (
        db.query(WeatherDaily)
        .filter(
            WeatherDaily.city == city,
            WeatherDaily.forecast_date >= date.today(),
        )
        .order_by(WeatherDaily.forecast_date.asc())
        .limit(days)
        .all()
    )

    if not records:
        raise HTTPException(
            status_code=404,
            detail=f"Keine Daten für '{city}'. Bitte zuerst den Airflow DAG triggern.",
        )

    return [WeatherDailySchema.model_validate(r) for r in records]


# ── Hourly Forecast ───────────────────────────────────

@app.get("/forecast/hourly", response_model=list[WeatherHourlySchema], tags=["Forecast"])
def get_hourly_forecast(
    city: str = Query(default=None),
    hours: int = Query(default=24, ge=1, le=168),
    db: Session = Depends(get_db),
):
    """Return the hourly weather forecast starting from the current UTC time.

    Filters rows whose ``forecast_time`` is greater than or equal to now, so
    past hours from the current day are never returned. The maximum window of
    168 hours corresponds to 7 full days (the Open-Meteo forecast horizon).

    Args:
        city: City name to query. Falls back to ``DEFAULT_CITY`` when omitted.
        hours: Number of hourly slots to return. Must be between 1 and 168
               inclusive (default: 24).
        db: SQLAlchemy session injected by FastAPI's dependency system.

    Returns:
        A list of ``WeatherHourlySchema`` objects ordered by ``forecast_time``
        ascending, starting from the nearest future hour.

    Raises:
        HTTPException(404): When no hourly records exist for ``city`` from the
            current time onward.
    """
    city = city or DEFAULT_CITY
    now  = datetime.now(timezone.utc)

    records = (
        db.query(WeatherHourly)
        .filter(WeatherHourly.city == city, WeatherHourly.forecast_time >= now)
        .order_by(WeatherHourly.forecast_time.asc())
        .limit(hours)
        .all()
    )

    if not records:
        raise HTTPException(status_code=404, detail=f"Keine stündlichen Daten für '{city}'.")

    return [WeatherHourlySchema.model_validate(r) for r in records]


# ── Alerts ────────────────────────────────────────────

@app.get("/alerts", response_model=list[WeatherAlertSchema], tags=["Alerts"])
def get_alerts(
    city: str = Query(default=None),
    active_only: bool = Query(default=True),
    severity: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Return general weather alerts for a city, evaluated dynamically from
    alerts_config.yaml against the current weather_daily forecast data.

    Alerts are computed on-demand for the requested city, so every station
    gets correctly evaluated regardless of which city the Airflow ETL runs for.

    Args:
        city: City name to query. Falls back to ``DEFAULT_CITY`` when omitted.
        active_only: Kept for API compatibility; all dynamic alerts are active
            by definition and this parameter has no effect.
        severity: Optional filter by severity level (``"info"``, ``"warning"``,
            ``"danger"``). When omitted, alerts of all severities are returned.
        db: SQLAlchemy session injected by FastAPI's dependency system.

    Returns:
        A list of ``WeatherAlertSchema`` objects, one per triggered rule per
        forecast day, sorted by severity (danger first) then date ascending.
    """
    city = city or DEFAULT_CITY
    alerts = _evaluate_general_alerts(city, db)
    if severity:
        alerts = [a for a in alerts if a.severity == severity]
    severity_order = {"danger": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda a: (severity_order.get(a.severity, 9), a.forecast_date or date.min))
    return alerts


@app.get("/alerts/history", response_model=list[WeatherAlertSchema], tags=["Alerts"])
def get_alert_history(
    city: str = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Return a paginated history of all alerts (active and deactivated) for a city.

    Unlike ``GET /alerts``, this endpoint always includes deactivated alerts,
    making it suitable for audit logs or historical analysis.

    Args:
        city: City name to query. Falls back to ``DEFAULT_CITY`` when omitted.
        limit: Maximum number of alert records to return. Must be between 1
               and 200 inclusive (default: 50).
        db: SQLAlchemy session injected by FastAPI's dependency system.

    Returns:
        A list of up to ``limit`` ``WeatherAlertSchema`` objects ordered by
        ``created_at`` descending (newest first).
    """
    city = city or DEFAULT_CITY
    alerts = (
        db.query(WeatherAlert)
        .filter(WeatherAlert.city == city)
        .order_by(desc(WeatherAlert.created_at))
        .limit(limit)
        .all()
    )
    return [WeatherAlertSchema.model_validate(a) for a in alerts]


# ── Stats ─────────────────────────────────────────────

@app.get("/stats/temperature", tags=["Stats"])
def get_temperature_chart_data(
    city: str = Query(default=None),
    db: Session = Depends(get_db),
):
    """Return structured JSON data for the 4-day temperature/precipitation/wind chart.

    This endpoint is consumed by the frontend's Chart.js bar/line chart. It
    returns the next 4 days of daily data (matching the default forecast strip
    length) in a shape that can be directly passed to Chart.js ``datasets``.

    Args:
        city: City name to query. Falls back to ``DEFAULT_CITY`` when omitted.
        db: SQLAlchemy session injected by FastAPI's dependency system.

    Returns:
        A JSON object with the following structure::

            {
              "city": "Freiburg",
              "labels": ["2025-06-01", "2025-06-02", ...],
              "datasets": {
                "temperature_max":  [28.4, 30.1, ...],
                "temperature_min":  [14.2, 16.0, ...],
                "precipitation":    [0.0,  12.3, ...],
                "wind_speed":       [18.0, 22.5, ...]
              }
            }

        ``None`` values indicate that Open-Meteo did not return data for that
        slot. ``precipitation`` falls back to ``0`` instead of ``None`` because
        the charting library treats ``null`` differently for bar charts.

    Raises:
        HTTPException(404): When no daily records exist for ``city``.
    """
    city = city or DEFAULT_CITY
    records = (
        db.query(WeatherDaily)
        .filter(WeatherDaily.city == city, WeatherDaily.forecast_date >= date.today())
        .order_by(WeatherDaily.forecast_date.asc())
        .limit(4)  # Matches the default forecast strip width shown in the dashboard
        .all()
    )
    if not records:
        raise HTTPException(status_code=404, detail=f"Keine Daten für '{city}'.")
    return {
        "city": city,
        "labels": [str(r.forecast_date) for r in records],
        "datasets": {
            "temperature_max": [float(r.temperature_max) if r.temperature_max else None for r in records],
            "temperature_min": [float(r.temperature_min) if r.temperature_min else None for r in records],
            "precipitation":   [float(r.precipitation_sum) if r.precipitation_sum else 0 for r in records],
            "wind_speed":      [float(r.wind_speed_max) if r.wind_speed_max else None for r in records],
        },
    }


@app.get("/stats/hourly-temp", tags=["Stats"])
def get_hourly_temp_chart(
    city: str = Query(default=None),
    hours: int = Query(default=48, ge=1, le=168),
    db: Session = Depends(get_db),
):
    """Return structured JSON data for the hourly temperature/precipitation sparkline chart.

    Returns data starting from the current UTC time. Timestamps are formatted
    as ``"dd.mm HH:MM"`` (CET-naive) for display on the x-axis.

    Args:
        city: City name to query. Falls back to ``DEFAULT_CITY`` when omitted.
        hours: Number of hourly slots to return. Must be between 1 and 168
               inclusive (default: 48).
        db: SQLAlchemy session injected by FastAPI's dependency system.

    Returns:
        A JSON object with the following structure::

            {
              "city": "Freiburg",
              "labels":        ["01.06 13:00", "01.06 14:00", ...],
              "temperature":   [22.3, 23.1, ...],
              "feels_like":    [21.0, 22.5, ...],
              "precipitation": [0.0,  0.0,  ...]
            }

        ``None`` values indicate missing data from the source API.
        ``precipitation`` falls back to ``0`` because ``null`` bars are
        invisible in Chart.js.
    """
    city = city or DEFAULT_CITY
    now  = datetime.now(timezone.utc)
    records = (
        db.query(WeatherHourly)
        .filter(WeatherHourly.city == city, WeatherHourly.forecast_time >= now)
        .order_by(WeatherHourly.forecast_time.asc())
        .limit(hours)
        .all()
    )
    return {
        "city": city,
        "labels":        [r.forecast_time.strftime("%d.%m %H:%M") for r in records],
        "temperature":   [float(r.temperature) if r.temperature else None for r in records],
        "feels_like":    [float(r.feels_like) if r.feels_like else None for r in records],
        "precipitation": [float(r.precipitation) if r.precipitation else 0 for r in records],
    }


# ── Day Detail Plot (Matplotlib PNG, single day) ──────

@app.get("/charts/day-detail", tags=["Charts"])
def get_day_detail_plot(
    date_str: str = Query(alias="date"),
    city: str = Query(default=None),
    db: Session = Depends(get_db),
):
    """Generate and return a 6-panel PNG chart for a single calendar day.

    Fetches all hourly records for the requested date and renders them into a
    Matplotlib figure with the following panels (top to bottom):

    1. Temperature [°C] — line chart with optional daily max/min scatter dots
    2. Relative humidity [%] — filled line chart
    3. Wind speed [km/h] — filled line chart
    4. Wind direction — narrow quiver (arrow) strip, one arrow per 3 hours
    5. Precipitation [mm] — bar chart
    6. Sunshine duration [min/h] — bar chart

    The figure uses a dark blue-grey colour palette consistent with the main
    hourly plot. Timestamps on the x-axis represent CET (UTC+1); the UTC
    conversion is a fixed +1 h offset (no DST handling).

    Results are cached in the in-memory chart cache under the key
    ``"<city>:day:<date_str>"``. Cached images are served with ``X-Cache: HIT``;
    freshly rendered images with ``X-Cache: MISS``.

    Args:
        date_str: The date to render, in ISO-8601 format ``YYYY-MM-DD``
                  (passed as the ``date`` query parameter, e.g. ``?date=2025-06-01``).
        city: City name to query. Falls back to ``DEFAULT_CITY`` when omitted.
        db: SQLAlchemy session injected by FastAPI's dependency system.

    Returns:
        A ``Response`` with ``Content-Type: image/png`` containing the rendered
        chart at 100 dpi, 8 × 6 inches (800 × 600 px).

    Raises:
        HTTPException(400): When ``date_str`` is not a valid ISO-8601 date.
        HTTPException(404): When no hourly records exist for ``city`` on the
            requested date.
    """
    from datetime import timedelta, date as _date

    city = city or DEFAULT_CITY

    # ── Cache check ──────────────────────────────────────
    cache_key = f"{city}:day:{date_str}"
    cached = chart_cache.get(cache_key)
    if cached:
        return Response(content=cached, media_type="image/png",
                        headers={"Cache-Control": "no-cache, max-age=0", "X-Cache": "HIT"})

    try:
        target_date = _date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format, use YYYY-MM-DD.")

    # Query all hours within the target calendar day (UTC midnight to 23:59:59).
    day_start = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=timezone.utc)
    day_end   = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59, tzinfo=timezone.utc)

    records = (
        db.query(WeatherHourly)
        .filter(
            WeatherHourly.city == city,
            WeatherHourly.forecast_time >= day_start,
            WeatherHourly.forecast_time <= day_end,
        )
        .order_by(WeatherHourly.forecast_time.asc())
        .all()
    )

    if not records:
        raise HTTPException(status_code=404, detail=f"Keine Stundendaten für {date_str}.")

    # Also load the daily record for the max/min scatter dots.
    daily = (
        db.query(WeatherDaily)
        .filter(WeatherDaily.city == city, WeatherDaily.forecast_date == target_date)
        .first()
    )

    # Convert UTC times to CET (UTC+1) naive datetimes. A fixed +1 h offset is
    # used intentionally so that x-axis labels always read as clock hours.
    CET   = timedelta(hours=1)
    times    = [r.forecast_time.replace(tzinfo=None) + CET for r in records]
    temp     = [float(r.temperature)       if r.temperature      is not None else np.nan for r in records]
    humidity = [float(r.humidity)          if r.humidity         is not None else np.nan for r in records]
    ws       = [float(r.wind_speed)        if r.wind_speed       is not None else 0.0    for r in records]
    wd       = [float(r.wind_direction)    if r.wind_direction   is not None else 0.0    for r in records]
    precip   = [float(r.precipitation)     if r.precipitation    is not None else 0.0    for r in records]
    # sunshine_duration is stored in seconds per hour; divide by 60 for minutes/hour display
    sunshine = [float(r.sunshine_duration) if r.sunshine_duration is not None else 0.0   for r in records]

    # Place daily max/min dots at 12:00 noon local time so they sit within the
    # visible x-axis range on days where data starts later than midnight.
    d_noon_max, d_temp_max = [], []
    d_noon_min, d_temp_min = [], []
    if daily:
        noon = datetime(target_date.year, target_date.month, target_date.day, 12, 0, 0)
        if times[0] <= noon <= times[-1]:
            if daily.temperature_max is not None:
                d_noon_max.append(noon); d_temp_max.append(float(daily.temperature_max))
            if daily.temperature_min is not None:
                d_noon_min.append(noon); d_temp_min.append(float(daily.temperature_min))

    # ── Colour palette (dark blue-grey theme) ──────────
    BG      = "#080c12"   # Page / figure background
    SURFACE = "#0d1520"   # Panel background
    GRID_C  = "#1a2a3f"   # Grid lines and spines
    DIV_C   = "#2a3d58"   # Midnight divider lines
    TEXT    = "#c8d8f0"   # Primary text
    DIM     = "#4a6080"   # Axis tick labels and secondary text
    WARM    = "#ff9d4a"   # Temperature line
    HUMID   = "#4adfb8"   # Humidity line
    WIND_C  = "#a78bfa"   # Wind speed fill/line
    WIND_D  = "#c4b5fd"   # Wind direction arrows
    PRECIP  = "#4a9eff"   # Precipitation bars
    SUN_C   = "#ffd950"   # Sunshine duration bars
    DOT_MAX = "#ff5566"   # Daily temperature maximum marker
    DOT_MIN = "#4ad4ff"   # Daily temperature minimum marker

    # Bar width in Matplotlib date units: 0.8 h expressed as a fraction of a day
    BAR_W = 0.8 / 24.0

    _WD_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    title_date = target_date.strftime("%d.%m.%Y")
    title_day  = _WD_EN[target_date.weekday()]

    # 6 panels with height ratios tuned so temperature gets the most vertical space
    fig, axes = plt.subplots(
        6, 1,
        figsize=(8, 6),
        gridspec_kw={"height_ratios": [3, 2, 2.5, 0.7, 1.5, 1.5], "hspace": 0.58},
        sharex=True,
        facecolor=BG,
    )

    def hour_fmt(x, pos):
        """Format x-axis tick as a zero-padded hour string every 4 hours."""
        h = mdates.num2date(x).hour
        return f"{h:02d}" if h % 4 == 0 else ""

    def style_ax(ax, ylabel, ylabel_color=TEXT):
        """Apply consistent dark-theme styling to an axes object.

        Sets the face colour, spine colour, grid lines, and tick parameters
        so that all panels share the same visual appearance.

        Args:
            ax: The Matplotlib ``Axes`` object to style.
            ylabel: Label text for the y-axis.
            ylabel_color: Hex colour string for the y-axis label (defaults to
                primary text colour).
        """
        ax.set_facecolor(SURFACE)
        ax.spines[:].set_color(GRID_C)
        ax.grid(True, color=GRID_C, linewidth=0.5, linestyle="--", alpha=0.5, which="major", axis="y")
        ax.set_ylabel(ylabel, color=ylabel_color, fontsize=8, labelpad=6)
        ax.yaxis.label.set_color(ylabel_color)
        ax.tick_params(colors=DIM, labelsize=7, which="both")
        ax.xaxis.set_minor_locator(mdates.HourLocator(interval=1))
        ax.xaxis.set_major_locator(mdates.HourLocator(byhour=range(0, 24, 2)))
        ax.xaxis.set_major_formatter(mticker.FuncFormatter(hour_fmt))
        ax.tick_params(axis="x", which="minor", length=3, color=DIM, labelbottom=False)
        ax.tick_params(axis="x", which="major", length=6, color=DIM, labelbottom=True, labelsize=6, pad=3)

    # ── Panel 1: Temperature ──
    ax1 = axes[0]
    ax1.plot(times, temp, color=WARM, linewidth=1.8, zorder=3)
    ax1.fill_between(times, temp, alpha=0.07, color=WARM, zorder=2)
    if d_noon_max:
        ax1.scatter(d_noon_max, d_temp_max, color=DOT_MAX, s=55, zorder=5,
                    edgecolors="white", linewidths=0.6, label="Tagesmax")
    if d_noon_min:
        ax1.scatter(d_noon_min, d_temp_min, color=DOT_MIN, s=55, zorder=5,
                    edgecolors="white", linewidths=0.6, label="Tagesmin")
    style_ax(ax1, "Temp  [°C]", WARM)
    ax1.tick_params(axis="x", top=True, labeltop=False, which="major", length=6, color=DIM)
    ax1.tick_params(axis="x", top=True, which="minor", length=3, color=DIM)
    ax1.spines["top"].set_color(GRID_C)

    def _hour_fmt_top(x, pos):
        """Format top-axis labels identically to the bottom axis."""
        h = mdates.num2date(x).hour
        return f"{h:02d}" if h % 4 == 0 else ""

    # Secondary top axis shows the same hour ticks for readability at both edges
    _ax1_top = ax1.secondary_xaxis("top")
    _ax1_top.xaxis.set_minor_locator(mdates.HourLocator(interval=1))
    _ax1_top.xaxis.set_major_locator(mdates.HourLocator(byhour=range(0, 24, 2)))
    _ax1_top.xaxis.set_major_formatter(mticker.FuncFormatter(_hour_fmt_top))
    _ax1_top.tick_params(axis="x", which="major", length=0, labelsize=6, colors=DIM, pad=4)
    _ax1_top.tick_params(axis="x", which="minor", length=0, labeltop=False)
    _ax1_top.spines["top"].set_visible(False)

    ax1.set_title(
        f"{city.upper()}  ·  {title_day.upper()},  {title_date}",
        color=TEXT, fontsize=9, fontfamily="monospace", loc="left", pad=52,
    )

    # ── Panel 2: Humidity ──
    ax2 = axes[1]
    ax2.plot(times, humidity, color=HUMID, linewidth=1.6, zorder=3)
    ax2.fill_between(times, humidity, alpha=0.08, color=HUMID, zorder=2)
    ax2.set_ylim(0, 105)  # Cap at 105 to give the line a little breathing room at 100 %
    style_ax(ax2, "Humidity  [%]", HUMID)

    # ── Panel 3: Wind Speed ──
    ax3 = axes[2]
    ax3.fill_between(times, ws, alpha=0.15, color=WIND_C, zorder=2)
    ax3.plot(times, ws, color=WIND_C, linewidth=1.6, zorder=3)
    ax3.set_ylim(bottom=0)
    style_ax(ax3, "Wind  [km/h]", WIND_C)

    # ── Panel 4: Wind Direction (narrow quiver strip) ──
    # One arrow every 3 h to avoid visual clutter. The meteorological convention
    # is "direction wind is coming FROM", so the arrow vector is negated:
    #   u = -sin(dir°), v = -cos(dir°) → arrow points in the "blowing to" direction
    ax4 = axes[3]
    style_ax(ax4, "Dir", WIND_D)
    ax4.set_ylim(-1.2, 1.2)
    ax4.set_yticks([])
    ax4.axhline(0, color=GRID_C, linewidth=0.5, zorder=1)
    t_sub  = times[::3]
    wd_sub = np.array(wd[::3])
    u = -np.sin(np.radians(wd_sub))
    v = -np.cos(np.radians(wd_sub))
    ax4.quiver(t_sub, np.zeros(len(t_sub)), u, v,
               color=WIND_D, alpha=0.9, scale=28, width=0.0015,
               headwidth=3, headlength=3.5, zorder=4, pivot="mid")

    # ── Panel 5: Precipitation ──
    ax5 = axes[4]
    ax5.bar(times, precip, width=BAR_W, color=PRECIP, alpha=0.85, zorder=3, align="center")
    ax5.set_ylim(bottom=0)
    style_ax(ax5, "Precip  [mm]", PRECIP)

    # ── Panel 6: Sunshine Duration ──
    # sunshine is stored as seconds/hour in the DB; convert to minutes/hour for display
    ax6 = axes[5]
    ax6.bar(times, [s / 60.0 for s in sunshine], width=BAR_W, color=SUN_C, alpha=0.85, zorder=3, align="center")
    ax6.set_ylim(0, 65)  # max is 60 min/h; cap at 65 to prevent bars from touching the top spine
    style_ax(ax6, "Sunshine\n[min/h]", SUN_C)
    ax6.set_xlabel("Zeit  (UTC+1 / CET)", color=DIM, fontsize=7.5)
    # Annotate total daily sunshine hours in the center of the panel
    total_sun_h = sum(sunshine) / 3600.0
    if times:
        mid_x = times[len(times) // 2]
        ax6.text(mid_x, 50, f"{total_sun_h:.1f} h", color=SUN_C, fontsize=9, fontweight="bold",
                 ha="center", va="center",
                 bbox=dict(boxstyle="round,pad=0.25", facecolor="#080c12", alpha=0.75, edgecolor="none"))

    axes[0].set_xlim(times[0], times[-1])
    fig.patch.set_facecolor(BG)
    plt.tight_layout(pad=0.8, rect=[0.10, 0.01, 1.0, 0.97])

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    chart_data = buf.getvalue()
    chart_cache.put(cache_key, chart_data)

    return Response(
        content=chart_data,
        media_type="image/png",
        headers={"Cache-Control": "no-cache, max-age=0", "X-Cache": "MISS"},
    )


# ── Hourly Plot (Matplotlib PNG) ──────────────────────

@app.get("/charts/hourly-plot", tags=["Charts"])
def get_hourly_plot(
    city: str = Query(default=None),
    hours: int = Query(default=96, ge=6, le=168),
    soil_t: str = Query(default="0,6,18"),
    soil_m: str = Query(default="0-1,1-3,3-9"),
    db: Session = Depends(get_db),
):
    """Generate and return an 8-panel multi-day hourly forecast PNG chart.

    Fetches hourly records from the current UTC time forward and renders them
    using a nested Matplotlib GridSpec layout into 4 paired panel groups:

    - Pair 1: Temperature [°C] + Relative humidity [%]
    - Pair 2: Wind speed [km/h] + Wind direction (quiver arrows)
    - Pair 3: Precipitation [mm] + Sunshine duration [min/h]
    - Pair 4: Soil temperature [°C] + Soil moisture [m³/m³]

    Within each pair the two panels share an x-axis and have a minimal gap
    between them (``hspace=0.2``) so they visually read as a single unit.

    The bottom-most panel (ax8, soil moisture) carries the full day-label
    formatter: at the midpoint of each calendar day's visible range the tick
    label shows ``"HH\nWeekday  DD.MM"`` instead of just ``"HH"``.

    Midnight transitions are highlighted with vertical divider lines on every
    panel.

    Daily max/min temperature values from ``weather_daily`` are overlaid as
    scatter dots on the temperature panel, positioned at 12:00 noon local time
    for each day that falls within the query window.

    Results are cached under the key
    ``"<city>:hourly:<hours>:st<soil_t>:sm<soil_m>"``. The cache key encodes
    all query parameters that affect the rendered output so that different
    depth selections produce distinct cache entries.

    Args:
        city: City name to query. Falls back to ``DEFAULT_CITY`` when omitted.
        hours: Number of hourly slots to render. Must be between 6 and 168
               inclusive (default: 96, i.e. 4 days).
        soil_t: Comma-separated list of soil temperature depths (cm) to plot.
                Accepted values are ``"0"``, ``"6"``, and ``"18"``.
                Example: ``"0,18"`` renders only the surface and mid layers.
        soil_m: Comma-separated list of soil moisture depth ranges (cm) to
                plot. Accepted values are ``"0-1"``, ``"1-3"``, and ``"3-9"``.
                Example: ``"0-1"`` renders only the surface moisture layer.
        db: SQLAlchemy session injected by FastAPI's dependency system.

    Returns:
        A ``Response`` with ``Content-Type: image/png`` containing the rendered
        chart at 100 dpi, 8 × 8 inches (800 × 800 px).

    Raises:
        HTTPException(404): When no hourly records exist for ``city`` from the
            current time onward.
    """
    from datetime import timedelta

    city = city or DEFAULT_CITY

    # Build cache key from all parameters that determine the rendered image.
    # Sorting the depth sets ensures that "0,6" and "6,0" produce the same key.
    show_st = set(soil_t.split(","))
    show_sm = set(soil_m.split(","))
    cache_key = f"{city}:hourly:{hours}:st{','.join(sorted(show_st))}:sm{','.join(sorted(show_sm))}"
    cached = chart_cache.get(cache_key)
    if cached:
        return Response(content=cached, media_type="image/png",
                        headers={"Cache-Control": "no-cache, max-age=0", "X-Cache": "HIT"})
    now  = datetime.now(timezone.utc)

    records = (
        db.query(WeatherHourly)
        .filter(WeatherHourly.city == city, WeatherHourly.forecast_time >= now)
        .order_by(WeatherHourly.forecast_time.asc())
        .limit(hours)
        .all()
    )

    if not records:
        raise HTTPException(status_code=404, detail=f"Keine stündlichen Daten für '{city}'.")

    # Load daily records covering the same date range so we can overlay
    # temperature max/min scatter dots on panel 1.
    daily_records = (
        db.query(WeatherDaily)
        .filter(
            WeatherDaily.city == city,
            WeatherDaily.forecast_date >= records[0].forecast_time.date(),
            WeatherDaily.forecast_date <= records[-1].forecast_time.date(),
        )
        .order_by(WeatherDaily.forecast_date.asc())
        .all()
    )

    # Convert UTC timestamps to CET (UTC+1) naive datetimes. A fixed +1 h
    # offset is used rather than a timezone-aware conversion so that Matplotlib
    # date formatters produce clean integer hour values.
    CET = timedelta(hours=1)
    times    = [r.forecast_time.replace(tzinfo=None) + CET for r in records]
    temp     = [float(r.temperature)       if r.temperature      is not None else np.nan for r in records]
    humidity = [float(r.humidity)          if r.humidity         is not None else np.nan for r in records]
    ws       = [float(r.wind_speed)        if r.wind_speed       is not None else 0.0    for r in records]
    wd       = [float(r.wind_direction)    if r.wind_direction   is not None else 0.0    for r in records]
    precip   = [float(r.precipitation)     if r.precipitation    is not None else 0.0    for r in records]
    # sunshine_duration is stored in seconds per hour; converted to min/h before plotting
    sunshine = [float(r.sunshine_duration) if r.sunshine_duration is not None else 0.0   for r in records]

    # Soil data — getattr guards against rows that pre-date the soil column migration
    s_t0  = [float(r.soil_temperature_0cm)  if getattr(r, "soil_temperature_0cm",  None) is not None else np.nan for r in records]
    s_t6  = [float(r.soil_temperature_6cm)  if getattr(r, "soil_temperature_6cm",  None) is not None else np.nan for r in records]
    s_t18 = [float(r.soil_temperature_18cm) if getattr(r, "soil_temperature_18cm", None) is not None else np.nan for r in records]
    s_m01 = [float(r.soil_moisture_0_1cm)   if getattr(r, "soil_moisture_0_1cm",   None) is not None else np.nan for r in records]
    s_m13 = [float(r.soil_moisture_1_3cm)   if getattr(r, "soil_moisture_1_3cm",   None) is not None else np.nan for r in records]
    s_m39 = [float(r.soil_moisture_3_9cm)   if getattr(r, "soil_moisture_3_9cm",   None) is not None else np.nan for r in records]

    # Daily max/min dots placed at noon local time for each day in the range
    d_noon_max, d_temp_max = [], []
    d_noon_min, d_temp_min = [], []
    for dr in daily_records:
        noon = datetime(dr.forecast_date.year, dr.forecast_date.month, dr.forecast_date.day, 12, 0, 0)
        if times[0] <= noon <= times[-1]:
            if dr.temperature_max is not None:
                d_noon_max.append(noon)
                d_temp_max.append(float(dr.temperature_max))
            if dr.temperature_min is not None:
                d_noon_min.append(noon)
                d_temp_min.append(float(dr.temperature_min))

    # ── Colour palette (same dark theme as day-detail) ──
    BG      = "#080c12"
    SURFACE = "#0d1520"
    GRID_C  = "#1a2a3f"
    DIV_C   = "#2a3d58"   # Midnight vertical divider
    TEXT    = "#c8d8f0"
    DIM     = "#4a6080"
    WARM    = "#ff9d4a"
    HUMID   = "#4adfb8"
    WIND_C  = "#a78bfa"
    WIND_D  = "#c4b5fd"
    PRECIP  = "#4a9eff"
    SUN_C   = "#ffd950"
    DOT_MAX = "#ff5566"
    DOT_MIN  = "#4ad4ff"
    SOIL_T0  = "#e8a05c"   # Surface soil temperature (warm sandy hue)
    SOIL_T6  = "#c07830"   # Shallow soil temperature (earth brown)
    SOIL_T18 = "#8b5520"   # Mid-depth soil temperature (dark earth)
    SOIL_M0  = "#5bb8f5"   # Surface soil moisture (light blue)
    SOIL_M1  = "#3a8cc4"   # Shallow moisture (medium blue)
    SOIL_M3  = "#1e5f8a"   # Deeper moisture (dark blue)

    # Bar width in Matplotlib date units: 0.8 h expressed as a fraction of a day
    BAR_W = 0.8 / 24.0

    # Compute midnight timestamps (local CET) within the data range for divider lines
    midnights = []
    if times:
        md = datetime(times[0].year, times[0].month, times[0].day) + timedelta(days=1)
        while md <= times[-1]:
            midnights.append(md)
            md += timedelta(days=1)

    # Nested GridSpec: 4 paired groups with small intra-pair hspace.
    # Pair 1 → ax1 (Temp) + ax2 (Humidity)
    # Pair 2 → ax3 (Wind speed) + ax4 (Wind direction)
    # Pair 3 → ax5 (Precipitation) + ax6 (Sunshine)
    # Pair 4 → ax7 (Soil Temperature) + ax8 (Soil Moisture)
    fig = plt.figure(figsize=(8, 8), facecolor=BG)
    _outer = mgs.GridSpec(4, 1, figure=fig, hspace=0.22)
    _p1 = mgs.GridSpecFromSubplotSpec(2, 1, subplot_spec=_outer[0], hspace=0.2, height_ratios=[3, 2])
    _p2 = mgs.GridSpecFromSubplotSpec(2, 1, subplot_spec=_outer[1], hspace=0.2, height_ratios=[2.5, 0.7])
    _p3 = mgs.GridSpecFromSubplotSpec(2, 1, subplot_spec=_outer[2], hspace=0.2, height_ratios=[1.5, 1.5])
    _p4 = mgs.GridSpecFromSubplotSpec(2, 1, subplot_spec=_outer[3], hspace=0.2, height_ratios=[1.5, 1.5])
    ax1 = fig.add_subplot(_p1[0])
    ax2 = fig.add_subplot(_p1[1], sharex=ax1)
    ax3 = fig.add_subplot(_p2[0])
    ax4 = fig.add_subplot(_p2[1], sharex=ax3)
    ax5 = fig.add_subplot(_p3[0])
    ax6 = fig.add_subplot(_p3[1], sharex=ax5)
    ax7 = fig.add_subplot(_p4[0])
    ax8 = fig.add_subplot(_p4[1], sharex=ax7)
    axes = [ax1, ax2, ax3, ax4, ax5, ax6, ax7, ax8]

    _WD_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    # Pre-compute the "label hour" for each calendar day: the midpoint of the
    # visible window for that day, snapped to the nearest 4-h tick. This hour
    # receives an extended label ("HH\nWeekday  DD.MM") on the bottom x-axis.
    from datetime import date as _date
    day_label_hours: dict = {}
    _check = times[0].date()
    while _check <= times[-1].date():
        _ds = max(times[0], datetime(_check.year, _check.month, _check.day, 0, 0))
        _de = min(times[-1], datetime(_check.year, _check.month, _check.day, 23, 59))
        _mid_h = (_ds.hour + _ds.minute / 60.0 + _de.hour + _de.minute / 60.0) / 2.0
        # Snap to the nearest even-numbered 4-hour mark so the label falls on an existing tick
        _lh = int(_mid_h / 4.0 + 0.5) * 4
        _lh = max(0, min(20, _lh))
        day_label_hours[_check] = _lh
        _check += timedelta(days=1)

    def hour_fmt_plain(x, pos):
        """Return zero-padded hour string every 4 hours; empty string otherwise."""
        h = mdates.num2date(x).hour
        return f"{h:02d}" if h % 4 == 0 else ""

    def hour_fmt_with_day(x, pos):
        """Return extended tick label with weekday+date at the per-day label hour.

        For most ticks this behaves identically to ``hour_fmt_plain``. At the
        pre-computed label hour for each calendar day it emits a two-line string:
        ``"HH\\nWeekday  DD.MM"`` so the day annotation appears directly below
        the hour number on the bottom-most panel.
        """
        dt = mdates.num2date(x)
        h  = dt.hour
        lh = day_label_hours.get(dt.date())
        if lh is not None and h == lh:
            return f"{h:02d}\n{_WD_EN[dt.weekday()]}  {dt.strftime('%d.%m')}"
        return f"{h:02d}" if h % 4 == 0 else ""

    def style_ax(ax, ylabel, ylabel_color=TEXT):
        """Apply consistent dark-theme styling and add midnight dividers.

        Args:
            ax: The Matplotlib ``Axes`` object to style.
            ylabel: Y-axis label text.
            ylabel_color: Hex colour string for the y-axis label.
        """
        ax.set_facecolor(SURFACE)
        ax.spines[:].set_color(GRID_C)
        ax.grid(True, color=GRID_C, linewidth=0.5, linestyle="--", alpha=0.5, which="major", axis="y")
        ax.set_ylabel(ylabel, color=ylabel_color, fontsize=8, labelpad=6)
        ax.yaxis.label.set_color(ylabel_color)
        ax.tick_params(colors=DIM, labelsize=7, which="both")
        ax.xaxis.set_minor_locator(mdates.HourLocator(interval=1))
        ax.xaxis.set_major_locator(mdates.HourLocator(byhour=range(0, 24, 2)))
        ax.xaxis.set_major_formatter(mticker.FuncFormatter(hour_fmt_plain))
        ax.tick_params(axis="x", which="minor", length=3, color=DIM, labelbottom=False)
        ax.tick_params(axis="x", which="major", length=6, color=DIM, labelbottom=True, labelsize=6, pad=3)
        for md in midnights:
            ax.axvline(md, color=DIV_C, linewidth=1.2, alpha=0.9, zorder=1)

    # ── Panel 1: Temperature ──────────────────────────────
    ax1.plot(times, temp, color=WARM, linewidth=1.8, zorder=3)
    ax1.fill_between(times, temp, alpha=0.07, color=WARM, zorder=2)
    if d_noon_max:
        ax1.scatter(d_noon_max, d_temp_max, color=DOT_MAX, s=25, zorder=5,
                    edgecolors="black", linewidths=0.2, label="Temp. max")
    if d_noon_min:
        ax1.scatter(d_noon_min, d_temp_min, color=DOT_MIN, s=25, zorder=5,
                    edgecolors="black", linewidths=0.2, label="Temp. min")
    style_ax(ax1, "Temp  [°C]", WARM)
    # Hide the bottom spine of ax1 so the pair visually merges with ax2 below
    ax1.tick_params(axis="x", labelbottom=False)
    ax1.spines["bottom"].set_visible(False)
    ax1.tick_params(axis="x", top=True, labeltop=False, which="major", length=6, color=DIM)
    ax1.tick_params(axis="x", top=True, which="minor", length=3, color=DIM)
    ax1.spines["top"].set_color(GRID_C)

    def _hour_fmt_top(x, pos):
        """Extended top-axis formatter: puts the day label on the line closest to the spine.

        On the top axis the "closest to spine" line is the first line of the
        label string, so the format is ``"Weekday  DD.MM\\nHH"`` (reversed
        compared to the bottom axis formatter).
        """
        dt = mdates.num2date(x)
        h  = dt.hour
        lh = day_label_hours.get(dt.date())
        if lh is not None and h == lh:
            return f"{_WD_EN[dt.weekday()]}  {dt.strftime('%d.%m')}\n{h:02d}"
        return f"{h:02d}" if h % 4 == 0 else ""

    # Secondary top x-axis carries day-name labels above the temperature panel
    _ax1_top = ax1.secondary_xaxis("top")
    _ax1_top.xaxis.set_minor_locator(mdates.HourLocator(interval=1))
    _ax1_top.xaxis.set_major_locator(mdates.HourLocator(byhour=range(0, 24, 2)))
    _ax1_top.xaxis.set_major_formatter(mticker.FuncFormatter(_hour_fmt_top))
    _ax1_top.tick_params(axis="x", which="major", length=0, labelsize=6, colors=DIM, pad=4)
    _ax1_top.tick_params(axis="x", which="minor", length=0, labeltop=False)
    _ax1_top.spines["top"].set_visible(False)

    ax1.set_title(
        f"{city.upper()}  ·  {hours}h  FORECAST  (CET)",
        color=TEXT, fontsize=9, fontfamily="monospace", loc="left", pad=52,
    )

    # ── Panel 2: Humidity ─────────────────────────────────
    ax2.plot(times, humidity, color=HUMID, linewidth=1.6, zorder=3)
    ax2.fill_between(times, humidity, alpha=0.08, color=HUMID, zorder=2)
    ax2.set_ylim(0, 105)
    style_ax(ax2, "Humidity  [%]", HUMID)
    ax2.spines["top"].set_visible(False)

    # ── Panel 3: Wind Speed ───────────────────────────────
    ax3.fill_between(times, ws, alpha=0.15, color=WIND_C, zorder=2)
    ax3.plot(times, ws, color=WIND_C, linewidth=1.6, zorder=3)
    ax3.set_ylim(bottom=0)
    style_ax(ax3, "Wind  [km/h]", WIND_C)
    ax3.tick_params(axis="x", labelbottom=False)
    ax3.spines["bottom"].set_visible(False)

    # ── Panel 4: Wind Direction (narrow quiver strip) ─────
    # One arrow every 3 h; vectors use the meteorological-to-cartesian conversion
    style_ax(ax4, "Dir", WIND_D)
    ax4.spines["top"].set_visible(False)
    ax4.set_ylim(-1.2, 1.2)
    ax4.set_yticks([])
    ax4.axhline(0, color=GRID_C, linewidth=0.5, zorder=1)
    t_sub  = times[::3]
    wd_sub = np.array(wd[::3])
    u = -np.sin(np.radians(wd_sub))
    v = -np.cos(np.radians(wd_sub))
    ax4.quiver(t_sub, np.zeros(len(t_sub)), u, v,
               color=WIND_D, alpha=0.9, scale=28, width=0.0015,
               headwidth=3, headlength=3.5, zorder=4, pivot="mid")

    # ── Panel 5: Precipitation ────────────────────────────
    ax5.bar(times, precip, width=BAR_W, color=PRECIP, alpha=0.85, zorder=3, align="center")
    ax5.set_ylim(bottom=0)
    style_ax(ax5, "Precip  [mm]", PRECIP)
    ax5.tick_params(axis="x", labelbottom=False)
    ax5.spines["bottom"].set_visible(False)

    # ── Panel 6: Sunshine Duration ────────────────────────
    # Convert seconds/hour → minutes/hour before plotting
    sunshine_min = [s / 60.0 for s in sunshine]
    ax6.bar(times, sunshine_min, width=BAR_W, color=SUN_C, alpha=0.85, zorder=3, align="center")
    ax6.set_ylim(0, 65)
    style_ax(ax6, "Sunshine\n[min/h]", SUN_C)
    ax6.spines["top"].set_visible(False)
    # Day labels are carried by ax8 (the bottom-most panel) — suppress them here
    ax6.tick_params(axis="x", labelbottom=False)
    # Annotate total sunshine hours per calendar day
    from collections import defaultdict
    _sun_by_day = defaultdict(float)
    for _t, _s in zip(times, sunshine):
        _sun_by_day[_t.date()] += _s
    for _day, _total_s in _sun_by_day.items():
        _noon = datetime(_day.year, _day.month, _day.day, 12, 0, 0)
        if times[0] <= _noon <= times[-1]:
            ax6.text(_noon, 50, f"{_total_s / 3600:.1f}h", color=SUN_C, fontsize=8, fontweight="bold",
                     ha="center", va="center",
                     bbox=dict(boxstyle="round,pad=0.2", facecolor="#080c12", alpha=0.75, edgecolor="none"))

    # ── Panel 7: Soil Temperature ─────────────────────────
    # Check whether any non-NaN soil data is present (may be absent before
    # the first pipeline run that includes the soil columns).
    _has_soil_t = not all(np.isnan(v) for v in s_t0)
    if _has_soil_t:
        if "0" in show_st:
            ax7.plot(times, s_t0,  color=SOIL_T0,  linewidth=1.5, zorder=3)
            ax7.fill_between(times, s_t0, alpha=0.05, color=SOIL_T0, zorder=2)
        if "6" in show_st:
            ax7.plot(times, s_t6,  color=SOIL_T6,  linewidth=1.5, zorder=3)
        if "18" in show_st:
            ax7.plot(times, s_t18, color=SOIL_T18, linewidth=1.5, zorder=3)
    style_ax(ax7, "Bodentemp\n[°C]", SOIL_T0)
    ax7.tick_params(axis="x", labelbottom=False)
    ax7.spines["bottom"].set_visible(False)
    if not _has_soil_t:
        ax7.text(0.5, 0.5, "Bodendaten verfügbar nach\nnächstem Datenabruf",
                 transform=ax7.transAxes, ha="center", va="center",
                 color=DIM, fontsize=7, fontfamily="monospace")

    # ── Panel 8: Soil Moisture ────────────────────────────
    _has_soil_m = not all(np.isnan(v) for v in s_m01)
    if _has_soil_m:
        if "0-1" in show_sm:
            ax8.plot(times, s_m01, color=SOIL_M0, linewidth=1.5, zorder=3)
            ax8.fill_between(times, s_m01, alpha=0.06, color=SOIL_M0, zorder=2)
        if "1-3" in show_sm:
            ax8.plot(times, s_m13, color=SOIL_M1, linewidth=1.5, zorder=3)
        if "3-9" in show_sm:
            ax8.plot(times, s_m39, color=SOIL_M3, linewidth=1.5, zorder=3)
    style_ax(ax8, "Bodenfeuchte\n[m³/m³]", SOIL_M0)
    ax8.spines["top"].set_visible(False)
    # This is the only panel that uses the extended day-label formatter
    ax8.xaxis.set_major_formatter(mticker.FuncFormatter(hour_fmt_with_day))
    ax8.set_xlabel("Zeit  (UTC+1 / CET)", color=DIM, fontsize=7.5)
    if not _has_soil_m:
        ax8.text(0.5, 0.5, "Bodendaten verfügbar nach\nnächstem Datenabruf",
                 transform=ax8.transAxes, ha="center", va="center",
                 color=DIM, fontsize=7, fontfamily="monospace")

    # Set the x-axis limits on the top panel of each shared-x pair; sharex
    # propagates the limits automatically to the paired bottom panel.
    for _ax in [ax1, ax3, ax5, ax7]:
        _ax.set_xlim(times[0], times[-1])

    fig.patch.set_facecolor(BG)
    # rect=[left, bottom, right, top]: 10 % left margin is reserved for y-axis labels
    plt.tight_layout(pad=0.8, rect=[0.10, 0.01, 1.0, 0.97])

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    chart_data = buf.getvalue()
    chart_cache.put(cache_key, chart_data)

    return Response(
        content=chart_data,
        media_type="image/png",
        headers={"Cache-Control": "no-cache, max-age=0", "X-Cache": "MISS"},
    )
