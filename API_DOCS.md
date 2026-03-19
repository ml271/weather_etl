# Weather ETL API – Vollständige Dokumentation

**Version:** 1.0.0
**Framework:** FastAPI
**Base-URL (lokal):** `http://localhost:8000`
**Datenquelle:** Open-Meteo API (`https://api.open-meteo.com/v1/forecast`)

---

## Inhaltsverzeichnis

1. [Übersicht aller Endpoints](#1-übersicht-aller-endpoints)
2. [Authentifizierung](#2-authentifizierung)
3. [System](#3-system)
4. [Authentifizierungs-Endpoints](#4-authentifizierungs-endpoints)
5. [Stationen](#5-stationen)
6. [Wetterdaten abrufen (On-Demand)](#6-wetterdaten-abrufen-on-demand)
7. [Forecast](#7-forecast)
8. [Alerts (System-generiert)](#8-alerts-system-generiert)
9. [Statistik-Daten (Chart-Data)](#9-statistik-daten-chart-data)
10. [Charts (Matplotlib PNG)](#10-charts-matplotlib-png)
11. [Warnungen (User-definiert)](#11-warnungen-user-definiert)
12. [Fehler-Referenz](#12-fehler-referenz)
13. [WMO Wetter-Codes](#13-wmo-wetter-codes)

---

## 1. Übersicht aller Endpoints

| Methode  | Pfad                        | Tag             | Auth erforderlich | Beschreibung                                    |
|----------|-----------------------------|-----------------|-------------------|-------------------------------------------------|
| GET      | `/health`                   | System          | Nein              | Datenbankverbindung und Status prüfen           |
| POST     | `/auth/register`            | Auth            | Nein              | Neuen Benutzer registrieren                     |
| POST     | `/auth/login`               | Auth            | Nein              | Login, JWT-Token erhalten                       |
| GET      | `/auth/me`                  | Auth            | **Ja**            | Eigenes Benutzerprofil abrufen                  |
| GET      | `/stations/search`          | Stations        | Nein              | Stationen nach Name oder Region suchen          |
| POST     | `/weather/fetch-now`        | Weather Fetch   | Nein              | Wetterdaten on-demand von Open-Meteo holen      |
| GET      | `/summary`                  | Forecast        | Nein              | Tages-Zusammenfassung mit aktiven Alerts        |
| GET      | `/forecast/daily`           | Forecast        | Nein              | Tägliche Wettervorhersage (bis 7 Tage)          |
| GET      | `/forecast/hourly`          | Forecast        | Nein              | Stündliche Wettervorhersage (bis 168 Stunden)   |
| GET      | `/alerts`                   | Alerts          | Nein              | System-generierte Wetterwarnungen               |
| GET      | `/alerts/history`           | Alerts          | Nein              | Verlauf aller Wetterwarnungen                   |
| GET      | `/stats/temperature`        | Stats           | Nein              | Temperaturdaten für Chart-Bibliotheken          |
| GET      | `/stats/hourly-temp`        | Stats           | Nein              | Stündliche Temperaturdaten für Charts           |
| GET      | `/charts/hourly-plot`       | Charts          | Nein              | Matplotlib-Diagramm als PNG (mehrtägig)         |
| GET      | `/charts/day-detail`        | Charts          | Nein              | Matplotlib-Tagesdetail als PNG (ein Tag)        |
| POST     | `/charts/cache-clear`       | Charts          | Nein              | Chart-Cache für eine Stadt leeren               |
| GET      | `/warnings/templates`       | Warnings        | Nein              | Vordefinierte Warn-Templates abrufen            |
| GET      | `/warnings/`                | Warnings        | **Ja**            | Eigene Warnungen auflisten                      |
| POST     | `/warnings/`                | Warnings        | **Ja**            | Neue Warnung erstellen                          |
| GET      | `/warnings/{warning_id}`    | Warnings        | **Ja**            | Einzelne Warnung abrufen                        |
| PUT      | `/warnings/{warning_id}`    | Warnings        | **Ja**            | Warnung aktualisieren                           |
| DELETE   | `/warnings/{warning_id}`    | Warnings        | **Ja**            | Warnung löschen                                 |

---

## 2. Authentifizierung

Die API verwendet **JWT Bearer Token Authentication** (JSON Web Token, RFC 7519).

### Ablauf

1. Benutzer registriert sich via `POST /auth/register`
2. Benutzer meldet sich an via `POST /auth/login` und erhält einen `access_token`
3. Für geschützte Endpoints wird der Token im HTTP-Header übermittelt:

```
Authorization: Bearer <access_token>
```

### Token-Details

| Eigenschaft     | Wert                                 |
|-----------------|--------------------------------------|
| Algorithmus     | HS256                                |
| Gültigkeit      | 24 Stunden ab Ausstellung            |
| Payload-Claims  | `sub` (user_id), `username`, `exp`   |
| Header-Name     | `Authorization`                      |
| Schema          | `Bearer`                             |

### Fehler bei ungültigem Token

```json
{
  "detail": "Invalid or expired token"
}
```
HTTP Status: `401 Unauthorized`
Response-Header: `WWW-Authenticate: Bearer`

---

## 3. System

### `GET /health`

Prüft den Status der API und der Datenbankverbindung.

**Authentifizierung:** Nicht erforderlich

**Query-Parameter:** Keine

**Response `200 OK`:**

```json
{
  "status": "ok",
  "timestamp": "2026-03-16T10:30:00.000000+00:00",
  "database": "ok",
  "default_city": "Freiburg"
}
```

| Feld           | Typ      | Beschreibung                                        |
|----------------|----------|-----------------------------------------------------|
| `status`       | `string` | Immer `"ok"` wenn der Server erreichbar ist         |
| `timestamp`    | `string` | ISO-8601 UTC-Zeitstempel der Abfrage                |
| `database`     | `string` | `"ok"` oder Fehlermeldung bei DB-Problem            |
| `default_city` | `string` | Standardstadt aus der Umgebungsvariable `DEFAULT_CITY` |

**Mögliche Fehler:** Keine (HTTP 200 auch bei DB-Fehler, `database`-Feld enthält dann die Fehlermeldung)

---

## 4. Authentifizierungs-Endpoints

### `POST /auth/register`

Registriert einen neuen Benutzer.

**Authentifizierung:** Nicht erforderlich

**Request Body (JSON):**

| Feld       | Typ      | Pflicht | Beschreibung                     |
|------------|----------|---------|----------------------------------|
| `email`    | `string` | Ja      | Eindeutige E-Mail-Adresse        |
| `username` | `string` | Ja      | Eindeutiger Benutzername         |
| `password` | `string` | Ja      | Passwort im Klartext (wird bcrypt-gehasht gespeichert) |

**Beispiel Request:**

```json
{
  "email": "max.mustermann@example.com",
  "username": "maxmustermann",
  "password": "sicheresPasswort123"
}
```

**Response `201 Created`:**

```json
{
  "id": 1,
  "email": "max.mustermann@example.com",
  "username": "maxmustermann",
  "created_at": "2026-03-16T10:30:00.000000+00:00"
}
```

| Feld         | Typ               | Beschreibung                    |
|--------------|-------------------|---------------------------------|
| `id`         | `integer`         | Datenbankid des Benutzers       |
| `email`      | `string`          | Registrierte E-Mail             |
| `username`   | `string`          | Registrierter Benutzername      |
| `created_at` | `string` / `null` | ISO-8601 Erstellungszeitpunkt   |

**Fehler-Responses:**

| Status | Beschreibung                          | Beispiel `detail`             |
|--------|---------------------------------------|-------------------------------|
| `400`  | E-Mail bereits vergeben               | `"Email already registered"`  |
| `400`  | Benutzername bereits vergeben         | `"Username already taken"`    |

---

### `POST /auth/login`

Authentifiziert einen Benutzer und gibt einen JWT-Token zurück.

**Authentifizierung:** Nicht erforderlich

**Request Body (JSON):**

| Feld       | Typ      | Pflicht | Beschreibung      |
|------------|----------|---------|-------------------|
| `username` | `string` | Ja      | Benutzername      |
| `password` | `string` | Ja      | Passwort          |

**Beispiel Request:**

```json
{
  "username": "maxmustermann",
  "password": "sicheresPasswort123"
}
```

**Response `200 OK`:**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwidXNlcm5hbWUiOiJtYXhtdXN0ZXJtYW5uIiwiZXhwIjoxNzQyMTI2NjAwfQ.abc123",
  "token_type": "bearer"
}
```

| Feld           | Typ      | Beschreibung                            |
|----------------|----------|-----------------------------------------|
| `access_token` | `string` | JWT-Token, gültig für 24 Stunden        |
| `token_type`   | `string` | Immer `"bearer"`                        |

**Fehler-Responses:**

| Status | Beschreibung                         | Beispiel `detail`                    |
|--------|--------------------------------------|--------------------------------------|
| `401`  | Ungültige Anmeldedaten               | `"Incorrect username or password"`   |

---

### `GET /auth/me`

Gibt das Profil des aktuell authentifizierten Benutzers zurück.

**Authentifizierung:** **Erforderlich** (Bearer Token)

**Query-Parameter:** Keine

**Response `200 OK`:**

```json
{
  "id": 1,
  "email": "max.mustermann@example.com",
  "username": "maxmustermann",
  "created_at": "2026-03-16T10:30:00.000000+00:00"
}
```

**Fehler-Responses:**

| Status | Beschreibung                         | Beispiel `detail`               |
|--------|--------------------------------------|---------------------------------|
| `401`  | Token fehlt, ungültig oder abgelaufen | `"Invalid or expired token"`   |
| `401`  | Benutzer nicht mehr in der Datenbank  | `"User not found"`             |

---

## 5. Stationen

### `GET /stations/search`

Durchsucht die Stationsdatenbank nach Name oder Region (case-insensitiv).

**Authentifizierung:** Nicht erforderlich

**Query-Parameter:**

| Parameter | Typ       | Pflicht | Standard | Beschreibung                                                                     |
|-----------|-----------|---------|----------|----------------------------------------------------------------------------------|
| `q`       | `string`  | Nein    | `""`     | Suchbegriff: Stadtname oder Bundesland. Leer = erste `limit` Stationen alphabetisch. |
| `limit`   | `integer` | Nein    | `20`     | Maximale Anzahl Treffer. Min: `1`, Max: `100`                                    |

**Suchlogik:**
- Leerer Suchbegriff: Gibt die ersten `limit` Stationen alphabetisch zurück
- Kurze Suche (< 2 Zeichen): Prefix-Match auf Stationsname
- Sonst: `ILIKE`-Suche (`%q%`) auf `name` UND `region`

**Beispiel Request:**

```
GET /stations/search?q=Freiburg&limit=5
```

**Response `200 OK`:**

```json
[
  {
    "station_id": 42,
    "name": "Freiburg im Breisgau",
    "region": "Baden-Württemberg",
    "country": "Germany",
    "lat": "47.995000",
    "lon": "7.849000"
  }
]
```

| Feld         | Typ       | Beschreibung                    |
|--------------|-----------|---------------------------------|
| `station_id` | `integer` | Eindeutige ID der Station       |
| `name`       | `string`  | Stationsname / Stadtname        |
| `region`     | `string` / `null` | Bundesland oder Region  |
| `country`    | `string` / `null` | Land (Standard: `"Germany"`) |
| `lat`        | `string`  | Breitengrad (Decimal)           |
| `lon`        | `string`  | Längengrad (Decimal)            |

**Fehler-Responses:** Keine spezifischen (leere Liste bei keinen Treffern)

---

## 6. Wetterdaten abrufen (On-Demand)

### `POST /weather/fetch-now`

Ruft aktuelle Wetterdaten von der Open-Meteo API ab und persistiert sie direkt in der Datenbank. Invalidiert danach den Chart-Cache für die Stadt und startet einen Hintergrundthread zur Chart-Vorwärmung.

**Authentifizierung:** Nicht erforderlich

**Query-Parameter:**

| Parameter | Typ      | Pflicht | Beschreibung               |
|-----------|----------|---------|----------------------------|
| `city`    | `string` | **Ja**  | Stadtname                  |
| `lat`     | `float`  | **Ja**  | Breitengrad (z.B. `47.995`) |
| `lon`     | `float`  | **Ja**  | Längengrad (z.B. `7.849`)  |

**Hinweis:** Dieser Endpoint verwendet Query-Parameter, keinen Request-Body.

**Beispiel Request:**

```
POST /weather/fetch-now?city=Freiburg&lat=47.995&lon=7.849
```

**Abgerufene Variablen (Open-Meteo):**

*Täglich:* `temperature_2m_max`, `temperature_2m_min`, `precipitation_sum`, `snowfall_sum`, `wind_speed_10m_max`, `wind_gusts_10m_max`, `weather_code`, `uv_index_max`, `sunrise`, `sunset`

*Stündlich:* `temperature_2m`, `apparent_temperature`, `precipitation`, `rain`, `snowfall`, `wind_speed_10m`, `wind_direction_10m`, `relative_humidity_2m`, `sunshine_duration`, `weather_code`, `is_day`, `soil_temperature_0cm`, `soil_temperature_6cm`, `soil_temperature_18cm`, `soil_moisture_0_to_1cm`, `soil_moisture_1_to_3cm`, `soil_moisture_3_to_9cm`

**Response `200 OK`:**

```json
{
  "status": "ok",
  "city": "Freiburg",
  "fetched_at": "2026-03-16T10:30:00.000000+00:00"
}
```

| Feld         | Typ      | Beschreibung                         |
|--------------|----------|--------------------------------------|
| `status`     | `string` | Immer `"ok"` bei Erfolg              |
| `city`       | `string` | Stadtname aus dem Query-Parameter    |
| `fetched_at` | `string` | ISO-8601 UTC-Zeitstempel des Abrufs  |

**Fehler-Responses:**

| Status | Beschreibung                          | Beispiel `detail`                                          |
|--------|---------------------------------------|------------------------------------------------------------|
| `504`  | Open-Meteo API antwortet nicht        | `"Open-Meteo API Timeout – bitte nochmal versuchen."`      |
| `502`  | Open-Meteo gibt    HTTP-Fehler zurück | `"Open-Meteo Fehler: 422 Client Error: ..."`               |
| `500`  | Unerwarteter interner Fehler          | Fehlermeldung als String                                   |

---

## 7. Forecast

### `GET /summary`

Gibt eine kompakte Zusammenfassung für das Dashboard zurück: heutiger Tagesforecast, Anzahl aktiver Alerts und die aktiven Alerts selbst, priorisiert nach Schweregrad.

**Authentifizierung:** Nicht erforderlich

**Query-Parameter:**

| Parameter | Typ      | Pflicht | Standard          | Beschreibung         |
|-----------|----------|---------|-------------------|----------------------|
| `city`    | `string` | Nein    | `DEFAULT_CITY` (env) | Stadtname         |

**Response `200 OK`:**

```json
{
  "city": "Freiburg",
  "today": {
    "id": 101,
    "city": "Freiburg",
    "forecast_date": "2026-03-16",
    "temperature_max": "14.50",
    "temperature_min": "6.20",
    "precipitation_sum": "0.00",
    "snowfall_sum": "0.00",
    "wind_speed_max": "18.30",
    "wind_gusts_max": "32.10",
    "weather_code": 2,
    "uv_index_max": "3.10",
    "sunrise": "2026-03-16T06:21:00+00:00",
    "sunset": "2026-03-16T17:48:00+00:00",
    "created_at": "2026-03-16T05:00:00+00:00",
    "weather_description": "Teilweise bewölkt",
    "weather_icon": "⛅"
  },
  "alerts_count": 1,
  "active_alerts": [
    {
      "id": 5,
      "city": "Freiburg",
      "alert_name": "Starker Wind",
      "severity": "warning",
      "message": "Windgeschwindigkeit überschreitet 30 km/h",
      "condition_met": {"parameter": "wind_speed_max", "value": 32.1},
      "forecast_date": "2026-03-16",
      "is_active": true,
      "created_at": "2026-03-16T05:00:00+00:00"
    }
  ],
  "last_updated": "2026-03-16T05:00:00+00:00"
}
```

Alert-Sortierung: `danger` vor `warning` vor sonstigen Schweregraden, dann aufsteigend nach `forecast_date`.

**Fehler-Responses:** Keine (leere/null-Felder wenn keine Daten vorhanden)

---

### `GET /forecast/daily`

Gibt die tägliche Wettervorhersage ab heute zurück.

**Authentifizierung:** Nicht erforderlich

**Query-Parameter:**

| Parameter | Typ       | Pflicht | Standard          | Beschreibung                             |
|-----------|-----------|---------|-------------------|------------------------------------------|
| `city`    | `string`  | Nein    |`DEFAULT_CITY`(env)| Stadtname                                |
| `days`    | `integer` | Nein    | `4`               | Anzahl Tage. Min: `1`, Max: `7`          |

**Response `200 OK`** – Array von `WeatherDailySchema`:

```json
[
  {
    "id": 101,
    "city": "Freiburg",
    "forecast_date": "2026-03-16",
    "temperature_max": "14.50",
    "temperature_min": "6.20",
    "precipitation_sum": "2.40",
    "snowfall_sum": "0.00",
    "wind_speed_max": "18.30",
    "wind_gusts_max": "32.10",
    "weather_code": 61,
    "uv_index_max": "2.50",
    "sunrise": "2026-03-16T06:21:00+00:00",
    "sunset": "2026-03-16T17:48:00+00:00",
    "created_at": "2026-03-16T05:00:00+00:00",
    "weather_description": "Leichter Regen",
    "weather_icon": "🌧️"
  }
]
```

**WeatherDailySchema – Felder:**

| Feld                  | Typ               | Beschreibung                                     |
|-----------------------|-------------------|--------------------------------------------------|
| `id`                  | `integer`         | Datenbankid                                      |
| `city`                | `string`          | Stadtname                                        |
| `forecast_date`       | `string` (date)   | Prognosedatum `YYYY-MM-DD`                       |
| `temperature_max`     | `string` / `null` | Tagesmaximum in °C (Decimal)                     |
| `temperature_min`     | `string` / `null` | Tagesminimum in °C (Decimal)                     |
| `precipitation_sum`   | `string` / `null` | Gesamtniederschlag in mm                         |
| `snowfall_sum`        | `string` / `null` | Gesamtschneefall in mm                           |
| `wind_speed_max`      | `string` / `null` | Maximale Windgeschwindigkeit in km/h             |
| `wind_gusts_max`      | `string` / `null` | Maximale Windböen in km/h                        |
| `weather_code`        | `integer` / `null`| WMO Wettercode (siehe Abschnitt 13)              |
| `uv_index_max`        | `string` / `null` | Maximaler UV-Index                               |
| `sunrise`             | `string` / `null` | Sonnenaufgang als ISO-8601 Datetime              |
| `sunset`              | `string` / `null` | Sonnenuntergang als ISO-8601 Datetime            |
| `created_at`          | `string` / `null` | Zeitpunkt der letzten Aktualisierung             |
| `weather_description` | `string`          | Computed: Deutsch-Text zum WMO-Code              |
| `weather_icon`        | `string`          | Computed: Emoji zum WMO-Code                     |

**Fehler-Responses:**

| Status | Beschreibung                     | Beispiel `detail`                                                         |
|--------|----------------------------------|---------------------------------------------------------------------------|
| `404`  | Keine Daten für die Stadt        | `"Keine Daten für 'Berlin'. Bitte zuerst den Airflow DAG triggern."`      |

---

### `GET /forecast/hourly`

Gibt die stündliche Wettervorhersage ab jetzt (UTC) zurück.

**Authentifizierung:** Nicht erforderlich

**Query-Parameter:**

| Parameter | Typ       | Pflicht | Standard          | Beschreibung                              |
|-----------|-----------|---------|-------------------|-------------------------------------------|
| `city`    | `string`  | Nein    |`DEFAULT_CITY`(env)| Stadtname                                 |
| `hours`   | `integer` | Nein    | `24`              | Anzahl Stunden. Min: `1`, Max: `168` (7 Tage) |

**Response `200 OK`** – Array von `WeatherHourlySchema`:

```json
[
  {
    "id": 2001,
    "city": "Freiburg",
    "forecast_time": "2026-03-16T11:00:00+00:00",
    "temperature": "12.30",
    "feels_like": "9.80",
    "precipitation": "0.10",
    "rain": "0.10",
    "snowfall": "0.00",
    "wind_speed": "15.20",
    "wind_direction": 230,
    "humidity": 72,
    "sunshine_duration": "1800.00",
    "weather_code": 2,
    "is_day": true,
    "weather_description": "Teilweise bewölkt",
    "weather_icon": "⛅"
  }
]
```

**WeatherHourlySchema – Felder:**

| Feld                  | Typ               | Beschreibung                                          |
|-----------------------|-------------------|-------------------------------------------------------|
| `id`                  | `integer`         | Datenbankid                                           |
| `city`                | `string`          | Stadtname                                             |
| `forecast_time`       | `string` (datetime)| Prognosezeitpunkt ISO-8601 mit Timezone               |
| `temperature`         | `string` / `null` | Temperatur in °C (2m-Höhe)                            |
| `feels_like`          | `string` / `null` | Gefühlte Temperatur in °C                             |
| `precipitation`       | `string` / `null` | Niederschlag in mm                                    |
| `rain`                | `string` / `null` | Regen in mm                                           |
| `snowfall`            | `string` / `null` | Schneefall in mm                                      |
| `wind_speed`          | `string` / `null` | Windgeschwindigkeit in km/h (10m-Höhe)                |
| `wind_direction`      | `integer` / `null`| Windrichtung in Grad (0–360, meteorologisch)          |
| `humidity`            | `integer` / `null`| Relative Luftfeuchtigkeit in %                        |
| `sunshine_duration`   | `string` / `null` | Sonnenscheindauer in Sekunden pro Stunde              |
| `weather_code`        | `integer` / `null`| WMO Wettercode (siehe Abschnitt 13)                   |
| `is_day`              | `boolean` / `null`| `true` = Tageslicht, `false` = Nacht                  |
| `weather_description` | `string`          | Computed: Deutsch-Text zum WMO-Code                   |
| `weather_icon`        | `string`          | Computed: Emoji zum WMO-Code                          |

**Hinweis:** Die Bodenfeuchte- und Bodentemperaturfelder (`soil_*`) sind in der DB vorhanden, werden aber vom `WeatherHourlySchema` nicht serialisiert. Sie sind ausschließlich über die Chart-Endpoints (`/charts/hourly-plot`) visuell verfügbar.

**Fehler-Responses:**

| Status | Beschreibung                    | Beispiel `detail`                          |
|--------|---------------------------------|--------------------------------------------|
| `404`  | Keine stündlichen Daten         | `"Keine stündlichen Daten für 'Berlin'."` |

---

## 8. Alerts (System-generiert)

System-Alerts werden vom Airflow-DAG generiert, nicht von Endbenutzern. Der `fetch-now`-Endpoint deaktiviert alle aktiven Alerts einer Stadt beim Datenimport.

### `GET /alerts`

Gibt aktive oder alle Wetterwarnungen einer Stadt zurück.

**Authentifizierung:** Nicht erforderlich

**Query-Parameter:**

| Parameter     | Typ       | Pflicht | Standard          | Beschreibung                                       |
|---------------|-----------|---------|-------------------|----------------------------------------------------|
| `city`        | `string`  | Nein    | `DEFAULT_CITY` (env) | Stadtname                                      |
| `active_only` | `boolean` | Nein    | `true`            | Wenn `true`: nur aktive Alerts; `false`: alle      |
| `severity`    | `string`  | Nein    | `null`            | Filter nach Schweregrad: `"danger"`, `"warning"`, etc. |

**Beispiel Requests:**

```
GET /alerts?city=Freiburg
GET /alerts?city=Freiburg&active_only=false&severity=danger
```

**Response `200 OK`** – Array von `WeatherAlertSchema`:

```json
[
  {
    "id": 5,
    "city": "Freiburg",
    "alert_name": "Hitzewarnung",
    "severity": "danger",
    "message": "Maximale Temperatur überschreitet 35°C",
    "condition_met": {
      "parameter": "temperature_max",
      "threshold": 35.0,
      "actual": 37.2
    },
    "forecast_date": "2026-07-15",
    "is_active": true,
    "created_at": "2026-07-14T18:00:00+00:00"
  }
]
```

**WeatherAlertSchema – Felder:**

| Feld            | Typ               | Beschreibung                                                   |
|-----------------|-------------------|----------------------------------------------------------------|
| `id`            | `integer`         | Datenbankid                                                    |
| `city`          | `string`          | Stadtname                                                      |
| `alert_name`    | `string`          | Name des Alerts (z.B. `"Hitzewarnung"`)                        |
| `severity`      | `string`          | Schweregrad: `"danger"`, `"warning"` o.ä.                      |
| `message`       | `string`          | Menschenlesbare Warnmeldung                                    |
| `condition_met` | `object` / `null` | JSONB-Objekt mit den ausgelösten Bedingungsdetails             |
| `forecast_date` | `string` / `null` | Prognosedatum für das der Alert gilt                           |
| `is_active`     | `boolean`         | `true` = aktuell aktiv                                         |
| `created_at`    | `string` / `null` | Erstellungszeitpunkt                                           |

**Fehler-Responses:** Keine (leere Liste wenn keine Alerts vorhanden)

---

### `GET /alerts/history`

Gibt den vollständigen Verlauf aller Wetterwarnungen einer Stadt zurück (aktive und inaktive), sortiert nach Erstellungsdatum absteigend.

**Authentifizierung:** Nicht erforderlich

**Query-Parameter:**

| Parameter | Typ       | Pflicht | Standard          | Beschreibung                               |
|-----------|-----------|---------|-------------------|--------------------------------------------|
| `city`    | `string`  | Nein    | `DEFAULT_CITY` (env) | Stadtname                              |
| `limit`   | `integer` | Nein    | `50`              | Maximale Anzahl Einträge. Min: `1`, Max: `200` |

**Response `200 OK`:** Array von `WeatherAlertSchema` (identische Struktur wie `/alerts`)

**Fehler-Responses:** Keine (leere Liste wenn keine Alerts vorhanden)

---

## 9. Statistik-Daten (Chart-Data)

Diese Endpoints liefern aufbereitete JSON-Daten für clientseitige Chart-Bibliotheken (z.B. Chart.js). Im Unterschied zu `/charts/*` wird kein PNG gerendert.

### `GET /stats/temperature`

Tägliche Temperatur-, Niederschlags- und Winddaten für die nächsten 4 Tage.

**Authentifizierung:** Nicht erforderlich

**Query-Parameter:**

| Parameter | Typ      | Pflicht | Standard          | Beschreibung |
|-----------|----------|---------|-------------------|--------------|
| `city`    | `string` | Nein    | `DEFAULT_CITY` (env) | Stadtname |

**Response `200 OK`:**

```json
{
  "city": "Freiburg",
  "labels": ["2026-03-16", "2026-03-17", "2026-03-18", "2026-03-19"],
  "datasets": {
    "temperature_max": [14.5, 16.2, 13.8, 11.0],
    "temperature_min": [6.2, 7.1, 5.5, 4.3],
    "precipitation": [0.0, 2.4, 5.1, 0.8],
    "wind_speed": [18.3, 12.0, 22.5, 15.7]
  }
}
```

| Feld                        | Typ              | Beschreibung                            |
|-----------------------------|------------------|-----------------------------------------|
| `city`                      | `string`         | Stadtname                               |
| `labels`                    | `string[]`       | Datumslabels `YYYY-MM-DD`               |
| `datasets.temperature_max`  | `number[]`/`null`| Tagesmaxima in °C                       |
| `datasets.temperature_min`  | `number[]`/`null`| Tagesminia in °C                        |
| `datasets.precipitation`    | `number[]`       | Niederschlag in mm (0 wenn kein Wert)   |
| `datasets.wind_speed`       | `number[]`/`null`| Maximale Windgeschwindigkeit in km/h    |

**Fehler-Responses:**

| Status | Beschreibung             | Beispiel `detail`                 |
|--------|--------------------------|-----------------------------------|
| `404`  | Keine Daten für die Stadt | `"Keine Daten für 'Berlin'."` |

---

### `GET /stats/hourly-temp`

Stündliche Temperatur-, Gefühlte-Temperatur- und Niederschlagsdaten.

**Authentifizierung:** Nicht erforderlich

**Query-Parameter:**

| Parameter | Typ       | Pflicht | Standard          | Beschreibung                             |
|-----------|-----------|---------|-------------------|------------------------------------------|
| `city`    | `string`  | Nein    | `DEFAULT_CITY` (env) | Stadtname                            |
| `hours`   | `integer` | Nein    | `48`              | Anzahl Stunden. Min: `1`, Max: `168`     |

**Response `200 OK`:**

```json
{
  "city": "Freiburg",
  "labels": ["16.03 11:00", "16.03 12:00", "16.03 13:00"],
  "temperature": [12.3, 13.1, 13.8],
  "feels_like": [9.8, 10.5, 11.2],
  "precipitation": [0.0, 0.1, 0.0]
}
```

| Feld            | Typ              | Beschreibung                                     |
|-----------------|------------------|--------------------------------------------------|
| `city`          | `string`         | Stadtname                                        |
| `labels`        | `string[]`       | Zeitlabels im Format `DD.MM HH:MM` (UTC)         |
| `temperature`   | `number[]`/`null`| Stundenwerte Temperatur in °C                    |
| `feels_like`    | `number[]`/`null`| Stundenwerte gefühlte Temperatur in °C           |
| `precipitation` | `number[]`       | Stundenwerte Niederschlag in mm (0 wenn kein Wert)|

**Fehler-Responses:** Keine (leere Arrays wenn keine Daten)

---

## 10. Charts (Matplotlib PNG)

Diese Endpoints rendern serverseitig PNG-Diagramme via Matplotlib. Die Antwort ist kein JSON, sondern ein Binär-PNG. Die Charts werden im In-Memory-Cache gespeichert und bei erneutem Aufruf aus dem Cache bedient (`X-Cache: HIT`).

### `GET /charts/hourly-plot`

Rendert ein mehrteiliges Prognosediagramm für den angegebenen Zeitraum mit 8 Panels: Temperatur, Luftfeuchtigkeit, Windgeschwindigkeit, Windrichtung, Niederschlag, Sonnenscheindauer, Bodentemperatur und Bodenfeuchte.

**Authentifizierung:** Nicht erforderlich

**Query-Parameter:**

| Parameter | Typ       | Pflicht | Standard          | Beschreibung                                                                   |
|-----------|-----------|---------|-------------------|--------------------------------------------------------------------------------|
| `city`    | `string`  | Nein    | `DEFAULT_CITY` (env) | Stadtname                                                                  |
| `hours`   | `integer` | Nein    | `96`              | Prognosehorizont in Stunden. Min: `6`, Max: `168`                              |
| `soil_t`  | `string`  | Nein    | `"0,6,18"`        | Kommagetrennte Bodentiefen für Bodentemperatur-Panel. Werte: `0`, `6`, `18`    |
| `soil_m`  | `string`  | Nein    | `"0-1,1-3,3-9"`   | Kommagetrennte Bodentiefen für Bodenfeuchte-Panel. Werte: `0-1`, `1-3`, `3-9` |

**Beispiel Requests:**

```
GET /charts/hourly-plot?city=Freiburg&hours=48
GET /charts/hourly-plot?city=Berlin&hours=120&soil_t=0,6&soil_m=0-1
```

**Response `200 OK`:**

```
Content-Type: image/png
Cache-Control: no-cache, max-age=0
X-Cache: HIT | MISS
```

Body: PNG-Bilddaten (8x8 Zoll, 100 DPI, dunkles Dark-Theme)

**Fehler-Responses:**

| Status | Beschreibung                    | Beispiel `detail`                                    |
|--------|---------------------------------|------------------------------------------------------|
| `404`  | Keine stündlichen Daten         | `"Keine stündlichen Daten für 'Berlin'."` |

---

### `GET /charts/day-detail`

Rendert ein Tagesdetail-Diagramm für einen einzelnen Tag mit 6 Panels: Temperatur (mit Tagesmax/-min-Punkten), Luftfeuchtigkeit, Windgeschwindigkeit, Windrichtung (Pfeile), Niederschlag und Sonnenscheindauer.

**Authentifizierung:** Nicht erforderlich

**Query-Parameter:**

| Parameter | Typ      | Pflicht | Beschreibung                                   |
|-----------|----------|---------|------------------------------------------------|
| `date`    | `string` | **Ja**  | Datum im Format `YYYY-MM-DD`                   |
| `city`    | `string` | Nein    | Stadtname. Standard: `DEFAULT_CITY` (env)      |

**Beispiel Request:**

```
GET /charts/day-detail?date=2026-03-16&city=Freiburg
```

**Response `200 OK`:**

```
Content-Type: image/png
Cache-Control: no-cache, max-age=0
X-Cache: HIT | MISS
```

Body: PNG-Bilddaten (8x6 Zoll, 100 DPI, dunkles Dark-Theme)

**Fehler-Responses:**

| Status | Beschreibung                     | Beispiel `detail`                              |
|--------|----------------------------------|------------------------------------------------|
| `400`  | Ungültiges Datumsformat          | `"Invalid date format, use YYYY-MM-DD."`       |
| `404`  | Keine Stundendaten für diesen Tag | `"Keine Stundendaten für 2026-03-16."` |

---

### `POST /charts/cache-clear`

Leert den In-Memory-Chart-Cache für eine bestimmte Stadt. Alle gecachten Charts (Stunden-Plot und alle Tagesdetail-Charts) dieser Stadt werden gelöscht.

**Authentifizierung:** Nicht erforderlich

**Query-Parameter:**

| Parameter | Typ      | Pflicht | Beschreibung |
|-----------|----------|---------|--------------|
| `city`    | `string` | **Ja**  | Stadtname    |

**Response `200 OK`:**

```json
{
  "status": "ok",
  "city": "Freiburg"
}
```

**Fehler-Responses:** Keine

---

## 11. Warnungen (User-definiert)

Benutzer können eigene, regelbasierte Wetterwarnungen konfigurieren. Im Unterschied zu System-Alerts (Abschnitt 8) werden diese nicht automatisch ausgelöst, sondern dienen als persönliche Konfiguration. Alle Endpoints außer `/warnings/templates` erfordern Authentifizierung.

### `GET /warnings/templates`

Gibt alle vordefinierten Warn-Templates zurück, die als Ausgangspunkt für eigene Warnungen dienen können.

**Authentifizierung:** Nicht erforderlich

**Query-Parameter:** Keine

**Response `200 OK`:**

```json
[
  {
    "id": 1,
    "name": "Hitzewarnung",
    "description": "Warnt bei extremer Hitze über 35°C",
    "conditions": [
      {
        "parameter": "temperature_max",
        "comparator": ">=",
        "value": 35.0,
        "label": "Temperatur >= 35°C"
      }
    ]
  }
]
```

| Feld          | Typ              | Beschreibung                                |
|---------------|------------------|---------------------------------------------|
| `id`          | `integer`        | Datenbankid des Templates                   |
| `name`        | `string`         | Name des Templates                          |
| `description` | `string` / `null`| Beschreibung                                |
| `conditions`  | `array`          | Array von `ConditionRule`-Objekten          |

**ConditionRule-Objekt:**

| Feld         | Typ               | Beschreibung                                                          |
|--------------|-------------------|-----------------------------------------------------------------------|
| `parameter`  | `string`          | Wetterparameter, z.B. `"temperature_max"`, `"wind_speed_max"`, `"precipitation_sum"` |
| `comparator` | `string`          | Vergleichsoperator: `">"`, `"<"`, `">="`, `"<="`, `"=="`             |
| `value`      | `float`           | Schwellenwert                                                          |
| `label`      | `string` / `null` | Optionaler lesbarer Text zur Bedingung                                |

**Fehler-Responses:** Keine (leere Liste wenn keine Templates)

---

### `GET /warnings/`

Listet alle eigenen Warnungen des authentifizierten Benutzers auf, sortiert nach Erstellungsdatum absteigend.

**Authentifizierung:** **Erforderlich** (Bearer Token)

**Query-Parameter:** Keine

**Response `200 OK`:**

```json
[
  {
    "id": 3,
    "station_id": 42,
    "city": "Freiburg",
    "name": "Meine Sturmwarnung",
    "conditions": [
      {
        "parameter": "wind_speed_max",
        "comparator": ">=",
        "value": 60.0,
        "label": "Sturmstärke"
      }
    ],
    "validity": {
      "type": "date_range",
      "date_from": "2026-10-01",
      "date_to": "2026-03-31",
      "weekdays": null,
      "months": null
    },
    "active": true,
    "created_at": "2026-03-16T09:00:00+00:00",
    "updated_at": "2026-03-16T09:00:00+00:00"
  }
]
```

**WarningOut-Felder:**

| Feld         | Typ               | Beschreibung                                      |
|--------------|-------------------|---------------------------------------------------|
| `id`         | `integer`         | Datenbankid der Warnung                           |
| `station_id` | `integer` / `null`| Verknüpfte Station (optional)                     |
| `city`       | `string`          | Stadtname                                         |
| `name`       | `string`          | Benutzerdefinierter Name der Warnung              |
| `conditions` | `array`           | Regeln als JSONB (identisch zu `ConditionRule[]`) |
| `validity`   | `object`          | Gültigkeitskonfiguration als JSONB (`ValiditySpec`) |
| `active`     | `boolean`         | Ob die Warnung aktiv ist                          |
| `created_at` | `string` / `null` | Erstellungszeitpunkt                              |
| `updated_at` | `string` / `null` | Letzter Änderungszeitpunkt                        |

**ValiditySpec-Objekt:**

| Feld        | Typ                    | Beschreibung                                              |
|-------------|------------------------|-----------------------------------------------------------|
| `type`      | `string`               | `"date_range"`, `"weekdays"` oder `"months"`             |
| `date_from` | `string` / `null`      | Startdatum für `date_range` (ISO-Date `YYYY-MM-DD`)       |
| `date_to`   | `string` / `null`      | Enddatum für `date_range` (ISO-Date `YYYY-MM-DD`)         |
| `weekdays`  | `integer[]` / `null`   | Wochentage für `weekdays`: `0`=Mo, `1`=Di, ..., `6`=So   |
| `months`    | `integer[]` / `null`   | Monate für `months`: `1`=Jan, ..., `12`=Dez              |

**Fehler-Responses:**

| Status | Beschreibung           | Beispiel `detail`               |
|--------|------------------------|---------------------------------|
| `401`  | Nicht authentifiziert  | `"Invalid or expired token"`    |

---

### `POST /warnings/`

Erstellt eine neue benutzerdefinierte Warnung.

**Authentifizierung:** **Erforderlich** (Bearer Token)

**Request Body (JSON) – `WarningCreate`:**

| Feld         | Typ               | Pflicht | Beschreibung                                        |
|--------------|-------------------|---------|-----------------------------------------------------|
| `station_id` | `integer`         | Nein    | ID einer Station aus `/stations/search`             |
| `city`       | `string`          | **Ja**  | Stadtname                                           |
| `name`       | `string`          | **Ja**  | Name der Warnung                                    |
| `conditions` | `ConditionRule[]` | **Ja**  | Mindestens eine Bedingungsregel                     |
| `validity`   | `ValiditySpec`    | **Ja**  | Gültigkeitsdefinition                               |

**Beispiel Request:**

```json
{
  "station_id": 42,
  "city": "Freiburg",
  "name": "Meine Sturmwarnung",
  "conditions": [
    {
      "parameter": "wind_speed_max",
      "comparator": ">=",
      "value": 60.0,
      "label": "Sturmstärke"
    }
  ],
  "validity": {
    "type": "months",
    "months": [10, 11, 12, 1, 2, 3]
  }
}
```

**Response `201 Created`:** `WarningOut`-Objekt (identische Struktur wie bei `GET /warnings/`)

**Fehler-Responses:**

| Status | Beschreibung           | Beispiel `detail`               |
|--------|------------------------|---------------------------------|
| `401`  | Nicht authentifiziert  | `"Invalid or expired token"`    |
| `422`  | Ungültiger Request-Body | Pydantic-Validierungsfehler    |

---

### `GET /warnings/{warning_id}`

Gibt eine einzelne Warnung des authentifizierten Benutzers zurück.

**Authentifizierung:** **Erforderlich** (Bearer Token)

**Pfad-Parameter:**

| Parameter    | Typ       | Beschreibung     |
|--------------|-----------|------------------|
| `warning_id` | `integer` | ID der Warnung   |

**Response `200 OK`:** `WarningOut`-Objekt

**Fehler-Responses:**

| Status | Beschreibung                                           | Beispiel `detail`               |
|--------|--------------------------------------------------------|---------------------------------|
| `401`  | Nicht authentifiziert                                  | `"Invalid or expired token"`    |
| `404`  | Warnung nicht gefunden oder gehört anderem Benutzer    | `"Warning not found"`           |

---

### `PUT /warnings/{warning_id}`

Aktualisiert eine bestehende Warnung vollständig (alle Felder werden ersetzt).

**Authentifizierung:** **Erforderlich** (Bearer Token)

**Pfad-Parameter:**

| Parameter    | Typ       | Beschreibung     |
|--------------|-----------|------------------|
| `warning_id` | `integer` | ID der Warnung   |

**Request Body (JSON):** Identisch mit `POST /warnings/` (`WarningCreate`)

**Response `200 OK`:** Aktualisiertes `WarningOut`-Objekt

**Fehler-Responses:**

| Status | Beschreibung                                           | Beispiel `detail`               |
|--------|--------------------------------------------------------|---------------------------------|
| `401`  | Nicht authentifiziert                                  | `"Invalid or expired token"`    |
| `404`  | Warnung nicht gefunden oder gehört anderem Benutzer    | `"Warning not found"`           |
| `422`  | Ungültiger Request-Body                                | Pydantic-Validierungsfehler     |

---

### `DELETE /warnings/{warning_id}`

Löscht eine Warnung dauerhaft.

**Authentifizierung:** **Erforderlich** (Bearer Token)

**Pfad-Parameter:**

| Parameter    | Typ       | Beschreibung     |
|--------------|-----------|------------------|
| `warning_id` | `integer` | ID der Warnung   |

**Response `204 No Content`:** Leerer Response-Body

**Fehler-Responses:**

| Status | Beschreibung                                           | Beispiel `detail`               |
|--------|--------------------------------------------------------|---------------------------------|
| `401`  | Nicht authentifiziert                                  | `"Invalid or expired token"`    |
| `404`  | Warnung nicht gefunden oder gehört anderem Benutzer    | `"Warning not found"`           |

---

## 12. Fehler-Referenz

Alle Fehler-Responses folgen dem FastAPI-Standard-Format:

```json
{
  "detail": "Fehlermeldung als String"
}
```

Pydantic-Validierungsfehler (HTTP 422) haben eine strukturiertere Form:

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "city"],
      "msg": "Field required",
      "input": {}
    }
  ]
}
```

**HTTP-Statuscodes im Überblick:**

| Code | Name                    | Typischer Auslöser                                              |
|------|-------------------------|-----------------------------------------------------------------|
| `200` | OK                     | Erfolgreiche Anfrage                                            |
| `201` | Created                | Ressource erfolgreich angelegt (Register, Warning POST)         |
| `204` | No Content             | Ressource erfolgreich gelöscht (Warning DELETE)                 |
| `400` | Bad Request            | Doppelte E-Mail/Username, logisch ungültige Eingabe             |
| `401` | Unauthorized           | Fehlender, ungültiger oder abgelaufener JWT-Token; falsche Anmeldedaten |
| `404` | Not Found              | Keine Daten für die angefragte Stadt / Warnung nicht gefunden   |
| `422` | Unprocessable Entity   | Pydantic-Validierungsfehler (fehlende Pflichtfelder, falscher Typ) |
| `500` | Internal Server Error  | Unerwarteter Serverfehler                                       |
| `502` | Bad Gateway            | Open-Meteo API gibt HTTP-Fehler zurück                          |
| `504` | Gateway Timeout        | Open-Meteo API antwortet nicht innerhalb von 30 Sekunden        |

---

## 13. WMO Wetter-Codes

Die API verwendet WMO-Wettercodes (World Meteorological Organization) in allen Forecast-Feldern. Die Codes werden in `weather_description` (Deutsch) und `weather_icon` (Emoji) übersetzt.

| Code | Beschreibung              | Icon |
|------|---------------------------|------|
| 0    | Klarer Himmel             | ☀️  |
| 1    | Überwiegend klar          | 🌤️  |
| 2    | Teilweise bewölkt         | ⛅  |
| 3    | Bedeckt                   | ☁️  |
| 45   | Nebel                     | 🌫️  |
| 48   | Reifnebel                 | 🌫️  |
| 51   | Leichter Nieselregen      | 🌦️  |
| 53   | Mäßiger Nieselregen       | 🌦️  |
| 55   | Starker Nieselregen       | 🌧️  |
| 61   | Leichter Regen            | 🌧️  |
| 63   | Mäßiger Regen             | 🌧️  |
| 65   | Starker Regen             | 🌧️  |
| 71   | Leichter Schneefall       | ❄️  |
| 73   | Mäßiger Schneefall        | ❄️  |
| 75   | Starker Schneefall        | ❄️  |
| 77   | Schneekörner              | 🌨️  |
| 80   | Leichte Regenschauer      | 🌦️  |
| 81   | Mäßige Regenschauer       | 🌧️  |
| 82   | Starke Regenschauer       | ⛈️  |
| 85   | Leichte Schneeschauer     | 🌨️  |
| 86   | Starke Schneeschauer      | 🌨️  |
| 95   | Gewitter                  | ⛈️  |
| 96   | Gewitter mit leichtem Hagel | ⛈️ |
| 99   | Gewitter mit starkem Hagel  | ⛈️ |

Unbekannte Codes liefern `"Unbekannt"` als Beschreibung und `🌡️` als Icon.

---

*Dokumentation generiert am 2026-03-16 | Weather ETL API v1.0.0*
