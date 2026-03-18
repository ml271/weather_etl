# Weather ETL Pipeline

A complete data engineering project: an automated ETL pipeline that fetches
7-day weather forecasts from the Open-Meteo API, stores them in PostgreSQL,
serves them through a FastAPI REST API, and visualises them on an Nginx-hosted
dashboard.

---

## Architecture Overview

```
Open-Meteo API (public, free)
        |
        | GET /v1/forecast (daily + hourly + soil data)
        v
[Airflow – Extract Task]
  Reads city / coordinates from env vars
  Fetches 7-day forecast (168 h)
  Pushes raw JSON to XCom
        |
        v
[Airflow – Transform Task]
  Pulls raw JSON from XCom
  Reshapes daily + hourly records into flat dicts
  Evaluates alert rules from alerts_config.yaml (AND logic)
  Pushes transformed data to XCom
        |
        v
[Airflow – Load Task]
  Pulls transformed data from XCom
  UPSERT into weather_raw, weather_daily, weather_hourly
  Replaces weather_alerts (deactivate old, insert new)
  Signals backend to clear chart cache
        |
        v
[PostgreSQL 15]   <──────────────────────────────────────────────────────┐
  weather_raw       (raw JSON archive, one row per run)                   |
  weather_daily     (UNIQUE city + date, 7-day window)                    |
  weather_hourly    (UNIQUE city + time, 168-hour window + soil data)     |
  weather_alerts    (system alerts from alerts_config.yaml)               |
  stations          (searchable city registry, pre-seeded ~75 cities)     |
  users             (auth, bcrypt passwords)                              |
  warnings          (user-defined alert rules, JSONB conditions)          |
  warning_notifications (dedup table: one email per warning × date)       |
        |                                                                  |
        v                                                                  |
[FastAPI Backend – port 8000]                                             |
  /forecast/daily    – daily forecast list                                |
  /forecast/hourly   – hourly forecast list                               |
  /summary           – dashboard summary (today + alerts)                 |
  /alerts            – system-generated alerts                            |
  /stats/*           – JSON data for Chart.js                             |
  /charts/*          – Matplotlib PNGs (8-panel + day-detail)            |
  /weather/fetch-now – on-demand fetch (auth required)                    |
  /stations/search   – city autocomplete                                  |
  /auth/*            – register / login / JWT me                          |
  /warnings/*        – CRUD for user warning rules (auth required)        |
        |
        v
[Nginx Frontend – port 80]
  /          → index.html  (city search / station picker)
  /dashboard → dashboard.html (forecast, chart, alerts)
  /warnings  → warnings.html (warning rule management)
  /login     → login.html
  /api/*     → proxy to backend:8000

[MailHog SMTP catch-all – port 1025 / UI 8025]
  Receives HTML email notifications sent by the check_warnings DAG
```

### Airflow DAGs

| DAG ID | Schedule | Purpose |
|---|---|---|
| `weather_etl_pipeline` | `@hourly` | Extract → Transform → Load |
| `check_weather_warnings` | `0 */2 * * *` (every 2 h) | Evaluate user warnings, send emails |

---

## Technology Stack

| Layer | Technology | Version |
|---|---|---|
| Data Source | Open-Meteo API | free tier, no key required |
| Orchestration | Apache Airflow | 2.x / 3.x |
| Database | PostgreSQL | 15 (Alpine) |
| Backend | FastAPI | — |
| ASGI Server | Uvicorn | — |
| ORM | SQLAlchemy | 2.x |
| DB Driver | psycopg2-binary | — |
| Auth | python-jose (JWT HS256) + passlib bcrypt | — |
| Charts | Matplotlib + NumPy | — |
| Frontend | Vanilla JS + Chart.js | — |
| Reverse Proxy | Nginx | Alpine |
| Mail (dev) | MailHog | latest |
| Containerisation | Docker + Docker Compose | 3.8 |

---

## Service Ports

| Service | Port | URL |
|---|---|---|
| Dashboard (Nginx) | 80 | http://localhost |
| FastAPI Backend | 8000 | http://localhost:8000/docs |
| Airflow Webserver | 8080 | http://localhost:8080 |
| PostgreSQL | 5432 | `localhost:5432` |
| MailHog SMTP | 1025 | — |
| MailHog Web UI | 8025 | http://localhost:8025 |

---

## Directory Structure

```
weather_etl/
├── airflow/
│   ├── dags/
│   │   ├── weather_dag.py              ETL pipeline DAG (hourly)
│   │   └── check_weather_warnings.py   Warning notification DAG (every 2 h)
│   └── tasks/
│       ├── extract.py                  Fetch from Open-Meteo API
│       ├── transform.py                Reshape + evaluate alert rules
│       ├── load.py                     UPSERT to PostgreSQL
│       └── check_warnings.py           Evaluate user warnings, send email
├── backend/
│   ├── main.py                         FastAPI app + chart endpoints
│   ├── models.py                       SQLAlchemy ORM models
│   ├── schemas.py                      Pydantic request/response schemas
│   ├── database.py                     Engine + session factory
│   ├── chart_cache.py                  In-memory TTL cache for PNGs
│   └── routers/
│       ├── auth.py                     /auth/* (register, login, me)
│       ├── stations.py                 /stations/search
│       ├── weather_fetch.py            /weather/fetch-now
│       └── warnings.py                /warnings/* (CRUD)
├── config/
│   └── alerts_config.yaml             System-wide alert thresholds
├── docker/
│   ├── init.sql                        DB schema + seed data
│   ├── migrate_session3.sql            Soil data columns migration
│   ├── migrate_session4.sql            Warning notifications migration
│   ├── migrate_soil.sql                Additional soil migration
│   ├── backend.Dockerfile
│   ├── airflow.Dockerfile
│   └── frontend.Dockerfile
├── frontend/
│   ├── index.html                      City search / landing page
│   ├── dashboard.html                  Main forecast dashboard
│   ├── warnings.html                   Warning rule editor
│   ├── login.html                      Login / registration form
│   ├── theme-switcher.html             Theme preview page
│   ├── js/
│   │   ├── app.js                      Dashboard logic
│   │   └── user-menu.js                Shared auth widget
│   └── css/
│       ├── style.css                   Base dark theme
│       ├── theme-fluent.css            Fluent design variant
│       ├── theme-retro.css             Retro terminal variant
│       └── theme-terminal.css          Monochrome terminal variant
├── docker-compose.yml                  Development stack
├── docker-compose.prod.yml             Production stack (no exposed DB port)
├── test_pipeline.py                    Local integration test script
├── API_DOCS.md                         Full API endpoint reference
└── README.md                           This file
```

