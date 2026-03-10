"""
FastAPI Backend – Weather ETL REST API
"""
import io
import os
import logging
from datetime import date, datetime, timezone
from typing import Optional

import matplotlib
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


# ── Day Detail Plot (Matplotlib PNG, single day) ──────

@app.get("/charts/day-detail", tags=["Charts"])
def get_day_detail_plot(
    date_str: str = Query(alias="date"),
    city: str = Query(default=None),
    db: Session = Depends(get_db),
):
    from datetime import timedelta, date as _date

    city = city or DEFAULT_CITY
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
        raise HTTPException(status_code=404, detail=f"Keine Stundendaten für {date_str}.")

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
        figsize=(11, 12),
        gridspec_kw={"height_ratios": [3, 2, 2.5, 0.7, 1.5, 1.5], "hspace": 0.32},
        sharex=True,
        facecolor=BG,
    )

    def hour_fmt(x, pos):
        h = mdates.num2date(x).hour
        return f"{h:02d}" if h % 2 == 0 else ""

    def style_ax(ax, ylabel, ylabel_color=TEXT):
        ax.set_facecolor(SURFACE)
        ax.spines[:].set_color(GRID_C)
        ax.grid(True, color=GRID_C, linewidth=0.5, linestyle="--", alpha=0.5, which="major", axis="y")
        ax.set_ylabel(ylabel, color=ylabel_color, fontsize=8, labelpad=6)
        ax.yaxis.label.set_color(ylabel_color)
        ax.tick_params(colors=DIM, labelsize=8, which="both")
        ax.xaxis.set_minor_locator(mdates.HourLocator(interval=1))
        ax.xaxis.set_major_locator(mdates.HourLocator(byhour=range(0, 24, 2)))
        ax.xaxis.set_major_formatter(mticker.FuncFormatter(hour_fmt))
        ax.tick_params(axis="x", which="minor", length=3, color=DIM, labelbottom=False)
        ax.tick_params(axis="x", which="major", length=6, color=DIM, labelbottom=True, labelsize=7, pad=5)

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
        h = mdates.num2date(x).hour
        return f"{h:02d}" if h % 2 == 0 else ""

    _ax1_top = ax1.secondary_xaxis("top")
    _ax1_top.xaxis.set_minor_locator(mdates.HourLocator(interval=1))
    _ax1_top.xaxis.set_major_locator(mdates.HourLocator(byhour=range(0, 24, 2)))
    _ax1_top.xaxis.set_major_formatter(mticker.FuncFormatter(_hour_fmt_top))
    _ax1_top.tick_params(axis="x", which="major", length=0, labelsize=7, colors=DIM, pad=8)
    _ax1_top.tick_params(axis="x", which="minor", length=0, labeltop=False)
    _ax1_top.spines["top"].set_visible(False)

    ax1.legend(loc="upper right", fontsize=7.5,
               facecolor=BG, edgecolor=GRID_C, labelcolor=TEXT, framealpha=0.9)
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
    ax6.set_xlabel("Zeit  (UTC+1 / CET)", color=DIM, fontsize=7.5)

    axes[0].set_xlim(times[0], times[-1])
    fig.patch.set_facecolor(BG)
    plt.tight_layout(pad=0.8, rect=[0.10, 0.01, 1.0, 0.97])

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)

    return Response(
        content=buf.read(),
        media_type="image/png",
        headers={"Cache-Control": "no-cache, max-age=0"},
    )


# ── Hourly Plot (Matplotlib PNG) ──────────────────────

