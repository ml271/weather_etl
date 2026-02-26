"""
Schemas – Pydantic Modelle für Response Serialisierung
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, computed_field

WMO_CODES = {
    0: "Klarer Himmel",
    1: "Überwiegend klar", 2: "Teilweise bewölkt", 3: "Bedeckt",
    45: "Nebel", 48: "Reifnebel",
    51: "Leichter Nieselregen", 53: "Mäßiger Nieselregen", 55: "Starker Nieselregen",
    61: "Leichter Regen", 63: "Mäßiger Regen", 65: "Starker Regen",
    71: "Leichter Schneefall", 73: "Mäßiger Schneefall", 75: "Starker Schneefall",
    77: "Schneekörner",
    80: "Leichte Regenschauer", 81: "Mäßige Regenschauer", 82: "Starke Regenschauer",
    85: "Leichte Schneeschauer", 86: "Starke Schneeschauer",
    95: "Gewitter", 96: "Gewitter mit leichtem Hagel", 99: "Gewitter mit starkem Hagel",
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
        return WMO_CODES.get(self.weather_code, "Unbekannt")

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
    wind_direction: Optional[int] = None
    humidity:       Optional[int] = None
    weather_code:   Optional[int] = None
    is_day:         Optional[bool] = None

    @computed_field
    @property
    def weather_description(self) -> str:
        return WMO_CODES.get(self.weather_code, "Unbekannt")

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


class ForecastSummary(BaseModel):
    city:          str
    today:         Optional[WeatherDailySchema] = None
    alerts_count:  int
    active_alerts: list[WeatherAlertSchema]
    last_updated:  Optional[datetime] = None
