# Session 7 – Technische Erklärungen

**Datum:** 2026-03-19
**Projekt:** Weather ETL – Capstone Project (neue fische)

---

## 1. Airflow Datenfluss

### Die zwei DAGs

| DAG | Schedule | Zweck |
|---|---|---|
| `weather_etl_pipeline` | `@hourly` (stündlich) | Wetterdaten holen und in DB schreiben |
| `check_weather_warnings` | alle 2 Stunden (`0 */2 * * *`) | User-Warnungen prüfen und Emails senden |

**Wichtig:** Airflow triggert die DAGs ausschließlich nach Zeitplan – **nicht** wenn ein User die Website aufruft.

---

### DAG 1: weather_etl_pipeline

```
start → [extract] → [transform] → [load] → end
```

#### EXTRACT (`airflow/tasks/extract.py`)

Ruft die **Open-Meteo API** auf und holt für die konfigurierte Stadt (Default: Freiburg):
- **7 Tage täglich**: Temp min/max, Niederschlag, Wind, UV-Index, Sonnenauf/-untergang
- **168 Stunden** (7×24h): Temperatur, Regen, Wind, Luftfeuchte, Sonnenscheindauer, Bodentemperatur

Das Ergebnis landet als **XCom** unter dem Key `"raw_weather"`.

> **Was ist XCom?** XCom = *Cross-Communication* – Airflow-Mechanismus damit Tasks Daten aneinander weitergeben können, ohne in Dateien oder die DB zu schreiben.

#### TRANSFORM (`airflow/tasks/transform.py`)

Holt `"raw_weather"` aus XCom und:
1. Flacht API-Arrays zu einzelnen Records ab (1 Row pro Tag / pro Stunde)
2. Übersetzt WMO-Wettercodes in deutsche Beschreibungen ("Klarer Himmel", "Starker Regen" …)
3. Wertet **General Alerts** aus (`alerts_config.yaml`, AND-Logik über alle Bedingungen)
4. Schreibt Ergebnis als `"transformed_weather"` zurück in XCom

#### LOAD (`airflow/tasks/load.py`)

Holt `"transformed_weather"` und schreibt **in einer Transaktion** in PostgreSQL:

| Tabelle | Art | Logik |
|---|---|---|
| `weather_raw` | INSERT | Rohes API-JSON als JSONB (Audit/Archiv) |
| `weather_daily` | UPSERT | Konflikt auf (city, date) → Werte überschreiben |
| `weather_hourly` | UPSERT | Konflikt auf (city, time) → Werte überschreiben |
| `weather_alerts` | UPDATE + INSERT | Alte deaktivieren, neue einfügen |

Danach: `POST /charts/cache-clear` ans Backend (Diagramm-Cache leeren).

---

### DAG 2: check_weather_warnings

```
start → [check_warnings] → end
```

Läuft alle 2 Stunden, liest **nur aus der DB** (kein API-Call) und:
1. Lädt alle aktiven User-Warnings (`warnings` Tabelle, `active = TRUE`)
2. Prüft für die nächsten 7 Tage ob Bedingungen in `weather_daily` erfüllt sind
3. Sendet HTML-Email wenn getriggert
4. Verhindert Doppel-Emails via `warning_notifications` Tabelle (Deduplication)

**SMTP:** Lokal via MailHog (Port 1025) – auf dem Server via Brevo.

---

### Zeitlicher Ablauf (Beispiel)

```
12:00  ETL startet → Open-Meteo abrufen → transformieren → DB schreiben
12:xx  ETL fertig, DB hat aktuelle 7-Tage-Prognose
12:00 oder 14:00  Check_Warnings startet → prüft DB → sendet ggf. Emails
```

---

## 2. FastAPI & Endpoints

### Was ist FastAPI?

FastAPI ist ein Python-Webframework. Es macht aus Python-Funktionen **HTTP-Endpoints** – also URLs, die über Browser oder JavaScript aufgerufen werden und Daten (JSON) oder Bilder (PNG) zurückgeben.

```
Browser/JS            →   HTTP Request               →   FastAPI-Funktion   →   Antwort
app.js fetchData()    →   GET /forecast/daily?city=X →   def get_daily()    →   [{...}]
```

### Projektstruktur

