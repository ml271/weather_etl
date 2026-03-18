"""
Airflow ETL – Load Task
========================

Reads transformed weather data from Airflow XCom (produced by the transform
task) and writes it to the PostgreSQL database in a single atomic transaction.

Tables written (in order):
  1. ``weather_raw``    – raw API JSON snapshot (one row per pipeline run)
  2. ``weather_daily``  – daily forecast records (UPSERT on city + date)
  3. ``weather_hourly`` – hourly forecast records (UPSERT on city + time)
  4. ``weather_alerts`` – deactivates stale alerts, inserts new ones

All four writes are wrapped in a single psycopg2 transaction (``with conn:``).
If any write fails the entire transaction is rolled back, leaving the database
in the state from the previous successful run.

After a successful commit, the load task calls ``POST /charts/cache-clear`` on
the backend service to evict stale chart PNGs from the in-memory cache. This
call is non-critical: a failure is logged at WARNING level but does not fail the
Airflow task.

Environment variables:
  POSTGRES_HOST      (default: ``postgres``)
  POSTGRES_PORT      (default: ``5432``)
  POSTGRES_DB        (default: ``weather_db``)
  POSTGRES_USER      (default: ``weather_user``)
  POSTGRES_PASSWORD  (default: ``weather_pass``)

Dependencies:
  psycopg2-binary, requests

Author: <project maintainer>
"""
import os
import json
import logging
import requests
import psycopg2
import psycopg2.extras
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def get_connection():
    """Create and return a new psycopg2 connection to the PostgreSQL database.

    Connection parameters are read from environment variables with safe
    fallback defaults that match the Docker Compose configuration.

    Returns:
        A new, open ``psycopg2.extensions.connection`` object.

    Raises:
        psycopg2.OperationalError: When the database is unreachable or the
            credentials are invalid.
    """
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=int(os.getenv("POSTGRES_PORT", 5432)),
        dbname=os.getenv("POSTGRES_DB", "weather_db"),
        user=os.getenv("POSTGRES_USER", "weather_user"),
        password=os.getenv("POSTGRES_PASSWORD", "weather_pass"),
    )


def load_raw(cursor, city: str, latitude: float, longitude: float, raw_json: dict):
    """Insert one row into ``weather_raw`` with the full API response snapshot.

    The raw JSON is stored verbatim for auditing and future re-processing
    without re-fetching from the API. The table has no UNIQUE constraint so
    every pipeline run creates a new row.

    Args:
        cursor: An open psycopg2 cursor within an active transaction.
        city: City name to associate with this snapshot.
        latitude: Geographic latitude used for the API request.
        longitude: Geographic longitude used for the API request.
        raw_json: Full Open-Meteo JSON response as a Python dict. Serialised
                  to a JSON string before insertion.
    """
    cursor.execute(
        """
        INSERT INTO weather_raw (city, latitude, longitude, raw_json)
        VALUES (%s, %s, %s, %s)
        """,
        (city, latitude, longitude, json.dumps(raw_json)),
    )
    logger.info(f"Inserted raw record for {city}")


