"""
Weather ETL Pipeline – Airflow DAG

Läuft stündlich und:
  1. Extrahiert Wetterdaten von Open-Meteo API (Extract)
  2. Bereinigt und berechnet Alerts (Transform)
  3. Schreibt in PostgreSQL (Load)
"""
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.empty import EmptyOperator

import sys
sys.path.insert(0, "/opt/airflow")

from tasks.extract import extract
from tasks.transform import transform
from tasks.load import load

# ─────────────────────────────────────────────────────
# DAG Default Arguments
# ─────────────────────────────────────────────────────
default_args = {
    "owner": "weather-etl",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 3,
    "retry_delay": timedelta(minutes=2),
}

# ─────────────────────────────────────────────────────
# DAG Definition
# ─────────────────────────────────────────────────────
with DAG(
    dag_id="weather_etl_pipeline",
    description="Holt Wetterdaten von Open-Meteo, transformiert sie und speichert in PostgreSQL",
    default_args=default_args,
    schedule="@hourly",              # Stündlich ausführen
    start_date=datetime(2024, 1, 1),
    catchup=False,                   # Keine historischen Runs nachholen
    max_active_runs=1,               # Nie zwei Runs gleichzeitig
    tags=["weather", "etl", "open-meteo"],
) as dag:

    # ── Start / End Marker (für saubere Visualisierung im Airflow UI) ──
    start = EmptyOperator(task_id="start")
    end   = EmptyOperator(task_id="end")

    # ── Extract ───────────────────────────────────────────────────────
    extract_task = PythonOperator(
        task_id="extract",
        python_callable=extract,
        doc_md="""
        ## Extract
        Ruft aktuelle 7-Tage-Wettervorhersage von der Open-Meteo API ab.
        - Tägliche Daten: Temperatur, Niederschlag, Wind, UV, Sonnenauf/-untergang
        - Stündliche Daten: Temperatur, Gefühlte Temperatur, Regen, Schnee, Wind, Luftfeuchtigkeit
        Ergebnis wird via XCom weitergegeben.
        """,
    )

    # ── Transform ─────────────────────────────────────────────────────
    transform_task = PythonOperator(
        task_id="transform",
        python_callable=transform,
        doc_md="""
        ## Transform
        - Bereinigt und strukturiert die Rohdaten
        - Ordnet WMO-Wettercodes lesbaren Beschreibungen zu
        - Evaluiert Alert-Regeln aus `alerts_config.yaml`
        - Gibt tägliche Records, stündliche Records und ausgelöste Alerts zurück
        """,
    )

    # ── Load ──────────────────────────────────────────────────────────
    load_task = PythonOperator(
        task_id="load",
        python_callable=load,
        doc_md="""
        ## Load
        - Schreibt Rohdaten in `weather_raw`
        - UPSERT tägliche Daten in `weather_daily`
        - UPSERT stündliche Daten in `weather_hourly`
        - Deaktiviert alte Alerts, fügt neue ein in `weather_alerts`
        Alles in einer atomaren Transaktion.
        """,
    )

    # ── Task Reihenfolge ──────────────────────────────────────────────
    start >> extract_task >> transform_task >> load_task >> end
