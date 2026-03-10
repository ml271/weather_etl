"""
Load Task – Transformierte Wetterdaten in PostgreSQL schreiben
"""
import os
import json
import logging
import psycopg2
import psycopg2.extras
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def get_connection():
    """Erstellt eine PostgreSQL-Verbindung aus Umgebungsvariablen."""
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=int(os.getenv("POSTGRES_PORT", 5432)),
        dbname=os.getenv("POSTGRES_DB", "weather_db"),
        user=os.getenv("POSTGRES_USER", "weather_user"),
        password=os.getenv("POSTGRES_PASSWORD", "weather_pass"),
    )


def load_raw(cursor, city: str, latitude: float, longitude: float, raw_json: dict):
    """Speichert den Roh-API-Response."""
    cursor.execute(
        """
        INSERT INTO weather_raw (city, latitude, longitude, raw_json)
        VALUES (%s, %s, %s, %s)
        """,
        (city, latitude, longitude, json.dumps(raw_json)),
    )
    logger.info(f"Inserted raw record for {city}")


def load_daily(cursor, records: list[dict]):
    """
    Speichert tägliche Wetterdaten – UPSERT (Update bei Konflikt).
    So bleibt die DB immer mit den aktuellsten Vorhersagedaten.
    """
    if not records:
        return

    sql = """
        INSERT INTO weather_daily (
            city, forecast_date,
            temperature_max, temperature_min,
            precipitation_sum, snowfall_sum,
            wind_speed_max, wind_gusts_max,
            weather_code, uv_index_max,
            sunrise, sunset
        ) VALUES (
            %(city)s, %(forecast_date)s,
            %(temperature_max)s, %(temperature_min)s,
            %(precipitation_sum)s, %(snowfall_sum)s,
            %(wind_speed_max)s, %(wind_gusts_max)s,
            %(weather_code)s, %(uv_index_max)s,
            %(sunrise)s, %(sunset)s
        )
        ON CONFLICT (city, forecast_date) DO UPDATE SET
            temperature_max   = EXCLUDED.temperature_max,
            temperature_min   = EXCLUDED.temperature_min,
            precipitation_sum = EXCLUDED.precipitation_sum,
            snowfall_sum      = EXCLUDED.snowfall_sum,
            wind_speed_max    = EXCLUDED.wind_speed_max,
            wind_gusts_max    = EXCLUDED.wind_gusts_max,
            weather_code      = EXCLUDED.weather_code,
            uv_index_max      = EXCLUDED.uv_index_max,
            sunrise           = EXCLUDED.sunrise,
            sunset            = EXCLUDED.sunset,
            created_at        = NOW()
    """
    psycopg2.extras.execute_batch(cursor, sql, records)
    logger.info(f"Upserted {len(records)} daily records")


def load_hourly(cursor, records: list[dict]):
    """Speichert stündliche Wetterdaten – UPSERT."""
    if not records:
        return

    sql = """
        INSERT INTO weather_hourly (
            city, forecast_time,
            temperature, feels_like,
            precipitation, rain, snowfall,
            wind_speed, wind_direction,
            humidity, sunshine_duration,
            weather_code, is_day
        ) VALUES (
            %(city)s, %(forecast_time)s,
            %(temperature)s, %(feels_like)s,
            %(precipitation)s, %(rain)s, %(snowfall)s,
            %(wind_speed)s, %(wind_direction)s,
            %(humidity)s, %(sunshine_duration)s,
            %(weather_code)s, %(is_day)s
        )
        ON CONFLICT (city, forecast_time) DO UPDATE SET
            temperature        = EXCLUDED.temperature,
            feels_like         = EXCLUDED.feels_like,
            precipitation      = EXCLUDED.precipitation,
            rain               = EXCLUDED.rain,
            snowfall           = EXCLUDED.snowfall,
            wind_speed         = EXCLUDED.wind_speed,
            wind_direction     = EXCLUDED.wind_direction,
            humidity           = EXCLUDED.humidity,
            sunshine_duration  = EXCLUDED.sunshine_duration,
            weather_code       = EXCLUDED.weather_code,
            is_day             = EXCLUDED.is_day,
            created_at         = NOW()
    """
    psycopg2.extras.execute_batch(cursor, sql, records)
    logger.info(f"Upserted {len(records)} hourly records")


def load_alerts(cursor, city: str, alerts: list[dict]):
    """
    Speichert neue Alerts – deaktiviert zuerst alte aktive Alerts
    für dieselbe Stadt, dann werden die neuen eingefügt.
    Vermeidet so doppelte Benachrichtigungen.
    """
    # Alte Alerts für diese Stadt deaktivieren
    cursor.execute(
        "UPDATE weather_alerts SET is_active = FALSE WHERE city = %s AND is_active = TRUE",
        (city,),
    )
    deactivated = cursor.rowcount
    if deactivated > 0:
        logger.info(f"Deactivated {deactivated} old alerts for {city}")

    if not alerts:
        logger.info(f"No new alerts for {city}")
        return

    sql = """
        INSERT INTO weather_alerts (
            city, alert_name, severity, message,
            condition_met, forecast_date, is_active
        ) VALUES (
            %(city)s, %(alert_name)s, %(severity)s, %(message)s,
            %(condition_met)s, %(forecast_date)s, %(is_active)s
        )
    """

    # condition_met dict → JSON string
    for alert in alerts:
        alert["condition_met"] = json.dumps(alert["condition_met"])

    psycopg2.extras.execute_batch(cursor, sql, alerts)
    logger.info(f"Inserted {len(alerts)} new alerts for {city}")


# ─────────────────────────────────────────────────────
# Airflow Task Entry Point
# ─────────────────────────────────────────────────────

def load(**context):
    """
    Airflow Task Function – liest transformierte Daten aus XCom
    und schreibt sie in PostgreSQL. Alles in einer Transaktion.
    """
    ti = context["ti"]
    data = ti.xcom_pull(task_ids="transform", key="transformed_weather")

    if not data:
        raise ValueError("No transformed weather data found in XCom!")

    city     = data["city"]
    meta     = data["raw_meta"]
    raw_json = data["raw_json"]
    daily    = data["daily"]
    hourly   = data["hourly"]
    alerts   = data["alerts"]

    conn = get_connection()
    try:
        with conn:  # Transaktion – bei Fehler automatisch Rollback
            with conn.cursor() as cur:
                load_raw(cur, city, meta["latitude"], meta["longitude"], raw_json)
                load_daily(cur, daily)
                load_hourly(cur, hourly)
                load_alerts(cur, city, alerts)

        logger.info(
            f"Load complete for {city}: "
            f"{len(daily)} daily, {len(hourly)} hourly, {len(alerts)} alerts"
        )
    except Exception as e:
        logger.error(f"Load failed for {city}: {e}")
        raise
    finally:
        conn.close()
