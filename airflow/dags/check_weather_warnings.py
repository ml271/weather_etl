"""
Check Weather Warnings DAG – Prüft User-Warnungen gegen aktuelle Vorhersagedaten
und sendet Email-Benachrichtigungen wenn Bedingungen erfüllt sind.

Läuft alle 2 Stunden. Liest ausschließlich aus der DB (keine API-Calls).
"""
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.empty import EmptyOperator

import sys
sys.path.insert(0, "/opt/airflow")

from tasks.check_warnings import check_warnings

# ─────────────────────────────────────────────────────
# DAG Default Arguments
# ─────────────────────────────────────────────────────
default_args = {
    "owner": "weather-etl",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

# ─────────────────────────────────────────────────────
# DAG Definition
# ─────────────────────────────────────────────────────
with DAG(
    dag_id="check_weather_warnings",
    description="Prüft User-Warnungen gegen Vorhersagedaten und sendet Email-Alerts",
    default_args=default_args,
    schedule="0 */2 * * *",          # Alle 2 Stunden
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["weather", "warnings", "email"],
) as dag:

    start = EmptyOperator(task_id="start")
    end   = EmptyOperator(task_id="end")

    check_task = PythonOperator(
        task_id="check_warnings",
        python_callable=check_warnings,
        doc_md="""
        ## Check Warnings
        - Lädt alle aktiven User-Warnungen aus der DB
        - Prüft jede Warnung gegen die nächsten 7 Tage der Tagesvorhersage
        - Bewertet Bedingungen (AND-Logik) gegen `weather_daily`
        - Sendet eine Email pro (Warnung × Vorhersagedatum) wenn Bedingungen erfüllt
        - Vermeidet Duplikate via `warning_notifications`-Tabelle
        """,
    )

    start >> check_task >> end
