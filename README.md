# 🌤️ Weather ETL Pipeline

Ein Data Engineering Capstone Projekt – vollständige ETL Pipeline für Wetterdaten mit Apache Airflow, PostgreSQL, FastAPI und Nginx.

## 🏗️ Architektur

```
Open-Meteo API → [Extract] → [Transform + Alerts] → [Load] → PostgreSQL
                                                                    ↓
                                                    FastAPI Backend (REST)
                                                                    ↓
                                                    Nginx Frontend (Dashboard)
```

## 🚀 Quick Start

### 1. Voraussetzungen
- Docker & Docker Compose installiert
- Ports frei: 80, 8000, 8080, 5432

### 2. Starten

```bash
# Repository klonen / in den Projektordner wechseln
cd weather-etl

# .env anpassen (optional)
cp .env .env.local

# Stack starten
docker compose up -d --build

# Logs verfolgen
docker compose logs -f
```

### 3. Services

| Service         | URL                        | Zugangsdaten     |
|----------------|----------------------------|-----------------|
| 🌐 Dashboard    | http://localhost           | –               |
| ⚙️ Airflow UI   | http://localhost:8080       | admin / admin   |
| 🔌 Backend API  | http://localhost:8000/docs  | –               |
| 🗄️ PostgreSQL   | localhost:5432              | weather_user/.. |

## 📁 Projektstruktur

```
weather-etl/
├── airflow/
│   ├── dags/           # Airflow DAG Definitionen
│   └── tasks/          # ETL Task Module
├── backend/            # FastAPI REST API
├── frontend/           # Nginx + HTML/JS Dashboard
├── config/
│   └── alerts_config.yaml   # ⚙️ Alert-Regeln konfigurieren!
└── docker/             # Dockerfiles + SQL Schema
```

## ⚙️ Alerts konfigurieren

Editiere `config/alerts_config.yaml` um eigene Wetterwarnungen zu definieren:

```yaml
alerts:
  - name: "Meine Warnung"
    enabled: true
    severity: warning          # info | warning | danger
    message: "Beschreibung..."
    conditions:
      temperature_max:
        operator: ">"
        value: 30
```

## 🔄 Pipeline manuell triggern

```bash
# Via Airflow UI: http://localhost:8080
# DAG: weather_etl_pipeline → ▶ Trigger DAG

# Oder via CLI:
docker exec weather_airflow_scheduler airflow dags trigger weather_etl_pipeline
```
