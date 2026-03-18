"""
Schemas – Pydantic models for response serialization
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, computed_field

WMO_CODES = {
    0: "Clear sky",
    1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snowfall", 73: "Moderate snowfall", 75: "Heavy snowfall",
    77: "Snow grains",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}

WMO_ICONS = {
    0: "☀️", 1: "🌤️", 2: "⛅", 3: "☁️",
    45: "🌫️", 48: "🌫️",
    51: "🌦️", 53: "🌦️", 55: "🌧️",
    61: "🌧️", 63: "🌧️", 65: "🌧️",
    71: "❄️", 73: "❄️", 75: "❄️", 77: "🌨️",
    80: "🌦️", 81: "🌧️", 82: "⛈️",
    85: "🌨️", 86: "🌨️",
    95: "⛈️", 96: "⛈️", 99: "⛈️",
}


class WeatherDailySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:                int
    city:              str
    forecast_date:     date
    temperature_max:   Optional[Decimal] = None
    temperature_min:   Optional[Decimal] = None
    precipitation_sum: Optional[Decimal] = None
    snowfall_sum:      Optional[Decimal] = None
    wind_speed_max:    Optional[Decimal] = None
    wind_gusts_max:    Optional[Decimal] = None
    weather_code:      Optional[int] = None
    uv_index_max:      Optional[Decimal] = None
    sunrise:           Optional[datetime] = None
    sunset:            Optional[datetime] = None
    created_at:        Optional[datetime] = None

    @computed_field
    @property
    def weather_description(self) -> str:
        return WMO_CODES.get(self.weather_code, "Unknown")

    @computed_field
    @property
    def weather_icon(self) -> str:
        return WMO_ICONS.get(self.weather_code, "🌡️")


class WeatherHourlySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:             int
    city:           str
    forecast_time:  datetime
    temperature:    Optional[Decimal] = None
    feels_like:     Optional[Decimal] = None
    precipitation:  Optional[Decimal] = None
    rain:           Optional[Decimal] = None
    snowfall:       Optional[Decimal] = None
    wind_speed:     Optional[Decimal] = None
    wind_direction:    Optional[int] = None
    humidity:          Optional[int] = None
    sunshine_duration: Optional[Decimal] = None
    weather_code:      Optional[int] = None
    is_day:         Optional[bool] = None

    @computed_field
    @property
    def weather_description(self) -> str:
        return WMO_CODES.get(self.weather_code, "Unknown")

    @computed_field
    @property
    def weather_icon(self) -> str:
        return WMO_ICONS.get(self.weather_code, "🌡️")


class WeatherAlertSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:            int
    city:          str
    alert_name:    str
    severity:      str
    message:       str
    condition_met: Optional[Any] = None
    forecast_date: Optional[date] = None
    is_active:     bool
    created_at:    Optional[datetime] = None


class RegisterRequest(BaseModel):
    email:    str
    username: str
    password: str

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id:         int
    email:      str
    username:   str
    created_at: Optional[datetime] = None


# ── Warning schemas ──────────────────────────────────────────────────────────

class ConditionRule(BaseModel):
    parameter:  str           # e.g. "temperature_max"
    comparator: str           # ">", "<", ">=", "<=", "=="
    value:      float
    label:      Optional[str] = None   # human-readable label

class WarningTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id:          int
    name:        str
    description: Optional[str] = None
    conditions:  list[ConditionRule]

class ValiditySpec(BaseModel):
    type:      str                        # "date_range" | "weekdays" | "months"
    date_from: Optional[str] = None      # ISO date string for date_range
    date_to:   Optional[str] = None
    weekdays:  Optional[list[int]] = None   # 0=Mon … 6=Sun
    months:    Optional[list[int]] = None   # 1=Jan … 12=Dec
    notify_offset_type:  Optional[str] = None   # "same_day" | "days_before" | "hours_before"
    notify_offset_value: Optional[int] = None   # X for days_before / hours_before

class WarningCreate(BaseModel):
    station_id: Optional[int] = None
    city:       str
    name:       str
    conditions: list[ConditionRule]
    validity:   ValiditySpec

class WarningOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id:         int
    station_id: Optional[int] = None
    city:       str
    name:       str
    conditions: Any
    validity:   Any
    active:     bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ForecastSummary(BaseModel):
    city:          str
    today:         Optional[WeatherDailySchema] = None
    alerts_count:  int
    active_alerts: list[WeatherAlertSchema]
    last_updated:  Optional[datetime] = None
