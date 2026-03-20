"""
SQLAlchemy ORM Models – Weather ETL Database Schema
====================================================

Each class in this module maps to one PostgreSQL table defined in
``docker/init.sql``. SQLAlchemy uses these models for query construction;
the actual table DDL is managed by init.sql on first startup, not by
``Base.metadata.create_all()``.

Column units and constraints:
  - Temperatures: °C stored as DECIMAL(5,2), i.e. −999.99 … 999.99 °C
  - Precipitation / snowfall: mm or cm stored as DECIMAL(6,2)
  - Wind speed: km/h stored as DECIMAL(6,2)
  - Soil moisture: m³/m³ stored as DECIMAL(8,6) for precision at small values
  - Timestamps: all stored WITH TIME ZONE (UTC in PostgreSQL)

Dependencies:
  - sqlalchemy >= 2.0  (``Column``, ``func``, ``declarative_base``)
  - sqlalchemy.dialects.postgresql  (``JSONB``)
  - database.py  (provides ``Base``)

Author: <project maintainer>
"""

from sqlalchemy import Column, Integer, String, Numeric, Boolean, Date, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from database import Base


class WeatherDaily(Base):
    """Daily weather forecast record for one city on one calendar date.

    Populated by the Airflow ETL pipeline (``load.py``) and by the on-demand
    ``POST /weather/fetch-now`` endpoint. The combination of (city, forecast_date)
    is unique; repeated imports perform an UPSERT rather than inserting duplicates.

    Attributes:
        id: Auto-incremented primary key.
        city: Human-readable city name (e.g. "Freiburg"). Must match exactly
            when querying; no normalisation is applied.
        forecast_date: The calendar date this record describes.
        temperature_max: Maximum air temperature at 2 m above ground in °C.
        temperature_min: Minimum air temperature at 2 m above ground in °C.
        precipitation_sum: Total precipitation (rain + snow water equivalent)
            in mm for the full day.
        snowfall_sum: Total snowfall accumulation in cm for the full day.
        wind_speed_max: Maximum sustained wind speed at 10 m in km/h.
        wind_gusts_max: Maximum wind gust speed at 10 m in km/h.
        weather_code: WMO weather interpretation code (see ``schemas.py`` for
            the human-readable mapping).
        uv_index_max: Maximum UV index for the day (dimensionless, 0–11+).
        sunrise: Local sunrise time, stored in UTC with timezone.
        sunset: Local sunset time, stored in UTC with timezone.
        created_at: UTC timestamp of row creation / last UPSERT, set by the
            database default ``NOW()``.
    """
    __tablename__ = "weather_daily"

    id                = Column(Integer, primary_key=True, index=True)
    city              = Column(String(100), nullable=False)
    forecast_date     = Column(Date, nullable=False)
    temperature_max   = Column(Numeric(5, 2))
    temperature_min   = Column(Numeric(5, 2))
    precipitation_sum = Column(Numeric(6, 2))
    snowfall_sum      = Column(Numeric(6, 2))
    wind_speed_max    = Column(Numeric(6, 2))
    wind_gusts_max    = Column(Numeric(6, 2))
    weather_code      = Column(Integer)
    uv_index_max      = Column(Numeric(4, 2))
    sunrise           = Column(DateTime(timezone=True))
    sunset            = Column(DateTime(timezone=True))
    created_at        = Column(DateTime(timezone=True), server_default=func.now())