---

## Setup and Deployment

### Prerequisites

- Docker Engine >= 24 and Docker Compose >= 2
- Ports 80, 8000, 8080, 5432, 1025, 8025 must be free

### 1. Configure Environment

Copy `.env` and adjust values:

```bash
cp .env .env.local  # optional: keep customisations separate
```

Key environment variables:

| Variable | Default | Description |
|---|---|---|
| `DEFAULT_CITY` | `Freiburg` | City loaded by the ETL pipeline |
| `DEFAULT_LATITUDE` | `47.9990` | Latitude for `DEFAULT_CITY` |
| `DEFAULT_LONGITUDE` | `7.8421` | Longitude for `DEFAULT_CITY` |
| `POSTGRES_USER` | `weather_user` | PostgreSQL username |
| `POSTGRES_PASSWORD` | `weather_pass` | PostgreSQL password (change in production) |
| `POSTGRES_DB` | `weather_db` | PostgreSQL database name |
| `SECRET_KEY` | *(required)* | HS256 signing key for JWTs. Use a long random string |
| `AIRFLOW_WWW_USER_USERNAME` | `admin` | Airflow UI login |
| `AIRFLOW_WWW_USER_PASSWORD` | `admin` | Airflow UI password (change in production) |
| `ALLOWED_ORIGINS` | `http://localhost,http://localhost:80` | CORS allowed origins |
| `SMTP_HOST` | `mailhog` | SMTP server hostname |
| `SMTP_PORT` | `1025` | SMTP server port |

### 2. Start the Stack

```bash
docker compose up -d --build
```

First startup takes approximately 2–3 minutes. Airflow runs `db migrate` and
creates the admin user before the scheduler starts.

### 3. Verify

```bash
# Check all containers are running
docker compose ps

# Check the API is healthy
curl http://localhost:8000/health

# Run the local integration test (API + DB)
python test_pipeline.py
```

### 4. Trigger the First Pipeline Run

```bash
# Via Airflow UI: http://localhost:8080 → DAG: weather_etl_pipeline → Trigger
# Or via CLI:
docker exec weather_airflow_scheduler airflow dags trigger weather_etl_pipeline
```

After the pipeline completes (~30 s), the dashboard at http://localhost will
show the forecast for `DEFAULT_CITY`.

---

## Alert Configuration

System-wide alerts are defined in `config/alerts_config.yaml`. The transform
task evaluates these rules during every pipeline run and stores triggered alerts
in the `weather_alerts` table.

```yaml
alerts:
  - name: "Extreme Hitze"
    enabled: true
    severity: danger          # info | warning | danger
    message: "Extreme Hitze erwartet!"
    conditions:
      temperature_max:        # field from weather_daily
        operator: ">"         # > | >= | < | <= | ==
        value: 35             # unit matches the field (°C for temperature)
```

Supported condition fields: `temperature_max`, `temperature_min`,
`precipitation_sum`, `snowfall_sum`, `wind_speed_max`, `wind_gusts_max`,
`uv_index_max`.

Multiple conditions in a single rule are combined with AND logic.

---

## User-Defined Warnings

Authenticated users can create personal warning rules via the warnings page at
http://localhost/warnings.html or directly through the API (`/warnings/*`).

Unlike system alerts (evaluated by the Airflow transform task), user warnings
are evaluated by the separate `check_weather_warnings` DAG which runs every 2
hours and sends an HTML email notification when conditions are met.

Supported validity types:
- `date_range`: active between two specific dates
- `weekdays`: active on selected days of the week (e.g. only weekends)
- `months`: active during selected months (e.g. only in summer)

---

## Local Testing

```bash
# Test Extract + Transform only (no DB needed)
python test_pipeline.py --no-db --no-api

# Full test including DB writes (PostgreSQL must be running)
python test_pipeline.py

# Test with a different city
python test_pipeline.py --city München --lat 48.135 --lon 11.582

# Skip API endpoint checks
python test_pipeline.py --no-api
```

---

## Production Deployment

Use `docker-compose.prod.yml` which:
- Does not expose PostgreSQL port 5432 to the host
- Disables Airflow example DAGs

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Before deploying to production:
1. Set a strong, unique `SECRET_KEY` (minimum 32 random characters)
2. Change `POSTGRES_PASSWORD` and `AIRFLOW_WWW_USER_PASSWORD`
3. Update `ALLOWED_ORIGINS` to your actual domain
4. Configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` for real email delivery
5. Set `AIRFLOW__CORE__FERNET_KEY` to a valid Fernet key

---

## API Reference

See [API_DOCS.md](API_DOCS.md) for the complete endpoint reference, or visit
the interactive Swagger UI at http://localhost:8000/docs.