```
backend/main.py              ← App-Instanz + Chart-Endpoints + Forecast-Endpoints
backend/routers/
  ├── auth.py                ← /auth/... (Login, Register, JWT)
  ├── stations.py            ← /stations/... (Stationssuche)
  ├── warnings.py            ← /warnings/... (User-Warnungen CRUD)
  └── weather_fetch.py       ← /weather/fetch-now (ETL on-demand)
```

### Alle Endpoints

```
SYSTEM
  GET  /health                        → Backend + DB erreichbar?

FORECAST
  GET  /summary?city=Freiburg         → Aktuelle Temp, Wind, last_updated
  GET  /forecast/daily?city=...       → 7 Tage Tagesprognose (JSON)
  GET  /forecast/hourly?city=...      → 168h Stundenprognose (JSON)

CHARTS (PNG-Bilder)
  GET  /charts/hourly-plot?hours=96   → Haupt-Dashboard-Chart (6 Panels)
  GET  /charts/day-detail?date=...    → Tages-Detailchart (Modal)
  POST /charts/cache-clear            → Cache leeren (Airflow ruft das auf)

ALERTS
  GET  /alerts?city=...               → Aktive General-Alerts
  GET  /alerts/history?city=...       → Alert-Verlauf

STATS
  GET  /stats/temperature?city=...    → Temp-Statistik (min/max/avg)
  GET  /stats/hourly-temp?city=...    → Stündliche Temp-Kurve

AUTH
  POST /auth/register                 → Registrierung → JWT
  POST /auth/login                    → Login → JWT
  GET  /auth/me                       → Wer bin ich? (JWT prüfen)

STATIONS
  GET  /stations/search?q=Berlin      → Stationssuche via Geocoding

WARNINGS (CRUD, erfordern JWT)
  GET    /warnings/templates          → Vorlagen für Warnungen
  GET    /warnings/                   → Alle meine Warnungen
  POST   /warnings/                   → Neue Warnung anlegen
  GET    /warnings/{id}               → Eine Warnung lesen
  PUT    /warnings/{id}               → Warnung bearbeiten
  DELETE /warnings/{id}               → Warnung löschen
  GET    /warnings/triggered          → Aktuell getriggerte Warnungen

ETL ON-DEMAND
  POST /weather/fetch-now?city=...    → ETL manuell starten (z.B. neue Stadt)
```

### Wie eine FastAPI-Funktion aussieht

```python
@app.get("/forecast/daily", response_model=list[WeatherDailySchema])
def get_daily_forecast(city: str = "Freiburg", db: Session = Depends(get_db)):
    records = db.query(WeatherDaily).filter(WeatherDaily.city == city).all()
    return records
```

- `@app.get(...)` → Decorator macht die Funktion zum HTTP GET Endpoint
- `response_model=...` → FastAPI validiert die Antwort gegen das Pydantic-Schema
- `city: str = "Freiburg"` → Query-Parameter mit Default (aus URL: `?city=Berlin`)
- `db: Session = Depends(get_db)` → **Dependency Injection**: FastAPI gibt automatisch eine DB-Session

### Pydantic

```
SQLAlchemy Model (ORM/DB)   →   Pydantic Schema   →   JSON-Antwort
WeatherDaily (DB-Zeile)     →   WeatherDailySchema →   {"city": "Freiburg", ...}
```

Pydantic validiert Typen und serialisiert Python-Objekte zu JSON.

### Interaktive Dokumentation

FastAPI generiert automatisch eine interaktive API-Doku:
`http://localhost:8000/docs` – alle Endpoints direkt im Browser ausprobierbar.

---

## 3. JSONB – Was ist das und warum hier sinnvoll?

### JSON vs. JSONB

- **JSON** = Textformat für strukturierte Daten
- **JSONB** = PostgreSQL's *Binary JSON* – JSON das als **strukturiertes Binärformat** gespeichert wird

### Warum JSONB statt normalen Spalten?

Eine User-Warning hat `conditions` (1 bis N Bedingungen) und `validity` (3 verschiedene Strukturen: `date_range`, `weekdays`, `months`).

**Option A – Normale Spalten (schlecht):**
```sql
condition_1_param VARCHAR, condition_1_op VARCHAR, condition_1_value FLOAT,
condition_2_param VARCHAR, condition_2_op VARCHAR, condition_2_value FLOAT,
-- ...bis zu N mal, plus drei Varianten für Validity
```
→ Starres Schema, viele NULL-Felder, schwer erweiterbar

