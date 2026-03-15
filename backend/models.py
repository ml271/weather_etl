"""
Models – SQLAlchemy ORM Modelle (spiegeln das DB-Schema aus init.sql)
"""
from sqlalchemy import Column, Integer, String, Numeric, Boolean, Date, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from database import Base


class WeatherDaily(Base):
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
    __tablename__ = "stations"

    id      = Column(Integer, primary_key=True, index=True)
    name    = Column(String(100), nullable=False)
    region  = Column(String(100))
    country = Column(String(50), default="Germany")
    lat     = Column(Numeric(9, 6), nullable=False)
    lon     = Column(Numeric(9, 6), nullable=False)


class User(Base):
    __tablename__ = "users"

    id              = Column(Integer, primary_key=True, index=True)
    email           = Column(String(255), unique=True, nullable=False, index=True)
    username        = Column(String(100), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    is_active       = Column(Boolean, default=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())


class WarningTemplate(Base):
    __tablename__ = "warning_templates"

    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String(100), nullable=False)
    description = Column(Text)
    conditions  = Column(JSONB, nullable=False)


class Warning(Base):
    __tablename__ = "warnings"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    station_id  = Column(Integer, ForeignKey("stations.id", ondelete="SET NULL"), nullable=True)
    city        = Column(String(100), nullable=False)
    name        = Column(String(100), nullable=False)
    conditions  = Column(JSONB, nullable=False)
    validity    = Column(JSONB, nullable=False)
    active      = Column(Boolean, default=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WeatherAlert(Base):
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