class WeatherHourly(Base):
    """Hourly weather forecast record for one city at one point in time.

    Populated by the Airflow ETL pipeline and by ``POST /weather/fetch-now``.
    The combination of (city, forecast_time) is unique; repeated imports
    perform an UPSERT.

    Attributes:
        id: Auto-incremented primary key.
        city: Human-readable city name. Must match exactly when querying.
        forecast_time: The hour this record describes, stored as a
            timezone-aware UTC datetime (always on the hour).
        temperature: Air temperature at 2 m in °C.
        feels_like: Apparent temperature (wind chill / heat index) at 2 m in °C.
        precipitation: Total precipitation during this hour in mm.
        rain: Rain component of precipitation in mm.
        snowfall: Snowfall component of precipitation in cm (snow water
            equivalent differs from rain).
        wind_speed: Wind speed at 10 m in km/h.
        wind_direction: Wind direction at 10 m in degrees (0 = North, 90 = East,
            180 = South, 270 = West). Represents the direction the wind is
            *coming from* (meteorological convention).
        humidity: Relative humidity at 2 m in percent (0–100).
        sunshine_duration: Duration of direct sunshine during this hour in
            seconds (range 0–3600). Divide by 60 to get minutes/hour.
        weather_code: WMO weather interpretation code.
        is_day: ``True`` during daylight hours, ``False`` at night.
        soil_temperature_0cm: Soil temperature at the surface (0 cm depth) in °C.
        soil_temperature_6cm: Soil temperature at 6 cm depth in °C.
        soil_temperature_18cm: Soil temperature at 18 cm depth in °C.
        soil_moisture_0_1cm: Volumetric soil moisture in the 0–1 cm layer in
            m³/m³.
        soil_moisture_1_3cm: Volumetric soil moisture in the 1–3 cm layer in
            m³/m³.
        soil_moisture_3_9cm: Volumetric soil moisture in the 3–9 cm layer in
            m³/m³.
        created_at: UTC timestamp of row creation / last UPSERT.
    """
    __tablename__ = "weather_hourly"

    id            = Column(Integer, primary_key=True, index=True)
    city          = Column(String(100), nullable=False)
    forecast_time = Column(DateTime(timezone=True), nullable=False)
    temperature   = Column(Numeric(5, 2))
    feels_like    = Column(Numeric(5, 2))
    precipitation = Column(Numeric(5, 2))
    rain          = Column(Numeric(5, 2))
    snowfall      = Column(Numeric(5, 2))
    wind_speed    = Column(Numeric(6, 2))
    wind_direction = Column(Integer)
    humidity           = Column(Integer)
    sunshine_duration  = Column(Numeric(6, 2))   # seconds per hour
    weather_code       = Column(Integer)
    is_day        = Column(Boolean)
    soil_temperature_0cm  = Column(Numeric(5, 2))   # °C surface
    soil_temperature_6cm  = Column(Numeric(5, 2))   # °C shallow
    soil_temperature_18cm = Column(Numeric(5, 2))   # °C mid
    soil_moisture_0_1cm   = Column(Numeric(8, 6))   # m³/m³
    soil_moisture_1_3cm   = Column(Numeric(8, 6))   # m³/m³
    soil_moisture_3_9cm   = Column(Numeric(8, 6))   # m³/m³
    created_at    = Column(DateTime(timezone=True), server_default=func.now())


class Station(Base):
    """A named weather observation / forecast location.

    Pre-seeded with ~75 German, Austrian, and Swiss cities in ``init.sql``.
    Used by the station search autocomplete feature (``GET /stations/search``).
    Coordinates are used to pass ``lat``/``lon`` to the Open-Meteo API when the
    user selects a city from the search results.

    Attributes:
        id: Auto-incremented primary key.
        name: City or station name (e.g. "Freiburg"). Indexed with a GIN
            trigram index for fast ILIKE searches.
        region: Administrative region / Bundesland (e.g. "Baden-Württemberg").
            May be ``None`` for non-German entries.
        country: Country name (default "Germany").
        lat: Geographic latitude in decimal degrees (WGS-84), precision 6
            decimal places (≈ 11 cm).
        lon: Geographic longitude in decimal degrees (WGS-84), precision 6
            decimal places.
    """
    __tablename__ = "stations"

    id      = Column(Integer, primary_key=True, index=True)
    name    = Column(String(100), nullable=False)
    region  = Column(String(100))
    country = Column(String(50), default="Germany")
    lat     = Column(Numeric(9, 6), nullable=False)
    lon     = Column(Numeric(9, 6), nullable=False)


class User(Base):
    """An authenticated application user.

    Passwords are stored as bcrypt hashes (never in plaintext).
    Users can create custom weather warnings that the Airflow
    ``check_warnings`` DAG evaluates against forecast data.

    Attributes:
        id: Auto-incremented primary key.
        email: Unique email address used for notification delivery.
        username: Unique login handle used for authentication.
        hashed_password: bcrypt hash of the user's password.
        is_active: When ``False``, the user cannot log in and their warnings
            are skipped by the notification pipeline.
        created_at: UTC timestamp of account creation.
    """
    __tablename__ = "users"

    id              = Column(Integer, primary_key=True, index=True)
    email           = Column(String(255), unique=True, nullable=False, index=True)
    username        = Column(String(100), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    is_active       = Column(Boolean, default=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())


class WarningTemplate(Base):
    """A predefined warning configuration that users can adopt as a starting point.

    Templates are seeded in ``init.sql`` and available to all users via
    ``GET /warnings/templates``. They cannot be created or modified through the
    API (read-only via the templates endpoint).

    Attributes:
        id: Auto-incremented primary key.
        name: Human-readable template name (e.g. "Hitzwarnung").
        description: Optional longer description of what this template monitors.
        conditions: JSONB array of condition rules in the format::

                [{"parameter": "temperature_max", "comparator": ">",
                  "value": 32, "label": "Temperatur max."}]
    """
    __tablename__ = "warning_templates"

    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String(100), nullable=False)
    description = Column(Text)
    conditions  = Column(JSONB, nullable=False)