**Option B – JSONB (verwendet):**
```sql
conditions JSONB  -- z.B. [{"parameter": "temperature_max", "comparator": ">", "value": 35}]
validity   JSONB  -- z.B. {"type": "weekdays", "weekdays": [0,1,2,3,4]}
```
→ Flexibel, erweiterbar ohne DB-Migration, sauber

### Vorteile JSONB vs. JSON-Text

| | JSON (Text) | JSONB (Binary) |
|---|---|---|
| Suche | Nicht möglich | `WHERE conditions @> '[...]'` |
| Indizierbar | Nein | Ja (GIN-Index) |
| Parse-Geschwindigkeit | Langsam (bei jedem Read) | Schnell (bereits geparst) |
| Validierung | Keine | PostgreSQL prüft die Struktur |

### Wo JSONB im Projekt verwendet wird

| Tabelle | Spalte | Inhalt |
|---|---|---|
| `weather_raw` | `raw_json` | Kompletter Open-Meteo API Response (Archiv) |
| `weather_alerts` | `condition_met` | Welche Werte haben den Alert getriggert |
| `warnings` | `conditions` | Alle Bedingungen der User-Warning |
| `warnings` | `validity` | Zeitraum/Wochentage/Monate der Warning |

---

## 4. Trigger-Mechanismus der Weather Warnings

```
User legt Warning an (Frontend → POST /warnings/)
         ↓
Warning in DB: active=True, conditions=[...], validity={...}
         ↓
Alle 2 Stunden: check_weather_warnings DAG läuft
         ↓
Für jede aktive Warning × nächste 7 Tage:
  1. Temporal valid? (Datum/Wochentag/Monat prüfen)
  2. Notification bereits gesendet? (warning_notifications Tabelle)
  3. Forecast-Daten aus weather_daily holen
  4. Alle Bedingungen (AND) prüfen
         ↓ wenn alle True:
Email senden + Eintrag in warning_notifications (Deduplizierung)
```

**Validity-Typen:**

```python
{"type": "date_range", "date_from": "2025-06-01", "date_to": "2025-09-30"}
{"type": "weekdays", "weekdays": [0, 1, 2, 3, 4]}   # 0=Montag, 6=Sonntag
{"type": "months", "months": [6, 7, 8]}              # Juni, Juli, August
```

---

## 5. Brevo vs. MailHog

| | **MailHog** | **Brevo** |
|---|---|---|
| Was | Lokales Fake-SMTP-Tool | Echter Email-Service (Cloud) |
| Wozu | Development & Testing | Produktion auf dem Server |
| Emails werden gesendet | Nein – abgefangen, im UI angezeigt | Ja – landen wirklich im Postfach |
| Konfiguration | `SMTP_HOST=mailhog`, Port 1025, kein Auth | `smtp-relay.brevo.com`, Port 587, API-Key |
| URL | `localhost:8025` | brevo.com |

**Lokal:** Docker-Compose startet MailHog. Emails landen unter `localhost:8025` – sie gehen nicht wirklich raus.

**Auf dem Server:** Brevo-SMTP-Zugangsdaten in den Umgebungsvariablen → echte Emails.

---

## 6. Architektur-Fehler Session 7 – Befunde und Fixes

### Fehler 1: Neue Stationen laden keine Daten (Berlin-Bug)

**Problem:** `POST /weather/fetch-now` erforderte JWT-Authentifizierung. Nicht eingeloggte User wählen Berlin aus → kein Token → `fetchWeatherNow()` bricht still ab → "No data – run ETL job!".

**Fix:**
- Backend (`backend/routers/weather_fetch.py`): `_current_user = Depends(get_current_user)` entfernt
- Frontend (`frontend/js/app.js`): Token-Check + Auth-Header in `fetchWeatherNow()` entfernt

**Warum kein Sicherheitsproblem:** Der Endpoint ruft nur die öffentliche Open-Meteo API ab – kein schützenswerter Inhalt.

---

### Fehler 2: Warning-Check prüft veraltete Daten für Nicht-Freiburg-Stationen

