"""
Airflow ETL – Transform Task
=============================

Reads raw Open-Meteo API data from Airflow XCom (produced by the extract task),
restructures it into flat dicts suitable for database insertion, and evaluates
alert rules from a YAML configuration file.

Steps performed:
  1. Pull ``raw_weather`` from XCom (pushed by the extract task).
  2. Transform the ``"daily"`` API response into a list of daily records
     (one dict per calendar day).
  3. Transform the ``"hourly"`` API response into a list of hourly records
     (one dict per hour).
  4. Load alert rules from ``ALERT_CONFIG_PATH`` (default:
     ``/opt/airflow/config/alerts_config.yaml``).
  5. Evaluate each alert rule against every daily record (AND logic across
     all conditions in a rule).
  6. Push the combined result dict to XCom under ``"transformed_weather"``
     for the load task to consume.

XCom output (key ``"transformed_weather"``):
  A dict with the structure::

      {
        "city":     "Freiburg",
        "raw_meta": {"fetched_at": "...", "latitude": ..., "longitude": ...},
        "raw_json": { <original Open-Meteo JSON> },
        "daily":    [ {city, forecast_date, temperature_max, ...}, ... ],
        "hourly":   [ {city, forecast_time, temperature, ...}, ... ],
        "alerts":   [ {city, alert_name, severity, message, ...}, ... ],
      }

Environment variables:
  ALERT_CONFIG_PATH – path to the YAML alert configuration file
                      (default: ``/opt/airflow/config/alerts_config.yaml``)

Dependencies:
  pyyaml

Author: <project maintainer>
"""

import os
import logging
import yaml
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# WMO weather interpretation code → German description.
# Used to enrich daily records with a human-readable ``weather_description`` field.
# Source: https://open-meteo.com/en/docs
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


# ── Helper Functions ──────────────────────────────────────────────────────────

def safe_get(lst: list, index: int, default=None):
    """Safely retrieve element ``index`` from a list without raising on bounds errors.

    Handles two common cases when unpacking Open-Meteo API lists:
    - The list is shorter than expected (``IndexError``).
    - The element value is explicitly ``None`` from the API response.

    Args:
        lst: Any list-like object, or ``None``.
        index: Zero-based index to retrieve.
        default: Value to return when the element is unavailable or ``None``.
                 Defaults to ``None``.

    Returns:
        ``lst[index]`` when it exists and is not ``None``, otherwise ``default``.
    """
    try:
        val = lst[index]
        return val if val is not None else default
    except (IndexError, TypeError):
        return default


def apply_operator(value: float, operator: str, threshold: float) -> bool:
    """Evaluate a comparison expression: ``value <operator> threshold``.

    Used by ``generate_alerts()`` to test each condition in an alert rule.

    Args:
        value: The actual forecast value (e.g. ``36.2`` for temperature_max).
        operator: Comparison operator string. Supported values:
                  ``">"``, ``">="``, ``"<"``, ``"<="``, ``"=="``.
        threshold: The configured threshold value from the alert rule.

    Returns:
        ``True`` if the comparison holds, ``False`` if it does not or if the
        operator string is not recognised.

    Example:
        >>> apply_operator(36.2, ">", 35.0)
        True
        >>> apply_operator(10.0, ">=", 20.0)
        False
    """
    ops = {
        ">":  lambda a, b: a > b,
        ">=": lambda a, b: a >= b,
        "<":  lambda a, b: a < b,
        "<=": lambda a, b: a <= b,
        "==": lambda a, b: a == b,
    }
    fn = ops.get(operator)
    if fn is None:
        logger.warning(f"Unknown operator: {operator}")
        return False
    return fn(value, threshold)


