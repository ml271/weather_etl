"""
Pydantic Schemas – API Request / Response Serialisation
========================================================

This module defines all Pydantic models used as FastAPI request bodies and
response models. It also contains the WMO weather-code lookup tables that are
shared between the backend API responses and the Airflow transform task.

Design notes:
  - All response schemas use ``model_config = ConfigDict(from_attributes=True)``
    so that SQLAlchemy ORM instances can be passed directly to
    ``Model.model_validate(orm_obj)``.
  - ``computed_field`` properties (``weather_description``, ``weather_icon``)
    are automatically included in serialised output without requiring an extra
    DB column.
  - Warning condition and validity schemas intentionally use ``Any`` for the
    ``WarningOut`` fields because the JSONB content is already validated at
    write-time and stored as-is.

Dependencies:
  pydantic >= 2.0

Author: marivn lorff and claude code
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, computed_field

# ── WMO Weather Code Lookup Tables ───────────────────────────────────────────

# Maps WMO weather interpretation codes to German-language descriptions.
# Source: https://open-meteo.com/en/docs (section "WMO Weather interpretation codes")
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

# Maps WMO codes to emoji icons for compact UI display.
# Multiple codes may share the same icon where the visual distinction is not needed.
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


# ── Forecast Schemas ──────────────────────────────────────────────────────────

class WeatherDailySchema(BaseModel):
    """Serialised representation of a ``WeatherDaily`` ORM row.

    Adds two computed fields (``weather_description``, ``weather_icon``) that
    translate the raw WMO integer code into human-readable text and an emoji,
    without storing these redundant values in the database.

    Attributes:
        id: Database primary key.
        city: City name.
        forecast_date: The calendar date this record describes.
        temperature_max: Maximum temperature in °C. ``None`` if not available.
        temperature_min: Minimum temperature in °C. ``None`` if not available.
        precipitation_sum: Total daily precipitation in mm. ``None`` if not
            available.
        snowfall_sum: Total daily snowfall in cm. ``None`` if not available.
        wind_speed_max: Maximum wind speed in km/h. ``None`` if not available.
        wind_gusts_max: Maximum wind gust speed in km/h. ``None`` if not
            available.
        weather_code: WMO weather interpretation code. ``None`` if not available.
        uv_index_max: Maximum UV index (0–11+). ``None`` if not available.
        sunrise: Local sunrise time as a timezone-aware UTC datetime. ``None``
            if not available.
        sunset: Local sunset time as a timezone-aware UTC datetime. ``None``
            if not available.
        created_at: UTC timestamp of the last data import for this row.
        weather_description: Computed. German-language description of the
            weather code (e.g. "Leichter Regen"). Falls back to "Unbekannt"
            for unmapped codes.
        weather_icon: Computed. Emoji icon for the weather code (e.g. "🌧️").
            Falls back to "🌡️" for unmapped codes.
    """
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
        """Return a German-language description for the WMO weather code.

        Returns:
            The description string from ``WMO_CODES``, or ``"Unbekannt"``
            when the code is ``None`` or not found in the lookup table.
        """
        return WMO_CODES.get(self.weather_code, "Unbekannt")

    @computed_field
    @property
    def weather_icon(self) -> str:
        """Return an emoji icon for the WMO weather code.

        Returns:
            The emoji string from ``WMO_ICONS``, or ``"🌡️"`` when the code
            is ``None`` or not found in the lookup table.
        """
        return WMO_ICONS.get(self.weather_code, "🌡️")


class WeatherHourlySchema(BaseModel):
    """Serialised representation of a ``WeatherHourly`` ORM row.

    Adds computed ``weather_description`` and ``weather_icon`` fields.
    Soil data columns are intentionally excluded from this schema to keep the
    JSON payload small; they are only used inside the Matplotlib chart endpoint.

    Attributes:
        id: Database primary key.
        city: City name.
        forecast_time: UTC timestamp for this hour, timezone-aware.
        temperature: Air temperature at 2 m in °C.
        feels_like: Apparent temperature at 2 m in °C.
        precipitation: Total precipitation during this hour in mm.
        rain: Rain component of precipitation in mm.
        snowfall: Snowfall component in cm.
        wind_speed: Wind speed at 10 m in km/h.
        wind_direction: Wind direction in degrees (0 = N, 90 = E, …).
        humidity: Relative humidity in percent (0–100).
        sunshine_duration: Direct sunshine duration in seconds per hour
            (0–3600).
        weather_code: WMO weather interpretation code.
        is_day: ``True`` during daylight hours.
        weather_description: Computed. German weather description.
        weather_icon: Computed. Weather emoji icon.
    """
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
        """Return a German-language description for the WMO weather code.

        Returns:
            The description string from ``WMO_CODES``, or ``"Unbekannt"``
            when the code is ``None`` or not found in the lookup table.
        """
        return WMO_CODES.get(self.weather_code, "Unbekannt")

    @computed_field
    @property
    def weather_icon(self) -> str:
        """Return an emoji icon for the WMO weather code.

        Returns:
            The emoji string from ``WMO_ICONS``, or ``"🌡️"`` when the code
            is ``None`` or not found in the lookup table.
        """
        return WMO_ICONS.get(self.weather_code, "🌡️")


class WeatherAlertSchema(BaseModel):
    """Serialised representation of a ``WeatherAlert`` ORM row.

    Attributes:
        id: Database primary key.
        city: City the alert applies to.
        alert_name: Name of the alert rule that was triggered.
        severity: Alert severity level: ``"info"``, ``"warning"``, or
            ``"danger"``.
        message: Human-readable alert message.
        condition_met: JSONB snapshot of the values that triggered the alert.
            Structure varies per rule; may be ``None`` for legacy rows.
        forecast_date: The date on which the threshold was exceeded.
        is_active: ``True`` if this alert is from the most recent ETL run.
        created_at: UTC timestamp of alert creation.
    """
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


# ── Auth Schemas ──────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    """Request body for ``POST /auth/register``.

    Attributes:
        email: Valid email address. Must be unique across all users.
        username: Login handle. Must be unique across all users.
        password: Plaintext password. Will be hashed with bcrypt before storage.
    """
    email:    str
    username: str
    password: str


class LoginRequest(BaseModel):
    """Request body for ``POST /auth/login``.

    Attributes:
        username: The user's login handle (not email).
        password: Plaintext password for verification against the stored hash.
    """
    username: str
    password: str


class TokenResponse(BaseModel):
    """Response body for ``POST /auth/login``.

    Attributes:
        access_token: Signed HS256 JWT valid for 24 hours. Include as
            ``Authorization: Bearer <token>`` in protected requests.
        token_type: Always ``"bearer"`` per the OAuth2 specification.
    """
    access_token: str
    token_type:   str = "bearer"


class UserOut(BaseModel):
    """Public user profile returned by ``GET /auth/me`` and ``POST /auth/register``.

    Deliberately excludes ``hashed_password`` and ``is_active`` to avoid
    leaking security-sensitive fields.

    Attributes:
        id: Database primary key.
        email: The user's email address.
        username: The user's login handle.
        created_at: UTC timestamp of account creation.
    """
    model_config = ConfigDict(from_attributes=True)
    id:         int
    email:      str
    username:   str
    created_at: Optional[datetime] = None


# ── Warning Schemas ───────────────────────────────────────────────────────────

class ConditionRule(BaseModel):
    """A single threshold condition for a weather warning.

    Multiple ``ConditionRule`` instances in a warning's ``conditions`` list are
    evaluated with AND logic: all rules must be satisfied for the warning to fire.

    Attributes:
        parameter: The ``weather_daily`` column to evaluate. Supported values:
            ``"temperature_max"``, ``"temperature_min"``,
            ``"precipitation_sum"``, ``"snowfall_sum"``,
            ``"wind_speed_max"``, ``"wind_gusts_max"``, ``"uv_index_max"``.
        comparator: Comparison operator as a string. One of:
            ``">"``, ``">="``, ``"<"``, ``"<="``, ``"=="``.
        value: Numeric threshold to compare the forecast value against.
        label: Optional human-readable label for the parameter shown in email
            notifications (e.g. ``"Temperatur max."``). Falls back to
            ``parameter`` when omitted.
    """
    parameter:  str
    comparator: str
    value:      float
    label:      Optional[str] = None


class WarningTemplateOut(BaseModel):
    """Serialised representation of a ``WarningTemplate`` ORM row.

    Attributes:
        id: Database primary key.
        name: Template name (e.g. "Hitzwarnung").
        description: Optional longer description.
        conditions: List of ``ConditionRule`` objects defining the template's
            threshold criteria.
    """
    model_config = ConfigDict(from_attributes=True)
    id:          int
    name:        str
    description: Optional[str] = None
    conditions:  list[ConditionRule]


class ValiditySpec(BaseModel):
    """Temporal scope specification for a user-defined warning.

    Determines which calendar dates the warning is active for. Exactly one of
    the three validity types must be fully specified:

    - ``date_range``: Active between two ISO-8601 dates (inclusive).
    - ``weekdays``: Active on specific days of the week (0 = Monday … 6 = Sunday).
    - ``months``: Active during specific months of the year (1 = January … 12 = December).

    Attributes:
        type: Validity type identifier. One of ``"date_range"``,
            ``"weekdays"``, or ``"months"``.
        date_from: Start date (ISO-8601 string) for ``"date_range"`` type.
        date_to: End date (ISO-8601 string, inclusive) for ``"date_range"`` type.
        weekdays: List of weekday integers (0–6) for ``"weekdays"`` type.
        months: List of month integers (1–12) for ``"months"`` type.
    """
    type:      str
    date_from: Optional[str] = None
    date_to:   Optional[str] = None
    weekdays:  Optional[list[int]] = None
    months:    Optional[list[int]] = None


class WarningCreate(BaseModel):
    """Request body for ``POST /warnings/`` and ``PUT /warnings/{id}``.

    Attributes:
        station_id: Optional ID of the station from the ``stations`` table.
            Used for UI display only; the ``city`` field drives data lookups.
        city: City name that must match a city in ``weather_daily``.
        name: User-chosen warning name.
        conditions: One or more threshold rules (AND logic).
        validity: Temporal scope specification.
    """
    station_id:    Optional[int] = None
    city:          str
    name:          str
    conditions:    list[ConditionRule]
    validity:      ValiditySpec
    notify_timing: Optional[str] = "as_available"  # 'as_available' | '1d'..'6d'


class WarningOut(BaseModel):
    """Serialised representation of a ``Warning`` ORM row.

    ``conditions`` and ``validity`` are typed as ``Any`` because they are
    stored as opaque JSONB in the database and returned verbatim without
    re-validation.

    Attributes:
        id: Database primary key.
        station_id: Optional station reference.
        city: City the warning monitors.
        name: User-chosen warning name.
        conditions: Raw JSONB list of condition rule objects.
        validity: Raw JSONB validity specification object.
        active: Whether the warning is currently active.
        created_at: UTC creation timestamp.
        updated_at: UTC last-modified timestamp.
    """
    model_config = ConfigDict(from_attributes=True)
    id:            int
    station_id:    Optional[int] = None
    city:          str
    name:          str
    conditions:    Any
    validity:      Any
    notify_timing: Optional[str] = "as_available"
    active:        bool
    created_at:    Optional[datetime] = None
    updated_at:    Optional[datetime] = None


# ── Dashboard Summary ─────────────────────────────────────────────────────────

class ForecastSummary(BaseModel):
    """Aggregated dashboard summary response for ``GET /summary``.

    Combines the most important data points into a single API call to minimise
    round-trips on dashboard load.

    Attributes:
        city: The resolved city name.
        today: Today's (or the nearest upcoming) daily forecast record.
            ``None`` when no data has been loaded for this city.
        alerts_count: Total number of currently active alerts.
        active_alerts: List of active alerts sorted by severity (danger →
            warning → info) then by forecast date ascending.
        last_updated: UTC timestamp of the most recent data import for this
            city. ``None`` when no data exists.
    """
    city:          str
    today:         Optional[WeatherDailySchema] = None
    alerts_count:  int
    active_alerts: list[WeatherAlertSchema]
    last_updated:  Optional[datetime] = None