**Problem:** `check_weather_warnings` DAG läuft alle 2h und prüft User-Warnungen gegen `weather_daily`. Aber `weather_daily` für Berlin/Hamburg/etc. enthält nur Daten vom letzten manuellen Dashboard-Aufruf – ggf. tagelang veraltet. Resultat: Warnungen für Nicht-Freiburg-Stationen triggern nie oder mit falschen Daten.

**Fix:** `_refresh_stale_cities()` in `check_warnings.py` eingefügt – läuft **vor** dem Prüf-Loop:
1. Alle Städte mit aktiven User-Warnungen aus DB holen
2. Für jede Stadt `weather_daily.created_at` prüfen (älter als 2h = veraltet)
3. Koordinaten aus `weather_raw` holen → Open-Meteo abrufen → UPSERT in `weather_daily` + `weather_hourly`

---

### Fehler 3: General Alerts (alerts_config.yaml) nur für Freiburg

**Problem:** General Alerts (`alerts_config.yaml`: Frost, Sturm, Hitze, …) wurden nur im Airflow ETL-Transform berechnet – und der ETL läuft nur für Freiburg. Für Berlin/Hamburg etc. war `GET /alerts?city=Berlin` immer leer.

**Fix:** `/alerts` Endpoint in `backend/main.py` vollständig auf **dynamische Berechnung** umgestellt:
- Liest `alerts_config.yaml` direkt im Endpoint
- Prüft Bedingungen gegen `weather_daily` für die angefragte Stadt
- Funktioniert jetzt für jede Station korrekt

**Nebeneffekt:** `weather_alerts` Tabelle in der DB ist jetzt verwaist (wird noch vom Airflow befüllt aber nicht mehr gelesen). → Cleanup-Aufgabe für später.

---

## 7. Berlin-Bug – technische Details

### Was passiert beim Aufrufen einer neuen Station

```
1. Dashboard öffnet mit ?city=Berlin&lat=...&lon=...
2. init() in app.js läuft:
   GET /forecast/daily?city=Berlin → 404 (keine Daten für Berlin)
   → needsFetch = true
3. fetchWeatherNow() prüft: kein JWT-Token im localStorage?
   → return false  ← STILLER FEHLSCHLAG
4. init() merkt es nicht (kein throw, kein catch)
5. loadForecast() läuft → immer noch keine Berlin-Daten
   → "No data – run ETL job!" wird angezeigt
```

### Ursache

`POST /weather/fetch-now` erfordert Authentifizierung. Der Endpoint-Docstring selbst sagt: *"The user object is not used in the function body; the dependency is present solely to enforce authentication."* – das User-Objekt wird also gar nicht genutzt.

Nicht-eingeloggte User können keine neuen Stationen laden.

### Quick Fix (geplant)

- **Backend** (`backend/routers/weather_fetch.py`): Auth-Dependency `_current_user = Depends(get_current_user)` entfernen
- **Frontend** (`frontend/js/app.js`): Token-Check in `fetchWeatherNow()` entfernen

Die Daten kommen von der öffentlichen Open-Meteo API – kein sicherheitsrelevanter Grund für Auth auf diesem Endpoint.

---

## 7. SYNC-Anzeige

Die SYNC-Anzeige oben im Dashboard zeigt den Zeitstempel des letzten erfolgreichen ETL-Runs:

```
"SYNC 14:32"  → letztes ETL-Update war um 14:32 Uhr
"NO SYNC"     → kein last_updated vorhanden
```

### Datenfluss

```
Airflow ETL fertig
  → load.py schreibt in DB (weather_daily.created_at = NOW())
  → POST /charts/cache-clear (Diagramm-Cache leeren)

Dashboard lädt /summary
  → Backend liest MAX(created_at) aus DB → gibt last_updated zurück
  → Frontend zeigt "SYNC 14:32"
```

### Staleness-Check

Wenn `last_updated` älter als **6 Stunden** ist, triggert das Frontend automatisch ein `fetch-now`:

```javascript
// app.js ~Zeile 445
if (!lu || (Date.now() - lu.getTime()) > 6 * 3600 * 1000) {
    needsFetch = true;
}
```

Das ist die automatische Datenaktualisierung außerhalb des Airflow-Zeitplans – z.B. wenn der User die Seite nach langer Zeit öffnet.