def load_alert_config(config_path: str) -> list[dict]:
    """Load and filter the alert rule configuration from a YAML file.

    Reads the YAML file at ``config_path``, extracts the ``alerts`` list, and
    returns only rules where ``enabled`` is ``True`` (or absent, defaulting to
    ``True``).

    Args:
        config_path: Absolute path to the YAML configuration file.
                     Expected structure::

                         alerts:
                           - name: "Extreme Hitze"
                             enabled: true
                             severity: danger
                             message: "..."
                             conditions:
                               temperature_max:
                                 operator: ">"
                                 value: 35

    Returns:
        A list of enabled alert rule dicts. Returns an empty list if the file
        does not exist (to allow the pipeline to run without any alert rules).

    Side effects:
        Logs a WARNING when the config file is not found.
    """
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        # Filter out disabled rules to avoid evaluating them unnecessarily
        alerts = [a for a in config.get("alerts", []) if a.get("enabled", True)]
        logger.info(f"Loaded {len(alerts)} active alert rules from {config_path}")
        return alerts
    except FileNotFoundError:
        logger.warning(f"Alert config not found at {config_path}, no alerts will be generated.")
        return []


# ── Transform Functions ───────────────────────────────────────────────────────

def transform_daily(city: str, daily: dict) -> list[dict]:
    """Convert the Open-Meteo ``"daily"`` response block into a list of flat record dicts.

    Each output dict corresponds to one calendar day and contains all fields
    required for insertion into the ``weather_daily`` database table. An extra
    ``weather_description`` field is added for frontend convenience (not stored
    in the DB; the DB schema derives it on-demand from the WMO code).

    Args:
        city: City name to embed in every record's ``city`` field.
        daily: The ``"daily"`` sub-dict from the Open-Meteo JSON response.
               Must contain at least a ``"time"`` key with a list of ISO-8601
               date strings.

    Returns:
        A list of dicts, one per day. Each dict contains:
        ``city``, ``forecast_date``, ``temperature_max``, ``temperature_min``,
        ``precipitation_sum``, ``snowfall_sum``, ``wind_speed_max``,
        ``wind_gusts_max``, ``weather_code``, ``uv_index_max``, ``sunrise``,
        ``sunset``, ``weather_description``.
    """
    records = []
    times = daily.get("time", [])

    for i, date_str in enumerate(times):
        weather_code = safe_get(daily.get("weather_code"), i)
        record = {
            "city":            city,
            "forecast_date":   date_str,
            "temperature_max":   safe_get(daily.get("temperature_2m_max"), i),
            "temperature_min":   safe_get(daily.get("temperature_2m_min"), i),
            "precipitation_sum": safe_get(daily.get("precipitation_sum"), i, 0.0),
            "snowfall_sum":      safe_get(daily.get("snowfall_sum"), i, 0.0),
            "wind_speed_max":    safe_get(daily.get("wind_speed_10m_max"), i),
            "wind_gusts_max":    safe_get(daily.get("wind_gusts_10m_max"), i),
            "weather_code":      weather_code,
            "uv_index_max":      safe_get(daily.get("uv_index_max"), i),
            "sunrise":           safe_get(daily.get("sunrise"), i),
            "sunset":            safe_get(daily.get("sunset"), i),
            # Derived label for frontend display; not persisted to the database
            "weather_description": WMO_CODES.get(weather_code, "Unbekannt"),
        }
        records.append(record)

    logger.info(f"Transformed {len(records)} daily records for {city}")
    return records