class Warning(Base):
    """A user-defined weather warning rule.

    Each warning belongs to exactly one user and targets one city. When the
    Airflow ``check_weather_warnings`` DAG runs, it evaluates every active
    warning's conditions against the daily forecast for the specified city and
    sends an email notification when all conditions are satisfied (AND logic).

    Conditions are evaluated against ``weather_daily`` fields:
    ``temperature_max``, ``temperature_min``, ``precipitation_sum``,
    ``snowfall_sum``, ``wind_speed_max``, ``wind_gusts_max``, ``uv_index_max``.

    Attributes:
        id: Auto-incremented primary key.
        user_id: Foreign key to ``users.id``. Cascade-deleted when the user is
            removed.
        station_id: Optional foreign key to ``stations.id``. Set to ``NULL``
            when the referenced station is deleted. The ``city`` field takes
            precedence over this for data lookups.
        city: City name used to query ``weather_daily``. Must match a city
            that the ETL pipeline has ingested data for.
        name: User-chosen name for this warning rule.
        conditions: JSONB array of ``ConditionRule`` objects (see
            ``schemas.py``). Each rule specifies a ``parameter``, ``comparator``
            (``>``, ``>=``, ``<``, ``<=``, ``==``), ``value``, and optional
            ``label``.
        validity: JSONB object describing the temporal scope of the warning.
            Schema matches ``ValiditySpec`` in ``schemas.py``; supported types
            are ``"date_range"``, ``"weekdays"``, and ``"months"``.
        active: When ``False``, the warning is excluded from the notification
            pipeline.
        created_at: UTC timestamp of warning creation.
        updated_at: UTC timestamp of last modification; updated automatically
            on each write.
    """
    __tablename__ = "warnings"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    station_id  = Column(Integer, ForeignKey("stations.id", ondelete="SET NULL"), nullable=True)
    city        = Column(String(100), nullable=False)
    name        = Column(String(100), nullable=False)
    conditions    = Column(JSONB, nullable=False)
    validity      = Column(JSONB, nullable=False)
    notify_timing = Column(String(15), default="as_available")
    active        = Column(Boolean, default=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WeatherAlert(Base):
    """A system-generated weather alert produced by the Airflow ETL pipeline.

    Alerts differ from user-defined ``Warning`` rules: they are generated
    automatically by comparing forecast data against ``config/alerts_config.yaml``
    during the Airflow transform step. They are visible to all users in the
    dashboard alert section.

    Each import cycle deactivates all previous alerts for a city and inserts
    fresh ones so the ``is_active`` flag always reflects the current forecast.

    Attributes:
        id: Auto-incremented primary key.
        city: City name the alert applies to.
        alert_name: Name of the alert rule that was triggered (from YAML ``name``
            field).
        severity: One of ``"info"``, ``"warning"``, or ``"danger"``. Enforced
            by a CHECK constraint in the database.
        message: Human-readable alert message (from YAML ``message`` field).
        condition_met: JSONB snapshot of which forecast values triggered the
            alert, e.g.::

                {"temperature_max": {"value": 36.2, "operator": ">",
                                     "threshold": 35}}
        forecast_date: The calendar date on which the threshold was exceeded.
        is_active: ``True`` for alerts from the most recent ETL run;
            ``False`` for all previous runs.
        created_at: UTC timestamp of alert creation.
        expires_at: Optional UTC timestamp after which the alert is no longer
            relevant. Currently not set by the pipeline (reserved for future use).
    """
    __tablename__ = "weather_alerts"

    id            = Column(Integer, primary_key=True, index=True)
    city          = Column(String(100), nullable=False)
    alert_name    = Column(String(100), nullable=False)
    severity      = Column(String(20), nullable=False)
    message       = Column(Text, nullable=False)
    condition_met = Column(JSONB)
    forecast_date = Column(Date)
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    expires_at    = Column(DateTime(timezone=True))