@app.get("/charts/hourly-plot", tags=["Charts"])
def get_hourly_plot(
    city: str = Query(default=None),
    hours: int = Query(default=96, ge=6, le=168),
    db: Session = Depends(get_db),
):
    from datetime import timedelta

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
    DOT_MIN = "#4ad4ff"

    BAR_W = 0.8 / 24.0   # 0.8 h in matplotlib date units (days)

    # Midnight dividers (local time)
    midnights = []
    if times:
        md = datetime(times[0].year, times[0].month, times[0].day) + timedelta(days=1)
        while md <= times[-1]:
            midnights.append(md)
            md += timedelta(days=1)

    # height_ratios: wind-dir panel (idx 3) is intentionally narrow
    fig, axes = plt.subplots(
        6, 1,
        figsize=(11, 12),
        gridspec_kw={"height_ratios": [3, 2, 2.5, 0.7, 1.5, 1.5], "hspace": 0.32},
        sharex=True,
        facecolor=BG,
    )

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
        _lh = int(_mid_h / 2.0 + 0.5) * 2   # snap to nearest even hour
        _lh = max(0, min(22, _lh))
        day_label_hours[_check] = _lh
        _check += timedelta(days=1)

    def hour_fmt(x, pos):
        dt = mdates.num2date(x)
        h  = dt.hour
        lh = day_label_hours.get(dt.date())
        if lh is not None and h == lh:
            return f"{h:02d}\n{_WD_EN[dt.weekday()]}  {dt.strftime('%d.%m')}"
        return f"{h:02d}" if h % 2 == 0 else ""

    def style_ax(ax, ylabel, ylabel_color=TEXT):
        ax.set_facecolor(SURFACE)
        ax.spines[:].set_color(GRID_C)
        ax.grid(True, color=GRID_C, linewidth=0.5, linestyle="--", alpha=0.5, which="major", axis="y")
        ax.set_ylabel(ylabel, color=ylabel_color, fontsize=8, labelpad=6)
        ax.yaxis.label.set_color(ylabel_color)
        ax.tick_params(colors=DIM, labelsize=8, which="both")
        ax.xaxis.set_minor_locator(mdates.HourLocator(interval=1))
        ax.xaxis.set_major_locator(mdates.HourLocator(byhour=range(0, 24, 2)))
        ax.xaxis.set_major_formatter(mticker.FuncFormatter(hour_fmt))
        ax.tick_params(axis="x", which="minor", length=3, color=DIM, labelbottom=False)
        ax.tick_params(axis="x", which="major", length=6, color=DIM, labelbottom=True, labelsize=7, pad=5)
        for md in midnights:
            ax.axvline(md, color=DIV_C, linewidth=1.2, alpha=0.9, zorder=1)

    # ── Panel 1: Temperature ──────────────────────────────
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
        return f"{h:02d}" if h % 2 == 0 else ""

    _ax1_top = ax1.secondary_xaxis("top")
    _ax1_top.xaxis.set_minor_locator(mdates.HourLocator(interval=1))
    _ax1_top.xaxis.set_major_locator(mdates.HourLocator(byhour=range(0, 24, 2)))
    _ax1_top.xaxis.set_major_formatter(mticker.FuncFormatter(_hour_fmt_top))
    _ax1_top.tick_params(axis="x", which="major", length=0, labelsize=7, colors=DIM, pad=8)
    _ax1_top.tick_params(axis="x", which="minor", length=0, labeltop=False)
    _ax1_top.spines["top"].set_visible(False)

    ax1.legend(loc="upper right", fontsize=7.5,
               facecolor=BG, edgecolor=GRID_C, labelcolor=TEXT, framealpha=0.9)
    ax1.set_title(
        f"{city.upper()}  ·  {hours}h  FORECAST  (CET)",
        color=TEXT, fontsize=9, fontfamily="monospace", loc="left", pad=52,
    )

    # ── Panel 2: Humidity ─────────────────────────────────
    ax2 = axes[1]
    ax2.plot(times, humidity, color=HUMID, linewidth=1.6, zorder=3)
    ax2.fill_between(times, humidity, alpha=0.08, color=HUMID, zorder=2)
    ax2.set_ylim(0, 105)
    style_ax(ax2, "Humidity  [%]", HUMID)

    # ── Panel 3: Wind Speed ───────────────────────────────
    ax3 = axes[2]
    ax3.fill_between(times, ws, alpha=0.15, color=WIND_C, zorder=2)
    ax3.plot(times, ws, color=WIND_C, linewidth=1.6, zorder=3)
    ax3.set_ylim(bottom=0)
    style_ax(ax3, "Wind  [km/h]", WIND_C)

    # ── Panel 4: Wind Direction (narrow quiver strip) ─────
    ax4 = axes[3]
    style_ax(ax4, "Dir", WIND_D)
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
    ax5 = axes[4]
    ax5.bar(times, precip, width=BAR_W, color=PRECIP, alpha=0.85, zorder=3, align="center")
    ax5.set_ylim(bottom=0)
    style_ax(ax5, "Precip  [mm]", PRECIP)

    # ── Panel 6: Sunshine Duration ────────────────────────
    ax6 = axes[5]
    sunshine_min = [s / 60.0 for s in sunshine]
    ax6.bar(times, sunshine_min, width=BAR_W, color=SUN_C, alpha=0.85, zorder=3, align="center")
    ax6.set_ylim(0, 65)
    style_ax(ax6, "Sunshine\n[min/h]", SUN_C)
    ax6.set_xlabel("Zeit  (UTC+1 / CET)", color=DIM, fontsize=7.5)

    # Clamp x-axis to exact data range — no automatic matplotlib padding
    axes[0].set_xlim(times[0], times[-1])

    fig.patch.set_facecolor(BG)
    # rect=[left, bottom, right, top] — 10 % left margin creates an empty side panel
    plt.tight_layout(pad=0.8, rect=[0.10, 0.01, 1.0, 0.97])

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)

    return Response(
        content=buf.read(),
        media_type="image/png",
        headers={"Cache-Control": "no-cache, max-age=0"},
    )
