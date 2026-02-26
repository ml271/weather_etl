"""
Transform Task – Rohdaten bereinigen, strukturieren und Alerts berechnen
"""
import os
import logging
import yaml
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# WMO Weather Code → lesbarer Text
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


# ─────────────────────────────────────────────────────
# Hilfsfunktionen
# ─────────────────────────────────────────────────────

def safe_get(lst: list, index: int, default=None):
    """Sicherer Listenzugriff ohne IndexError."""
    try:
        val = lst[index]
        return val if val is not None else default
    except (IndexError, TypeError):
        return default


def apply_operator(value: float, operator: str, threshold: float) -> bool:
    """Wertet eine Alert-Bedingung aus."""
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
    """Lädt die Alert-Konfiguration aus der YAML-Datei."""
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        alerts = [a for a in config.get("alerts", []) if a.get("enabled", True)]
        logger.info(f"Loaded {len(alerts)} active alert rules from {config_path}")
        return alerts
    except FileNotFoundError:
        logger.warning(f"Alert config not found at {config_path}, no alerts will be generated.")
        return []


# ─────────────────────────────────────────────────────
# Transform Funktionen
# ─────────────────────────────────────────────────────

def transform_daily(city: str, daily: dict) -> list[dict]:
    """Verarbeitet die täglichen Wetterdaten in strukturierte Records."""
    records = []
    times = daily.get("time", [])

    for i, date_str in enumerate(times):
        record = {
            "city": city,
            "forecast_date": date_str,
            "temperature_max":   safe_get(daily.get("temperature_2m_max"), i),
            "temperature_min":   safe_get(daily.get("temperature_2m_min"), i),
            "precipitation_sum": safe_get(daily.get("precipitation_sum"), i, 0.0),
            "snowfall_sum":      safe_get(daily.get("snowfall_sum"), i, 0.0),
            "wind_speed_max":    safe_get(daily.get("wind_speed_10m_max"), i),
            "wind_gusts_max":    safe_get(daily.get("wind_gusts_10m_max"), i),
            "weather_code":      safe_get(daily.get("weather_code"), i),
            "uv_index_max":      safe_get(daily.get("uv_index_max"), i),
            "sunrise":           safe_get(daily.get("sunrise"), i),
            "sunset":            safe_get(daily.get("sunset"), i),
            # Zusatzfelder für Frontend
            "weather_description": WMO_CODES.get(safe_get(daily.get("weather_code"), i), "Unbekannt"),
        }
        records.append(record)

    logger.info(f"Transformed {len(records)} daily records for {city}")
    return records


def transform_hourly(city: str, hourly: dict) -> list[dict]:
    """Verarbeitet die stündlichen Wetterdaten."""
    records = []
    times = hourly.get("time", [])

    for i, time_str in enumerate(times):
        record = {
            "city": city,
            "forecast_time":  time_str,
            "temperature":    safe_get(hourly.get("temperature_2m"), i),
            "feels_like":     safe_get(hourly.get("apparent_temperature"), i),
            "precipitation":  safe_get(hourly.get("precipitation"), i, 0.0),
            "rain":           safe_get(hourly.get("rain"), i, 0.0),
            "snowfall":       safe_get(hourly.get("snowfall"), i, 0.0),
            "wind_speed":     safe_get(hourly.get("wind_speed_10m"), i),
            "wind_direction": safe_get(hourly.get("wind_direction_10m"), i),
            "humidity":       safe_get(hourly.get("relative_humidity_2m"), i),
            "weather_code":   safe_get(hourly.get("weather_code"), i),
            "is_day":         bool(safe_get(hourly.get("is_day"), i, 1)),
        }
        records.append(record)

    logger.info(f"Transformed {len(records)} hourly records for {city}")
    return records


def generate_alerts(city: str, daily_records: list[dict], alert_rules: list[dict]) -> list[dict]:
    """
    Vergleicht tägliche Wetterdaten mit konfigurierten Alert-Regeln.
    Gibt eine Liste ausgelöster Alerts zurück.
    """
    alerts = []

    # Feld-Mapping: YAML-Key → Feldname im daily_record
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
                    continue

                value = record.get(db_field)
                if value is None:
                    all_met = False
                    break

                operator = condition.get("operator", ">")
                threshold = condition.get("value")

                if not apply_operator(float(value), operator, float(threshold)):
                    all_met = False
                    break
                else:
                    triggered_values[yaml_field] = {"value": value, "operator": operator, "threshold": threshold}

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
                logger.info(f"Alert triggered: [{rule['severity'].upper()}] {rule['name']} for {city} on {record['forecast_date']}")

    logger.info(f"Generated {len(alerts)} alerts for {city}")
    return alerts


# ─────────────────────────────────────────────────────
# Airflow Task Entry Point
# ─────────────────────────────────────────────────────

def transform(**context) -> dict:
    """
    Airflow Task Function – liest Raw-Daten aus XCom,
    transformiert sie und schreibt Ergebnisse zurück.
    """
    ti = context["ti"]
    raw = ti.xcom_pull(task_ids="extract", key="raw_weather")

    if not raw:
        raise ValueError("No raw weather data found in XCom from extract task!")

    city = raw["city"]
    api_data = raw["data"]

    # Transform
    daily_records  = transform_daily(city, api_data.get("daily", {}))
    hourly_records = transform_hourly(city, api_data.get("hourly", {}))

    # Alerts
    config_path = os.getenv("ALERT_CONFIG_PATH", "/opt/airflow/config/alerts_config.yaml")
    alert_rules = load_alert_config(config_path)
    alerts = generate_alerts(city, daily_records, alert_rules)

    result = {
        "city":        city,
        "raw_meta":    {"fetched_at": raw["fetched_at"], "latitude": raw["latitude"], "longitude": raw["longitude"]},
        "raw_json":    api_data,
        "daily":       daily_records,
        "hourly":      hourly_records,
        "alerts":      alerts,
    }

    ti.xcom_push(key="transformed_weather", value=result)
    logger.info(f"Transform complete: {len(daily_records)} daily, {len(hourly_records)} hourly, {len(alerts)} alerts")
    return result