def transform_hourly(city: str, hourly: dict) -> list[dict]:
    """Convert the Open-Meteo ``"hourly"`` response block into a list of flat record dicts.

    Each output dict corresponds to one hour and contains all fields required
    for insertion into the ``weather_hourly`` database table, including the
    soil data fields added in Session 3.

    Note: The Open-Meteo API uses ``"soil_moisture_0_to_1cm"`` notation while
    the database column is named ``"soil_moisture_0_1cm"``. The mapping is
    applied here so the load task receives correctly named fields.

    Args:
        city: City name to embed in every record's ``city`` field.
        hourly: The ``"hourly"`` sub-dict from the Open-Meteo JSON response.
                Must contain at least a ``"time"`` key with a list of ISO-8601
                datetime strings (local time, ``"Europe/Berlin"``).

    Returns:
        A list of dicts, one per hour. Each dict contains:
        ``city``, ``forecast_time``, ``temperature``, ``feels_like``,
        ``precipitation``, ``rain``, ``snowfall``, ``wind_speed``,
        ``wind_direction``, ``humidity``, ``sunshine_duration``,
        ``weather_code``, ``is_day``, ``soil_temperature_0cm``,
        ``soil_temperature_6cm``, ``soil_temperature_18cm``,
        ``soil_moisture_0_1cm``, ``soil_moisture_1_3cm``, ``soil_moisture_3_9cm``.
    """
    records = []
    times = hourly.get("time", [])

    for i, time_str in enumerate(times):
        record = {
            "city":           city,
            "forecast_time":  time_str,
            "temperature":    safe_get(hourly.get("temperature_2m"), i),
            "feels_like":     safe_get(hourly.get("apparent_temperature"), i),
            "precipitation":  safe_get(hourly.get("precipitation"), i, 0.0),
            "rain":           safe_get(hourly.get("rain"), i, 0.0),
            "snowfall":       safe_get(hourly.get("snowfall"), i, 0.0),
            "wind_speed":     safe_get(hourly.get("wind_speed_10m"), i),
            "wind_direction": safe_get(hourly.get("wind_direction_10m"), i),
            "humidity":           safe_get(hourly.get("relative_humidity_2m"), i),
            "sunshine_duration":  safe_get(hourly.get("sunshine_duration"), i, 0.0),
            "weather_code":           safe_get(hourly.get("weather_code"), i),
            # is_day is an integer (0/1) from the API; cast to bool for the DB boolean column
            "is_day":                 bool(safe_get(hourly.get("is_day"), i, 1)),
            "soil_temperature_0cm":   safe_get(hourly.get("soil_temperature_0cm"), i),
            "soil_temperature_6cm":   safe_get(hourly.get("soil_temperature_6cm"), i),
            "soil_temperature_18cm":  safe_get(hourly.get("soil_temperature_18cm"), i),
            # Open-Meteo uses "0_to_1cm" notation; DB column is "0_1cm"
            "soil_moisture_0_1cm":    safe_get(hourly.get("soil_moisture_0_to_1cm"), i),
            "soil_moisture_1_3cm":    safe_get(hourly.get("soil_moisture_1_to_3cm"), i),
            "soil_moisture_3_9cm":    safe_get(hourly.get("soil_moisture_3_to_9cm"), i),
        }
        records.append(record)

    logger.info(f"Transformed {len(records)} hourly records for {city}")
    return records


