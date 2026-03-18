"""
FastAPI Backend – Weather ETL REST API
"""
import io
import os
import logging
from datetime import date, datetime, timezone
from typing import Optional

import matplotlib
import matplotlib.gridspec as mgs
matplotlib.use("Agg")  # non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
import numpy as np

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import desc, func, text, case

from database import get_db, engine
from models import WeatherDaily, WeatherHourly, WeatherAlert
from schemas import WeatherDailySchema, WeatherHourlySchema, WeatherAlertSchema, ForecastSummary
from routers import stations, weather_fetch, auth, warnings
import chart_cache

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Weather ETL API",
    description="REST API for the Weather ETL Pipeline",
    version="1.0.0",
)

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

DEFAULT_CITY = os.getenv("DEFAULT_CITY", "Freiburg")


# ── Cache Management ──────────────────────────────────

@app.post("/charts/cache-clear", tags=["Charts"])
def clear_chart_cache(city: str = Query(...)):
    chart_cache.invalidate(city)
    return {"status": "ok", "city": city}


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
            detail=f"No data for '{city}'. Please trigger the Airflow DAG first.",
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
        raise HTTPException(status_code=404, detail=f"No hourly data for '{city}'.")

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
        raise HTTPException(status_code=404, detail=f"No data for '{city}'.")
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


# ── Day Detail Plot (Matplotlib PNG, single day) ──────

