FROM apache/airflow:2.9.1-python3.11

# WICHTIG: Eigene requirements-airflow.txt ohne SQLAlchemy verwenden,
# damit Airflows interne SQLAlchemy-Version nicht überschrieben wird.
COPY requirements-airflow.txt /requirements-airflow.txt
RUN pip install --no-cache-dir -r /requirements-airflow.txt