def load_daily(cursor, records: list[dict]):
    """Upsert a list of daily forecast records into ``weather_daily``.

    Uses ``psycopg2.extras.execute_batch`` to send all rows in a single
    batched network call for performance. On conflict (same ``city`` and
    ``forecast_date``) all mutable columns are overwritten with the incoming
    values and ``created_at`` is reset to ``NOW()``, so repeated runs always
    reflect the most recent forecast.

    Args:
        cursor: An open psycopg2 cursor within an active transaction.
        records: List of daily record dicts as produced by
                 ``transform.transform_daily()``. Each dict must contain the
                 keys: ``city``, ``forecast_date``, ``temperature_max``,
                 ``temperature_min``, ``precipitation_sum``, ``snowfall_sum``,
                 ``wind_speed_max``, ``wind_gusts_max``, ``weather_code``,
                 ``uv_index_max``, ``sunrise``, ``sunset``.

    Side effects:
        Performs no action and returns immediately when ``records`` is empty.
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
    """Upsert a list of hourly forecast records into ``weather_hourly``.

    Uses ``psycopg2.extras.execute_batch`` for batched insertion performance.
    On conflict (same ``city`` and ``forecast_time``) all columns are overwritten
    with the incoming values.

    Args:
        cursor: An open psycopg2 cursor within an active transaction.
        records: List of hourly record dicts as produced by
                 ``transform.transform_hourly()``. Each dict must contain the
                 keys: ``city``, ``forecast_time``, ``temperature``,
                 ``feels_like``, ``precipitation``, ``rain``, ``snowfall``,
                 ``wind_speed``, ``wind_direction``, ``humidity``,
                 ``sunshine_duration``, ``weather_code``, ``is_day``,
                 ``soil_temperature_0cm``, ``soil_temperature_6cm``,
                 ``soil_temperature_18cm``, ``soil_moisture_0_1cm``,
                 ``soil_moisture_1_3cm``, ``soil_moisture_3_9cm``.

    Side effects:
        Performs no action and returns immediately when ``records`` is empty.
    """
    if not records:
        return

    sql = """
        INSERT INTO weather_hourly (
            city, forecast_time,
            temperature, feels_like,
            precipitation, rain, snowfall,
            wind_speed, wind_direction,
            humidity, sunshine_duration,
            weather_code, is_day,
            soil_temperature_0cm, soil_temperature_6cm, soil_temperature_18cm,
            soil_moisture_0_1cm, soil_moisture_1_3cm, soil_moisture_3_9cm
        ) VALUES (
            %(city)s, %(forecast_time)s,
            %(temperature)s, %(feels_like)s,
            %(precipitation)s, %(rain)s, %(snowfall)s,
            %(wind_speed)s, %(wind_direction)s,
            %(humidity)s, %(sunshine_duration)s,
            %(weather_code)s, %(is_day)s,
            %(soil_temperature_0cm)s, %(soil_temperature_6cm)s, %(soil_temperature_18cm)s,
            %(soil_moisture_0_1cm)s, %(soil_moisture_1_3cm)s, %(soil_moisture_3_9cm)s
        )
        ON CONFLICT (city, forecast_time) DO UPDATE SET
            temperature           = EXCLUDED.temperature,
            feels_like            = EXCLUDED.feels_like,
            precipitation         = EXCLUDED.precipitation,
            rain                  = EXCLUDED.rain,
            snowfall              = EXCLUDED.snowfall,
            wind_speed            = EXCLUDED.wind_speed,
            wind_direction        = EXCLUDED.wind_direction,
            humidity              = EXCLUDED.humidity,
            sunshine_duration     = EXCLUDED.sunshine_duration,
            weather_code          = EXCLUDED.weather_code,
            is_day                = EXCLUDED.is_day,
            soil_temperature_0cm  = EXCLUDED.soil_temperature_0cm,
            soil_temperature_6cm  = EXCLUDED.soil_temperature_6cm,
            soil_temperature_18cm = EXCLUDED.soil_temperature_18cm,
            soil_moisture_0_1cm   = EXCLUDED.soil_moisture_0_1cm,
            soil_moisture_1_3cm   = EXCLUDED.soil_moisture_1_3cm,
            soil_moisture_3_9cm   = EXCLUDED.soil_moisture_3_9cm,
            created_at            = NOW()
    """
    psycopg2.extras.execute_batch(cursor, sql, records)
    logger.info(f"Upserted {len(records)} hourly records")


def load_alerts(cursor, city: str, alerts: list[dict]):
    """Replace active alerts for a city with the newly generated ones.

    First deactivates all currently active alerts for the city (setting
    ``is_active = FALSE``), then inserts the new alerts as active rows. This
    two-step approach ensures that the dashboard always shows only the alerts
    produced by the most recent pipeline run, without accumulating historical
    duplicates.

    ``condition_met`` dicts are serialised to JSON strings before insertion
    because psycopg2 does not automatically convert Python dicts to the
    PostgreSQL ``JSONB`` type without the ``psycopg2.extras.Json`` adapter.

    Args:
        cursor: An open psycopg2 cursor within an active transaction.
        city: City name used to scope the deactivation query.
        alerts: List of alert dicts as produced by
                ``transform.generate_alerts()``. Each dict must contain the
                keys: ``city``, ``alert_name``, ``severity``, ``message``,
                ``condition_met`` (dict), ``forecast_date``, ``is_active``.

    Side effects:
        Mutates each dict in ``alerts`` by replacing ``condition_met``
        (a Python dict) with its JSON string representation. Callers should
        not reuse the ``alerts`` list after this function returns.
    """
    # Deactivate all currently active alerts for this city before inserting fresh ones
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
    """Airflow task entry point for the load step.

    Pulls the transformed weather data from XCom (written by the transform
    task) and writes all four data types (raw, daily, hourly, alerts) to the
    PostgreSQL database in a single atomic transaction.

    After a successful commit, signals the backend to invalidate the chart
    cache via ``POST /charts/cache-clear``. This call is non-critical: a
    failure is caught, logged, and does not re-raise so the Airflow task is
    still marked as successful.

    This function is registered as a ``PythonOperator`` callable in
    ``airflow/dags/weather_dag.py``.

    Args:
        **context: Airflow task context dict. Must contain ``context["ti"]``
                   (TaskInstance) to enable XCom pull operations.

    Raises:
        ValueError: When no transformed weather data is found in XCom from
            the transform task.
        Exception: Any database error causes the transaction to roll back
            automatically (psycopg2 ``with conn:`` context manager) and the
            exception is re-raised so Airflow can retry the task.

    Side effects:
        - Pulls ``"transformed_weather"`` from XCom (task_id: ``"transform"``).
        - Writes to ``weather_raw``, ``weather_daily``, ``weather_hourly``, and
          ``weather_alerts`` tables in a single transaction.
        - Calls ``POST http://backend:8000/charts/cache-clear`` (non-critical).
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

    # Invalidate chart cache so the next request regenerates fresh charts
    try:
        requests.post(
            "http://backend:8000/charts/cache-clear",
            params={"city": city},
            headers={"X-Internal-Token": os.getenv("INTERNAL_API_TOKEN", "")},
            timeout=5,
        )
        logger.info(f"Chart cache cleared for {city}")
    except Exception as e:
        logger.warning(f"Chart cache clear failed (non-critical): {e}")