@app.get("/charts/day-detail", tags=["Charts"])
def get_day_detail_plot(
    date_str: str = Query(alias="date"),
    city: str = Query(default=None),
    db: Session = Depends(get_db),
):
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
        raise HTTPException(status_code=404, detail=f"No hourly data for {date_str}.")

    daily = (
        db.query(WeatherDaily)
        .filter(WeatherDaily.city == city, WeatherDaily.forecast_date == target_date)
        .first()
    )

    CET   = timedelta(hours=1)
    times    = [r.forecast_time.replace(tzinfo=None) + CET for r in records]
    temp     = [float(r.temperature)       if r.temperature      is not None else np.nan for r in records]
    humidity = [float(r.humidity)          if r.humidity         is not None else np.nan for r in records]
    ws       = [float(r.wind_speed)        if r.wind_speed       is not None else 0.0    for r in records]
    wd       = [float(r.wind_direction)    if r.wind_direction   is not None else 0.0    for r in records]
    precip   = [float(r.precipitation)     if r.precipitation    is not None else 0.0    for r in records]
    sunshine = [float(r.sunshine_duration) if r.sunshine_duration is not None else 0.0   for r in records]

    # Daily max/min dots at noon if it falls within the data range
    d_noon_max, d_temp_max = [], []
    d_noon_min, d_temp_min = [], []
    if daily:
        noon = datetime(target_date.year, target_date.month, target_date.day, 12, 0, 0)
        if times[0] <= noon <= times[-1]:
            if daily.temperature_max is not None:
                d_noon_max.append(noon); d_temp_max.append(float(daily.temperature_max))
            if daily.temperature_min is not None:
                d_noon_min.append(noon); d_temp_min.append(float(daily.temperature_min))

    # ── Same palette as main plot ──
    BG      = "#080c12"
    SURFACE = "#0d1520"
    GRID_C  = "#1a2a3f"
    DIV_C   = "#2a3d58"
    TEXT    = "#c8d8f0"
    DIM     = "#4a6080"
    WARM    = "#ff9d4a"
    HUMID   = "#4adfb8"
    WIND_C  = "#a78bfa"
    WIND_D  = "#c4b5fd"
    PRECIP  = "#4a9eff"
    SUN_C   = "#ffd950"
    DOT_MAX = "#ff5566"
    DOT_MIN = "#4ad4ff"

    BAR_W = 0.8 / 24.0

    _WD_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    title_date = target_date.strftime("%d.%m.%Y")
    title_day  = _WD_EN[target_date.weekday()]

    # ── Same 6-panel layout as main plot ──
    fig, axes = plt.subplots(
        6, 1,
        figsize=(8, 6),
        gridspec_kw={"height_ratios": [4, 2, 2.5, 0.7, 1.5, 1.5], "hspace": 0.58},
        sharex=True,
        facecolor=BG,
    )

    def hour_fmt(x, pos):
        h = mdates.num2date(x).hour
        return f"{h:02d}" if h % 4 == 0 else ""

    def style_ax(ax, ylabel, ylabel_color=TEXT):
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
    ax1.axhline(0, color=DIM, linewidth=0.8, linestyle="--", alpha=0.6, zorder=2)
    if d_noon_max:
        ax1.scatter(d_noon_max, d_temp_max, color=DOT_MAX, s=55, zorder=5,
                    edgecolors="white", linewidths=0.6, label="Daily max")
    if d_noon_min:
        ax1.scatter(d_noon_min, d_temp_min, color=DOT_MIN, s=55, zorder=5,
                    edgecolors="white", linewidths=0.6, label="Daily min")
    style_ax(ax1, "Temp  [°C]", WARM)
    ax1.tick_params(axis="x", top=True, labeltop=False, which="major", length=6, color=DIM)
    ax1.tick_params(axis="x", top=True, which="minor", length=3, color=DIM)
    ax1.spines["top"].set_color(GRID_C)

    def _hour_fmt_top(x, pos):
        h = mdates.num2date(x).hour
        return f"{h:02d}" if h % 4 == 0 else ""

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
    ax2.set_ylim(0, 105)
    style_ax(ax2, "Humidity  [%]", HUMID)

    # ── Panel 3: Wind Speed ──
    ax3 = axes[2]
    ax3.fill_between(times, ws, alpha=0.15, color=WIND_C, zorder=2)
    ax3.plot(times, ws, color=WIND_C, linewidth=1.6, zorder=3)
    ax3.set_ylim(bottom=0)
    style_ax(ax3, "Wind  [km/h]", WIND_C)

    # ── Panel 4: Wind Direction (narrow quiver strip) ──
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
    ax6 = axes[5]
    ax6.bar(times, [s / 60.0 for s in sunshine], width=BAR_W, color=SUN_C, alpha=0.85, zorder=3, align="center")
    ax6.set_ylim(0, 65)
    style_ax(ax6, "Sunshine\n[min/h]", SUN_C)
    ax6.set_xlabel("Time  (UTC+1 / CET)", color=DIM, fontsize=7.5)

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
    soil_t: str = Query(default="0,6,18"),      # comma-sep depths to show: 0 / 6 / 18
    soil_m: str = Query(default="0-1,1-3,3-9"), # comma-sep depths: 0-1 / 1-3 / 3-9
    db: Session = Depends(get_db),
):
    from datetime import timedelta

    city = city or DEFAULT_CITY

    # ── Cache check ──────────────────────────────────────
    show_st = set(soil_t.split(","))   # e.g. {"0", "6", "18"}
    show_sm = set(soil_m.split(","))   # e.g. {"0-1", "1-3", "3-9"}
    cache_key = f"{city}:hourly:{hours}:st{','.join(sorted(show_st))}:sm{','.join(sorted(show_sm))}"
    cached = chart_cache.get(cache_key)
    if cached:
        return Response(content=cached, media_type="image/png",
                        headers={"Cache-Control": "no-cache, max-age=0", "X-Cache": "HIT"})

    from datetime import timedelta as _td
    _CET = _td(hours=1)
    _now_utc = datetime.now(timezone.utc)
    # Start chart at 00:00 CET of the current day
    _today_cet = (_now_utc + _CET).date()
    _midnight_utc = datetime(_today_cet.year, _today_cet.month, _today_cet.day,
                             tzinfo=timezone.utc) - _CET

    records = (
        db.query(WeatherHourly)
        .filter(WeatherHourly.city == city, WeatherHourly.forecast_time >= _midnight_utc)
        .order_by(WeatherHourly.forecast_time.asc())
        .limit(hours)
        .all()
    )

    if not records:
        raise HTTPException(status_code=404, detail=f"No hourly data for '{city}'.")

    # Daily records for max/min scatter dots
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

    # Convert to local CET (UTC+1) naive datetimes for clean axis labels
    CET = timedelta(hours=1)
    times    = [r.forecast_time.replace(tzinfo=None) + CET for r in records]
    temp     = [float(r.temperature)       if r.temperature      is not None else np.nan for r in records]
    humidity = [float(r.humidity)          if r.humidity         is not None else np.nan for r in records]
    ws       = [float(r.wind_speed)        if r.wind_speed       is not None else 0.0    for r in records]
    wd       = [float(r.wind_direction)    if r.wind_direction   is not None else 0.0    for r in records]
    precip   = [float(r.precipitation)     if r.precipitation    is not None else 0.0    for r in records]
    sunshine = [float(r.sunshine_duration) if r.sunshine_duration is not None else 0.0   for r in records]
    s_t0  = [float(r.soil_temperature_0cm)  if getattr(r, "soil_temperature_0cm",  None) is not None else np.nan for r in records]
    s_t6  = [float(r.soil_temperature_6cm)  if getattr(r, "soil_temperature_6cm",  None) is not None else np.nan for r in records]
    s_t18 = [float(r.soil_temperature_18cm) if getattr(r, "soil_temperature_18cm", None) is not None else np.nan for r in records]
    s_m01 = [float(r.soil_moisture_0_1cm)   if getattr(r, "soil_moisture_0_1cm",   None) is not None else np.nan for r in records]
    s_m13 = [float(r.soil_moisture_1_3cm)   if getattr(r, "soil_moisture_1_3cm",   None) is not None else np.nan for r in records]
    s_m39 = [float(r.soil_moisture_3_9cm)   if getattr(r, "soil_moisture_3_9cm",   None) is not None else np.nan for r in records]

    # Daily max/min dots placed at noon local time
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

    # ── Palette ──────────────────────────────────────────
    BG      = "#080c12"
    SURFACE = "#0d1520"
    GRID_C  = "#1a2a3f"
    DIV_C   = "#2a3d58"
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
    SOIL_T0  = "#e8a05c"   # surface soil temp (warm sandy)
    SOIL_T6  = "#c07830"   # shallow soil temp (earth)
    SOIL_T18 = "#8b5520"   # mid soil temp (deep earth)
    SOIL_M0  = "#5bb8f5"   # surface moisture (light blue)
    SOIL_M1  = "#3a8cc4"   # shallow moisture
    SOIL_M3  = "#1e5f8a"   # deeper moisture

    BAR_W = 0.8 / 24.0   # 0.8 h in matplotlib date units (days)

    # Midnight dividers (local time)
    midnights = []
    if times:
        md = datetime(times[0].year, times[0].month, times[0].day) + timedelta(days=1)
        while md <= times[-1]:
            midnights.append(md)
            md += timedelta(days=1)

    # Nested GridSpec: 4 paired groups, small space within each pair, normal gap between pairs.
    # Pair 1 → ax1 (Temp) + ax2 (Humidity)
    # Pair 2 → ax3 (Wind speed) + ax4 (Wind direction)
    # Pair 3 → ax5 (Precipitation) + ax6 (Sunshine)
    # Pair 4 → ax7 (Soil Temperature) + ax8 (Soil Moisture)
    fig = plt.figure(figsize=(8, 8), facecolor=BG)
    _outer = mgs.GridSpec(4, 1, figure=fig, hspace=0.22)
    _p1 = mgs.GridSpecFromSubplotSpec(2, 1, subplot_spec=_outer[0], hspace=0.2, height_ratios=[4, 2])
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

    # Compute per-day label hour: midpoint of the visible portion of each day,
    # snapped to the nearest even hour so it lands on an existing tick.
    from datetime import date as _date
    day_label_hours: dict = {}
    _check = times[0].date()
    while _check <= times[-1].date():
        _ds = max(times[0], datetime(_check.year, _check.month, _check.day, 0, 0))
        _de = min(times[-1], datetime(_check.year, _check.month, _check.day, 23, 59))
        _mid_h = (_ds.hour + _ds.minute / 60.0 + _de.hour + _de.minute / 60.0) / 2.0
        _lh = int(_mid_h / 4.0 + 0.5) * 4   # snap to nearest 4-hour mark
        _lh = max(0, min(20, _lh))
        day_label_hours[_check] = _lh
        _check += timedelta(days=1)

    def hour_fmt_plain(x, pos):
        h = mdates.num2date(x).hour
        return f"{h:02d}" if h % 4 == 0 else ""

    def hour_fmt_with_day(x, pos):
        dt = mdates.num2date(x)
        h  = dt.hour
        lh = day_label_hours.get(dt.date())
        if lh is not None and h == lh:
            return f"{h:02d}\n{_WD_EN[dt.weekday()]}  {dt.strftime('%d.%m')}"
        return f"{h:02d}" if h % 4 == 0 else ""

    def style_ax(ax, ylabel, ylabel_color=TEXT):
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
    ax1.axhline(0, color=DIM, linewidth=0.8, linestyle="--", alpha=0.6, zorder=2)
    if d_noon_max:
        ax1.scatter(d_noon_max, d_temp_max, color=DOT_MAX, s=25, zorder=5,
                    edgecolors="black", linewidths=0.2, label="Temp. max")
    if d_noon_min:
        ax1.scatter(d_noon_min, d_temp_min, color=DOT_MIN, s=25, zorder=5,
                    edgecolors="black", linewidths=0.2, label="Temp. min")
    style_ax(ax1, "Temp  [°C]", WARM)
    # Pair 1 top: hide bottom edge so ax1+ax2 look merged
    ax1.tick_params(axis="x", labelbottom=False)
    ax1.spines["bottom"].set_visible(False)
    # Top spine: tick marks from ax1, no labels (labels come from secondary axis below)
    ax1.tick_params(axis="x", top=True, labeltop=False, which="major", length=6, color=DIM)
    ax1.tick_params(axis="x", top=True, which="minor", length=3, color=DIM)
    ax1.spines["top"].set_color(GRID_C)

    # Independent secondary top x-axis — reversed noon format so "12" is the LAST line
    # (for top-axis labels, the last line sits closest to the spine = same level as other hours)
    def _hour_fmt_top(x, pos):
        dt = mdates.num2date(x)
        h  = dt.hour
        lh = day_label_hours.get(dt.date())
        if lh is not None and h == lh:
            # Last line is closest to spine on top axis, so put hour number last
            return f"{_WD_EN[dt.weekday()]}  {dt.strftime('%d.%m')}\n{h:02d}"
        return f"{h:02d}" if h % 4 == 0 else ""

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
    # Pair 2 top: hide bottom edge
    ax3.tick_params(axis="x", labelbottom=False)
    ax3.spines["bottom"].set_visible(False)

    # ── Panel 4: Wind Direction (narrow quiver strip) ─────
    style_ax(ax4, "Dir", WIND_D)
    ax4.spines["top"].set_visible(False)
    ax4.set_ylim(-1.2, 1.2)
    ax4.set_yticks([])
    ax4.axhline(0, color=GRID_C, linewidth=0.5, zorder=1)
    # One arrow every 3 h — meteorological → blowing-to cartesian; scale=28 = very small
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
    # Pair 3 top: hide bottom edge
    ax5.tick_params(axis="x", labelbottom=False)
    ax5.spines["bottom"].set_visible(False)

    # ── Panel 6: Sunshine Duration ────────────────────────
    sunshine_min = [s / 60.0 for s in sunshine]
    ax6.bar(times, sunshine_min, width=BAR_W, color=SUN_C, alpha=0.85, zorder=3, align="center")
    ax6.set_ylim(0, 65)
    style_ax(ax6, "Sunshine\n[min/h]", SUN_C)
    ax6.spines["top"].set_visible(False)
    # Pair 3 bottom: no day labels here — they will appear on ax8 (bottom of chart)
    ax6.tick_params(axis="x", labelbottom=False)

    # ── Panel 7: Soil Temperature (filtered by show_st) ──
    _has_soil_t = not all(np.isnan(v) for v in s_t0)
    if _has_soil_t:
        if "0" in show_st:
            ax7.plot(times, s_t0,  color=SOIL_T0,  linewidth=1.5, zorder=3)
            ax7.fill_between(times, s_t0, alpha=0.05, color=SOIL_T0, zorder=2)
        if "6" in show_st:
            ax7.plot(times, s_t6,  color=SOIL_T6,  linewidth=1.5, zorder=3)
        if "18" in show_st:
            ax7.plot(times, s_t18, color=SOIL_T18, linewidth=1.5, zorder=3)
    style_ax(ax7, "Soil Temp\n[°C]", SOIL_T0)
    ax7.tick_params(axis="x", labelbottom=False)
    ax7.spines["bottom"].set_visible(False)
    if not _has_soil_t:
        ax7.text(0.5, 0.5, "Soil data available after\nnext ETL run",
                 transform=ax7.transAxes, ha="center", va="center",
                 color=DIM, fontsize=7, fontfamily="monospace")

    # ── Panel 8: Soil Moisture (filtered by show_sm) ─────
    _has_soil_m = not all(np.isnan(v) for v in s_m01)
    if _has_soil_m:
        if "0-1" in show_sm:
            ax8.plot(times, s_m01, color=SOIL_M0, linewidth=1.5, zorder=3)
            ax8.fill_between(times, s_m01, alpha=0.06, color=SOIL_M0, zorder=2)
        if "1-3" in show_sm:
            ax8.plot(times, s_m13, color=SOIL_M1, linewidth=1.5, zorder=3)
        if "3-9" in show_sm:
            ax8.plot(times, s_m39, color=SOIL_M3, linewidth=1.5, zorder=3)
    style_ax(ax8, "Soil Moist.\n[m³/m³]", SOIL_M0)
    ax8.spines["top"].set_visible(False)
    ax8.xaxis.set_major_formatter(mticker.FuncFormatter(hour_fmt_with_day))
    ax8.set_xlabel("Time  (UTC+1 / CET)", color=DIM, fontsize=7.5)
    if not _has_soil_m:
        ax8.text(0.5, 0.5, "Soil data available after\nnext ETL run",
                 transform=ax8.transAxes, ha="center", va="center",
                 color=DIM, fontsize=7, fontfamily="monospace")

    # Clamp x-axis — set on top panel of each pair; sharex propagates to the bottom panel
    for _ax in [ax1, ax3, ax5, ax7]:
        _ax.set_xlim(times[0], times[-1])

    fig.patch.set_facecolor(BG)
    # rect=[left, bottom, right, top] — 10 % left margin creates an empty side panel
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
