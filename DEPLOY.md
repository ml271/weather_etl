# Deployment auf Linux-Server

## Voraussetzungen
- Docker + Docker Compose installiert
- Git installiert
- Port 80 in der Firewall offen

## Setup

```bash
# 1. Repo clonen
git clone <dein-repo-url> weather_etl
cd weather_etl

# 2. .env anlegen (NICHT im Repo – manuell kopieren oder anlegen)
cp .env.example .env   # falls vorhanden, sonst manuell anlegen
nano .env              # Werte anpassen (Passwörter, SMTP, etc.)

# 3. Container bauen und starten (Produktionsmodus)
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

# 4. DB-Migration ausführen (nur beim ersten Mal)
docker exec weather_postgres psql -U <POSTGRES_USER> -d <POSTGRES_DB> -c "
CREATE TABLE IF NOT EXISTS warning_notifications (
    id SERIAL PRIMARY KEY,
    warning_id INTEGER NOT NULL REFERENCES warnings(id) ON DELETE CASCADE,
    forecast_date DATE NOT NULL,
    sent_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(warning_id, forecast_date)
);
"
```

## .env Pflichtfelder für Produktion

```env
POSTGRES_USER=weather_user
POSTGRES_PASSWORD=<sicheres-passwort>
POSTGRES_DB=weather_db
POSTGRES_HOST=postgres
POSTGRES_PORT=5432

AIRFLOW_WWW_USER_USERNAME=admin
AIRFLOW_WWW_USER_PASSWORD=<sicheres-passwort>
AIRFLOW__CORE__FERNET_KEY=<generieren: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION=true
AIRFLOW__CORE__LOAD_EXAMPLES=false

DEFAULT_CITY=Freiburg
DEFAULT_LATITUDE=47.9990
DEFAULT_LONGITUDE=7.8421

# Brevo SMTP (echte Emails)
SMTP_HOST=smtp-relay.brevo.com
SMTP_PORT=587
SMTP_USER=<brevo-login-email>
SMTP_PASSWORD=<brevo-smtp-key>
SMTP_FROM=<verifizierte-absender-email>

SECRET_KEY=<sicherer-random-string>
```

## Ports nach dem Start

| Dienst   | Port | Öffentlich (Prod) |
|----------|------|-------------------|
| Frontend | 80   | ✅ Ja             |
| Backend  | 8000 | ❌ Nur intern     |
| Airflow  | 8080 | ❌ Nur intern     |
| Postgres | 5432 | ❌ Nur intern     |
| Mailhog  | 8025 | ❌ Nur intern     |

## Updates einspielen

```bash
git pull
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

## Logs prüfen

```bash
docker-compose logs -f backend
docker-compose logs -f airflow-scheduler
```
