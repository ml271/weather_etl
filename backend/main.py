"""
FastAPI Backend – Weather ETL REST API
"""
import os
import logging
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import desc, func, text, case

from database import get_db, engine
from models import WeatherDaily, WeatherHourly, WeatherAlert, Base
from schemas import WeatherDailySchema, WeatherHourlySchema, WeatherAlertSchema, ForecastSummary

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Weather ETL API",
    description="REST API für die Weather ETL Pipeline",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DEFAULT_CITY = os.getenv("DEFAULT_CITY", "Freiburg")


# ── Health Check ──────────────────────────────────────

@app.get("/health", tags=["System"])
def health_check(db: Session = Depends(get_db)):
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
    city = city or DEFAULT_CITY

    today_record = (
        db.query(WeatherDaily)
        .filter(
            WeatherDaily.city == city,
            WeatherDaily.forecast_date >= date.today(),
        )
        .order_by(WeatherDaily.forecast_date.asc())
        .first()
    )

    active_alerts = (
        db.query(WeatherAlert)
        .filter(WeatherAlert.city == city, WeatherAlert.is_active == True)
        .order_by(
            # SQLAlchemy 2.x case() Syntax
            case(
                (WeatherAlert.severity == "danger",  0),
                (WeatherAlert.severity == "warning", 1),
                else_=2,
            ),
            WeatherAlert.forecast_date.asc(),
        )
        .all()
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
        active_alerts=[WeatherAlertSchema.model_validate(a) for a in active_alerts],
        last_updated=last_updated,
    )


# ── Daily Forecast ────────────────────────────────────

@app.get("/forecast/daily", response_model=list[WeatherDailySchema], tags=["Forecast"])
def get_daily_forecast(
    city: str = Query(default=None),
    days: int = Query(default=4, ge=1, le=7),  # Default 4 Tage (genauer + übersichtlicher)
    db: Session = Depends(get_db),
):
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
    city = city or DEFAULT_CITY
    query = db.query(WeatherAlert).filter(WeatherAlert.city == city)
    if active_only:
        query = query.filter(WeatherAlert.is_active == True)
    if severity:
        query = query.filter(WeatherAlert.severity == severity)
    return [WeatherAlertSchema.model_validate(a) for a in query.order_by(desc(WeatherAlert.created_at)).all()]


@app.get("/alerts/history", response_model=list[WeatherAlertSchema], tags=["Alerts"])
def get_alert_history(
    city: str = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
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
    city = city or DEFAULT_CITY
    records = (
        db.query(WeatherDaily)
        .filter(WeatherDaily.city == city, WeatherDaily.forecast_date >= date.today())
        .order_by(WeatherDaily.forecast_date.asc())
        .limit(4)  # 4 Tage passend zum Forecast Default
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