def generate_alerts(city: str, daily_records: list[dict], alert_rules: list[dict]) -> list[dict]:
    """Evaluate alert rules against daily forecast records and return triggered alerts.

    Iterates over every combination of (daily record, alert rule). A rule is
    triggered for a given day if **all** conditions in the rule's ``conditions``
    dict are satisfied simultaneously (AND logic). When triggered, a new alert
    dict is appended to the result list containing the city, rule metadata,
    the affected forecast date, and a snapshot of the values that crossed the
    thresholds.

    Args:
        city: City name to embed in each generated alert's ``city`` field.
        daily_records: List of transformed daily record dicts as returned by
                       ``transform_daily()``.
        alert_rules: List of enabled alert rule dicts as returned by
                     ``load_alert_config()``. Each rule must have the keys
                     ``"name"``, ``"severity"``, ``"message"``, and
                     ``"conditions"`` (a dict of ``{field: {operator, value}}``).

    Returns:
        A list of alert dicts, one per triggered (record, rule) combination.
        Each dict contains:
        ``city``, ``alert_name``, ``severity``, ``message``, ``condition_met``
        (dict of field → ``{value, operator, threshold}``), ``forecast_date``,
        ``is_active`` (always ``True`` for newly generated alerts).
        Returns an empty list when no rules are triggered.
    """
    alerts = []

    # Mapping from YAML config field names → daily record field names.
    # Only these fields are supported in alert conditions.
    field_map = {
        "temperature_max":   "temperature_max",
        "temperature_min":   "temperature_min",
        "precipitation_sum": "precipitation_sum",
        "snowfall_sum":      "snowfall_sum",
        "wind_speed_max":    "wind_speed_max",
        "wind_gusts_max":    "wind_gusts_max",
        "uv_index_max":      "uv_index_max",
    }

    for record in daily_records:
        for rule in alert_rules:
            conditions = rule.get("conditions", {})
            triggered_values = {}
            all_met = True

            for yaml_field, condition in conditions.items():
                db_field = field_map.get(yaml_field)
                if not db_field:
                    # Unknown field in YAML config — skip this condition silently
                    continue

                value = record.get(db_field)
                if value is None:
                    # Missing forecast data means we cannot evaluate this condition;
                    # treat the entire rule as not triggered for this day.
                    all_met = False
                    break

                operator  = condition.get("operator", ">")
                threshold = condition.get("value")

                if not apply_operator(float(value), operator, float(threshold)):
                    all_met = False
                    break
                else:
                    # Record which value triggered this condition for the audit snapshot
                    triggered_values[yaml_field] = {
                        "value":     value,
                        "operator":  operator,
                        "threshold": threshold,
                    }

            if all_met and triggered_values:
                alert = {
                    "city":           city,
                    "alert_name":     rule["name"],
                    "severity":       rule["severity"],
                    "message":        rule["message"],
                    "condition_met":  triggered_values,
                    "forecast_date":  record["forecast_date"],
                    "is_active":      True,
                }
                alerts.append(alert)
                logger.info(
                    f"Alert triggered: [{rule['severity'].upper()}] "
                    f"{rule['name']} for {city} on {record['forecast_date']}"
                )

    logger.info(f"Generated {len(alerts)} alerts for {city}")
    return alerts


# ── Airflow Task Entry Point ───────────────────────────────────────────────────

def transform(**context) -> dict:
    """Airflow task entry point for the transform step.

    Pulls raw weather data from XCom (written by the extract task), applies
    all three transformation steps (daily, hourly, alerts), and pushes the
    combined result back to XCom for the load task.

    This function is registered as a ``PythonOperator`` callable in
    ``airflow/dags/weather_dag.py``.

    Args:
        **context: Airflow task context dict. Must contain ``context["ti"]``
                   (TaskInstance) to enable XCom pull/push operations.

    Returns:
        The transformed data dict (same object that was pushed to XCom under
        the key ``"transformed_weather"``).

    Raises:
        ValueError: When no raw weather data is found in XCom from the
            extract task (e.g. if the extract task was skipped or failed
            without writing to XCom).

    Side effects:
        - Pulls ``"raw_weather"`` from XCom (task_id: ``"extract"``).
        - Pushes the result to XCom under the key ``"transformed_weather"``.
    """
    ti  = context["ti"]
    raw = ti.xcom_pull(task_ids="extract", key="raw_weather")

    if not raw:
        raise ValueError("No raw weather data found in XCom from extract task!")

    city     = raw["city"]
    api_data = raw["data"]

    daily_records  = transform_daily(city, api_data.get("daily", {}))
    hourly_records = transform_hourly(city, api_data.get("hourly", {}))

    # Load alert rules from YAML config; path is overridable via env var
    config_path = os.getenv("ALERT_CONFIG_PATH", "/opt/airflow/config/alerts_config.yaml")
    alert_rules = load_alert_config(config_path)
    alerts = generate_alerts(city, daily_records, alert_rules)

    result = {
        "city":     city,
        "raw_meta": {
            "fetched_at": raw["fetched_at"],
            "latitude":   raw["latitude"],
            "longitude":  raw["longitude"],
        },
        "raw_json": api_data,    # Passed through for storage in weather_raw
        "daily":    daily_records,
        "hourly":   hourly_records,
        "alerts":   alerts,
    }

    ti.xcom_push(key="transformed_weather", value=result)
    logger.info(
        f"Transform complete: {len(daily_records)} daily, "
        f"{len(hourly_records)} hourly, {len(alerts)} alerts"
    )
    return result
