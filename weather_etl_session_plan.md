# Weather ETL – Projektplan & Session-Übersicht

**Deadline:** 20. März  
**Stack:** Airflow · PostgreSQL · FastAPI · Nginx · Docker

---

## Gesamtarchitektur

```
Landing Page (Stationssuche)
        ↓
    Dashboard (Wettervorhersage der gewählten Station)
        ↓
    User Login / Registrierung (JWT Auth)
        ↓
    Warning-Baukasten (visuell, nach Login)
        ↓
    Airflow prüft Wetterdaten vs. aktive Warnings (stündlich)
        ↓
    Mail-Notification bei Treffer
```

---

## Datenbank-Schema (neue Tabellen)

| Tabelle             | Felder                                                                 |
|---------------------|------------------------------------------------------------------------|
| `users`             | id, email, username, hashed_password, created_at                      |
| `warnings`          | id, user_id, station_id, name, conditions (JSON), valid_from, valid_to, active |
| `warning_templates` | id, name, description, conditions (JSON) – vorkonfigurierte Warnings  |

> Keine sensitiven Nutzerdaten außer E-Mail und Benutzername.

---

## Session-Plan

---

### Session 1 – Stationssuche (Frontend + FastAPI)

**Ziel:** Stationssuche auf der Landing Page, Dashboard zeigt Wettervorhersage der gewählten Station.

**Block 1 – FastAPI Endpoint** (~45 min)
- `GET /stations/search?q=` – sucht nach Name, Region oder Koordinaten
- Response: `station_id`, `name`, `region`, `lat`, `lon`
- Neuer Router: `fastapi/routers/stations.py`

**Block 2 – Landing Page** (~45 min)
- Suchfeld prominent auf der Landing Page
- Fetch gegen `/stations/search`
- Ergebnisse als Liste → Klick lädt Dashboard der Station

**Block 3 – Dashboard** (~20 min)
- Wettervorhersage-Daten der gewählten Station anzeigen
- Temperatur, Niederschlag, Wind etc.
- Edge Cases: leere Suche, keine Treffer

---

### Session 2 – User Login & JWT Auth

**Ziel:** Registrierung, Login, geschützte Routen.

**Endpoints**
- `POST /auth/register` – Email + Username + Passwort
- `POST /auth/login` – gibt JWT Token zurück
- JWT Middleware für geschützte Routen

**Datenbank**
- Tabelle `users` anlegen
- Passwort-Hashing mit `bcrypt`

**Frontend**
- Login-Seite mit Standard-Formular
- JWT Token im LocalStorage speichern
- Weiterleitung zum Warning-Baukasten nach Login

---

### Session 3 – Warning-Baukasten (visueller UI)

**Ziel:** User kann eigene Wetter-Warnings konfigurieren.

Weather Alerts sollen für jeden user einfach anzulegen sein dafür muss er eine bedingung mit einem wetter-parameter verknüpfen, einen ort und einen Zeitraum (intervall oder sich wiedeholendes Interval) angeben.

**UI-Aufbau (3-spaltig)**

| Links | Mitte | Rechts |
|---|---|---|
| Station / Ort / Gebiet wählen (Suchfeld oder Dropdown) | Wetter-Parameter wählen (Niederschlag, Temperatur, Wind, …) + Bedingung definieren (z.B. Temperatur > 32) + AND / AND NOT Verknüpfung | Zeitliche Gültigkeit (von / bis) |
Die zeitlich gültigkiet soll erst mal eine Art Kalender veranschaulicht sein.
Es soll die möglichkeit geben, die zeitlich gültigkiet auch auf Wochentage ( beispiel Warining: schönes wochenende: Samstag und Sonntag über 20 grad und kein Regen) oder auf Monate zu beschränken (Bsp. Schneefall im Januar und Februar über 20 cm) oder auf ein klassisches Start und End-Datum (Bsp. 12-03-2026 bis 30-04-2027) festzulegen.
Beim Abspeichern soll noch nach einem namen für die weather warning gefragt werden und die alters für den user gespeichert werden und im user panel angezeigt werden.
Ein click im user Panel auf die warnings soll wieder die Konfiguration ui öffen mit den gespeicherten parametern der warning.Es soll die möglichkeit geben waring auch wieder zu löschen.

**Vorkonfigurierte Warnings (Templates)**
Beispiele für die Bedigungen der Wetter-Parameter in der mitte der ui

- Hitzwarnung (Temperatur > 32°C)
- Frostwarnung (Temperatur < 0°C)
- Starkregen (Niederschlag > 20mm/h)
- Sturmwarnung (Windgeschwindigkeit > 60 km/h)
- Schneefallwarnung ( Schneefall > 10 cm)


**FastAPI Endpoints**
- `GET /warnings/templates` – vorkonfigurierte Warnings
- `POST /warnings/` – neue Warning speichern
- `GET /warnings/` – alle Warnings des Users
- `DELETE /warnings/{id}` – Warning löschen

---

### Session 4 – Airflow Warning-Check DAG + Mail

**Ziel:** Automatische Prüfung und Mail-Benachrichtigung.
eine Airflow task soll einmal alle 1 oder 2 stunden die selben Daten abfragen wie die Wetterdiagramme auf dem dashboard und die Bedingungen prüfen.



**Neuer Airflow DAG:** `check_weather_warnings`
- Läuft stündlich oder zwei stündlich
- Holt aktuelle Wetterdaten pro Station
- Prüft gegen alle aktiven User-Warnings
- Triggert Mail wenn Bedingung erfüllt


**Meine Bedenken**
- Es könnten zu viel API-Calls auf der open meteo seite generiert werden.
- Es könnten sich unmengen an Wetterdaten in der Datenbank ansammeln
- Es könnte sehr lange dauert bis alle Bedingungen überprüft werden.
- Es kommt wahrscheinlich sehr auf die menge der user an, sagen wir jeder User legt 3 warnings im schnitt an oder wir limitieren es auf 10 Warnings pro User. Wie viele user könnte unsere Infrastrucktur dann verkraften? nur so als grobe Schätzung!

**Mail-Setup**
- SMTP via Python (`smtplib`) oder Mailgun
- Template: Station, Warning-Name, aktueller Wert, Schwellwert

---

### Session 5 – Integration & Feinschliff

**Ziel:** Alles zusammenbauen, testen, polish.

- Navigation: Landing Page → Dashboard → Login → Baukasten
- Nginx Routing prüfen
- End-to-End Test: Warning konfigurieren → Airflow triggern → Mail prüfen
- sicherheits checken up
- README aktualisieren

---

## Dateistruktur (Ziel)

```
weather_etl/
├── docker-compose.yml
├── nginx/
│   └── nginx.conf
├── airflow/
│   └── dags/
│       ├── weather_etl_dag.py        (existiert)
│       └── check_weather_warnings.py (neu – Session 4)
├── fastapi/
│   ├── main.py
│   ├── database.py
│   └── routers/
│       ├── stations.py   (neu – Session 1)
│       ├── auth.py       (neu – Session 2)
│       └── warnings.py   (neu – Session 3)
└── frontend/
    ├── index.html        (Landing Page mit Stationssuche)
    ├── dashboard.html
    ├── login.html        (neu – Session 2)
    └── warnings.html     (Baukasten – neu – Session 3)
```

---

*Erstellt am 11.03.2026 – Weather ETL Projektplanung*

## Session 6
0. securtiy  agent fixess
1. theme wiederherstellung des altes theme 
2. Focus auf ETL Pipeline und Nextwerk Aufbau - Aufbau der Präsentation
3. unter Aktive Warnungen scheint ein Bug zu sein. Ich möchte das dort alle aktiven Wetterwarnung des users auftauchen mit datum, name überschrittenen wert und vorhersage wert.
Darunter in der rechten spalte könntenn auch noch die gespeicherten und nicht aktiven warnungen des users angezeigt werden. auch die generischen Wetter warnungen sollten dort aufgelistet sein. ein click auf die jeweilige warnung soll den editor mit den setting der warnung aufrufen.
4. in email notification bitt "gemmessener Wert" in vorhergesagter Wert ändern.

Aufbau der Präsentation:
titelbaltt mit name: marvin lorff und Bezug zu Capstone Project des Daten engineering kurs von neufische. der content soll auf englisch sein.
Der inhalt soll das Project vorstellen ohne den Code zu zeigen. beispiel und Screenshots sollen enthalten sein. der Focus Soll auf dem Data Enginering teil liegen die postgres shemas erklären und die einzelnen schirtten der datenverarbeitung extract transform load behinhalten.Es soll ausserdem die netztwerkstrucktur erklärt werden mit einem diagramm das den aufbau mit dem linux server zeigt das kann cih aber noch nachreeiechen wenn ich den calude code auf dem server laufen lasse er wird alles dann zum aufbau wissen.
Die Präsentation ist auf meine bidschirm manchmal nur halb zu sehen weil der untere bereich verschwindet, im oberen teil ist vielleciht noch etwas platz den wir kürzen können oder? oder  man hätte auf der seiten scrollen müssen was baer leider nicht geht.besonderst seite 3 wird abgeschnitten auch wenn ich ganz rauszoome.


### Session 7 ###

0. Navigation: von dem Weather Warning Konfigurator soll es zurück auf das Dashboard gehen und nicht auf den index /Stationssuche.

1. Presentation: Ich habe die Präsentation als ppt in meinem Googledrive, ich will  Claude Code mit meinem Googleworkspace verknüpfen. Dann sollest du in der lage sein powerpoint dateien dort abzulegen und einzulesen richtig?
ich habe ein Copie vorerst ins lokal Verzeichnis präsi gelegt als .pptx

1.2 In der Präsentation fehlt noch ein Teil der die Triggers der Weather Warnings erklärt und die Versendung der Emails mit Brevo und Mailhog. Erkläre mir auch noch mal JSONB das Deti Format und warum es hier sinnvolll ist zu bnutzen.

2. Diagramme: Kannst du gesamten Sonnenscheindauer in Stunden im Barplot der Sonnscheindauer anzeigen, einfach als Zahl in der Mitte, soll aber gut lesbar sein vor dem dunkeln hintergurnd.

3. Warnungskofigurator: Die Sonnenscheindauer sollen dort pro Tag angegeben werden und nicht als min/h sondern h/tag.

3.2 Es soll beim Speichern des Weather Alters, indem fenster in dem der name eingegeben wird auch ein Auswahl geben die bestimmt wann eine Notification per mail gesendet wird, zur auswahl steht: sobald daten verfügbar sind (sollte 7 tage sein), 1 - 6 tage vorher eintreffen der Wetter bedingungen, tag vorher, X Stunden vorher.

4. Bei dem Aufrufen von neuen Stationen werden macnhmal keine Daten abgrufen. Bsp Berlin, Station wird gefunden aber Dashboard zeigt: Hourly forecast
No data – run ETL job! Wie kommt es dazu? triggert der Airflow weather-ttl-pipeline nicht wenn man dashboard aufruft sondern "nur" alle 2 Stunden? das sollte nicht so sein. Aufjeden Fall sollte das in der Präsenatation nicht mehr vorkommen! schneler fix muss her.
Erkläre mir aussdem die SYNC Anzeige und wie sie mit Datenaktualisierung zusammenhängt.

5. Im Zusammenhang mit 4. wie genau sieht der Datenfluss aus? wann werden die airflow dags getriggert? wie genau sieht es innerhlab der dags aus? Genauer Beschreibung nochmal der Datenpiplines Extract, Transoform und Load.

6. Ich möchte nochmehr über Fast API und die Endpoints lernen da ich glaub das mir dort noch ein Bisschen Grundverständnis fehlt um das ganze System besser erklären zu können. Kannst du das mir noch erklären und veranschaulichen?

7. mein Todo: ich möchte noch ein Architekturdiagramm des linux servers zur präsentations hinzufügen das werde ich aber von ClaudCode auf dem Server genieren lassen weil er den einblick in das gesamte Dockersetup hat mit proxy manager usw.

8. mein todo: Ich möchte für die Präsi noch eine Bildschirmaufnahme machen wie ich durch die Website klicke mich anmelde, ein warninge konfiguriere und dann acuh eine warning erhalte. das sollten wir mit einer entsprechenden test warning vielleicht planen damit das funktioniert.

9. Im Dashbaord müssen wir noch mal die linke seit anpassen, unterhalb der wetterstation, wo die gespeicherten und ativen Weather Warnings angezeigt werden.

Überschirft: Weather-Alters.
General Alters
My Weather Alters
Triggered Alters

Momentan wird mir obwohl ich eingelogtt bin unter My warnigs angeziegt: " not signed in"

Also um dir noch mal mehr Kontext zu den Warnings/Alters geben: Allgemeine oder Voreingestellte Warnings sind in config/alers_config gespeichert und werden immer auf die akuelle Ausgewälte Station angewendet! hier werden keine emails versand wenn die bedingung eintriit sondern nur am linken Rand hier die Meldung angezeigt, mit Datum und Uhrzeit.
Unter My Alters sollen die vom User angelegt warnings bzw alters gespeichert sein, sowohl ative als auch deaktive. Die anzeige soll Name Station Bedingung und Zietrahmen enthalten. EIn click hier soll den Configurator öffnen.
Unter Triggert Alerts sollen alle aktuell vom User angelegte und getriggerten Warnings aufgeführt sein, genau so wie unter my Alters nur mit Name, Station sowie tag Uhrzeit und überschrittener Wert, bedingung un vorhersage wert. Ein Alter gilt solange als getriggert wie der wert auch in den Vorhersage Daten vorkommt.

10. Lass mal Claude code auf dem Server mit dem Opus Modell laufen um allen Code zu Überprüfen und Verbesserungen vorzuschlagen, vielleicht das nicht als letztes.

11. Kläre ab ob es vielleicht bei Warings und Alerts zu einer unstimmigkeit und uneindeutigkeit kommt , ich glaube das habe ich nicht einheitliche gemacht.

---

### Session 7 – Strukturierter Arbeitsplan (Claude Code, 2026-03-19)

**Deadline:** 20.03.2026

#### A) Code-Änderungen

| # | Aufgabe | Status |
|---|---------|--------|
| 0 | Navigation: Configurator → Dashboard (`history.back()`) | ✅ erledigt |
| 4 | Berlin-Bug: Auth von `/weather/fetch-now` entfernt | ✅ erledigt |
| 4b | Architektur-Fix: `_refresh_stale_cities()` in check_warnings DAG | ✅ erledigt |
| 4c | Architektur-Fix: General Alerts dynamisch für jede Stadt | ✅ erledigt |
| 9 | Sidebar: General / My Alerts / Triggered + "not signed in" Fix | ✅ erledigt |
| 3 | Configurator: Sonnenscheindauer-Einheit min/h → h/Tag | ✅ erledigt |
| 2 | Charts: Gesamte Sonnenscheindauer als Zahl im Barplot | ✅ erledigt |
| 3.2 | Alert speichern: Timing-Auswahl für Email-Notification (vollst. mit Logik) | ✅ erledigt |
| 11 | Terminologie Warnings vs. Alerts vereinheitlichen | ✅ erledigt |

#### B) Erklärungen (erledigt in Session 7)

- ✅ Airflow Datenfluss: DAG 1 (stündlich ETL) + DAG 2 (alle 2h Warning-Check)
- ✅ FastAPI & Endpoints: Grundverständnis + alle Endpoints dokumentiert
- ✅ JSONB: Was ist es, warum hier sinnvoll (conditions, validity, weather_raw)
- ✅ Trigger-Mechanismus Weather Warnings + Brevo vs. MailHog
- ✅ Berlin-Bug Ursache: fetch-now erfordert Auth, nicht-eingeloggte User → stiller Fehlschlag
- ✅ SYNC-Anzeige: zeigt last_updated aus DB, Staleness-Check > 6h triggert fetch-now

#### C) User-TODOs

| # | Aufgabe |
|---|---------|
| 1 | Google Workspace / Drive verknüpfen für Präsentation |
| 7 | Server-Architekturdiagramm: Claude Code auf Server (Docker/Proxy) |
| 8 | Bildschirmaufnahme: Login → Warning → Alert |
| 10 | Claude Code mit Opus auf Server – Code-Review |

#### Verbleibende Reihenfolge (nächste Session)

1. **3** – Configurator: Sunshine-Einheit h/Tag
2. **2** – Chart: Sunshine-Stunden als Zahl im Barplot
3. **3.2** – Email Notification Timing (vollständig mit Backend-Logik)
4. **11** – Terminologie vereinheitlichen
5. **1** – Präsentation (.pptx aus `/präsi` direkt bearbeiten)

#### Kritische Dateien

- `frontend/js/app.js` – Navigation, Sidebar, Charts
- `frontend/index.html` – Sidebar-Struktur
- `frontend/css/style.css` – Sidebar-Styling
- `backend/main.py` – API, Charts
- `backend/models.py` – Alert-Model (Timing-Felder)
- `backend/routers/weather_fetch.py` – fetch-now Auth entfernen
- `docker/init.sql` – DB-Schema

---

### Session 8 – Code Review: Security, Architecture & Best Practices (2026-03-20)

**Grundlage:** Opus Code-Review-Agent hat den gesamten Codebestand analysiert.
Dieser Session-Plan dokumentiert alle gefundenen Issues, priorisiert nach Schwere.

---

#### A) Critical Issues – Sofort beheben

| # | Issue | Datei(en) | Beschreibung |
|---|-------|-----------|-------------|
| C1 | SMTP-Credentials in Git-History | `.env` | Der Brevo SMTP-Key (`xsmtpsib-...`) wurde in die Git-History committed. `.gitignore` enthält `.env` zwar bereits, aber der Key war zuvor committed und ist in der History sichtbar. **Sofort-Massnahme:** Brevo-Dashboard → Key rotieren. `.env.example` anlegen (ohne echte Werte). Optional: `git filter-branch` oder BFG Repo Cleaner um die History zu bereinigen. |
| C2 | `/weather/fetch-now` ohne Rate-Limiting | `backend/routers/weather_fetch.py:310` | Endpoint ist unauthentifiziert (absichtlich seit Berlin-Bug-Fix). Aber ohne Rate-Limiting kann ein Angreifer: die Open-Meteo-API spammen, beliebige City-Namen in die DB schreiben, die DB mit 168 Rows pro Aufruf fluten. **Fix:** In-Memory Cooldown pro City (z.B. 5 Min) einbauen. |
| C3 | Route-Reihenfolge Bug: `/triggered` unerreichbar | `backend/routers/warnings.py` | ✅ **erledigt** – `/triggered` vor `/{warning_id}` verschoben |
| C4 | Falsche Spaltennamen in Triggered-Query | `backend/routers/warnings.py` | ✅ **erledigt** – `wind_speed_10m_max` → `wind_speed_max`, `wind_gusts_10m_max` → `wind_gusts_max` |
| C5 | Invertierte Token-Logik in `_require_internal_token` | `backend/main.py:198` | ✅ **erledigt** – `if not _INTERNAL_TOKEN or` → `if _INTERNAL_TOKEN and` |

---

#### B) Important Improvements – Architektur & Sicherheit

| # | Issue | Datei(en) | Beschreibung |
|---|-------|-----------|-------------|
| I1 | `main.py` aufteilen (1.275 Zeilen) | `backend/main.py` | Enthält Forecast-Endpoints, Alert-Logik, Chart-Generierung, Cache-Management und Stats in einer Datei. Vorschlag: `routers/charts.py`, `routers/forecast.py`, `routers/alerts.py`, `routers/stats.py` auslagern. `main.py` nur noch App-Setup + Router-Includes. |
| I2 | DRY: UPSERT-SQL 4x dupliziert | `load.py`, `check_warnings.py`, `weather_fetch.py`, `transform.py` | Gleicher UPSERT-Code für `weather_daily` und `weather_hourly` existiert in 4 Dateien. Bei neuen Spalten müssen alle 4 Stellen angepasst werden → Risiko für **Silent Data Loss**. **Fix:** Gemeinsames Modul `shared/sql_templates.py` oder DB-Funktion. |
| I3 | DRY: `WMO_CODES` 3x dupliziert | `backend/schemas.py`, `airflow/tasks/transform.py`, `test_pipeline.py` | Drei separate Kopien des gleichen Mappings. **Fix:** Zentrale Python-Datei `shared/wmo_codes.py`. |
| I4 | `ConditionRule` ohne Enum-Validierung | `backend/schemas.py:290` | `parameter` und `comparator` sind bare `str` – ein User könnte beliebige Werte senden. **Fix:** `WeatherParameter(str, Enum)` und `Comparator(str, Enum)` definieren. Verhindert ungültige Daten in JSONB. |
| I5 | `RegisterRequest` ohne Validierung | `backend/schemas.py:233` | Kein `EmailStr`, keine Passwort-Mindestlänge, keine Username-Einschränkung. Ein User kann sich mit `password=""` registrieren. **Fix:** `EmailStr`, `Field(min_length=8)`, Username-Pattern. |
| I6 | XSS in `warnings.html` | `frontend/warnings.html:1002-1003` | `${w.name}` und `${w.city}` werden unescaped in `innerHTML` eingefügt (Stored XSS). `escHtml()` existiert in `index.html:202` — muss auch in `warnings.html` verwendet werden. |
| I7 | Einzel-SQL-Inserts statt Batch | `backend/routers/weather_fetch.py:189-203` | 168 einzelne SQL-Statements pro fetch-now Aufruf (7×24 Stunden). In `load.py` wird korrekt `execute_batch` verwendet. **Fix:** Parameter sammeln, als Batch ausführen. |

---

#### C) Best Practice Suggestions

| # | Issue | Datei(en) | Beschreibung |
|---|-------|-----------|-------------|
| B1 | Deprecated `declarative_base` Import | `backend/database.py:30` | `from sqlalchemy.ext.declarative import declarative_base` ist seit SQLAlchemy 2.0 deprecated. **Fix:** `from sqlalchemy.orm import DeclarativeBase` + `class Base(DeclarativeBase): pass` |
| B2 | `sys.path.insert` in Airflow DAG | `airflow/dags/weather_dag.py:16` | Fragiler Pfad-Hack. Besser: Tasks als Python-Package installieren oder `__init__.py` mit relativen Imports. |
| B3 | Race Condition in `chart_cache.get()` | `backend/chart_cache.py:58-67` | Staleness-Check passiert **ausserhalb** des Locks. Zwischen Lesen und Prüfen könnte ein anderer Thread die Entry überschrieben haben. **Fix:** Gesamte get-Logik in einen Lock-Block. |
| B4 | Fehlender Backend-Healthcheck in Docker | `docker-compose.yml` | Postgres und Airflow haben Healthchecks, Backend nicht. **Fix:** `healthcheck: test: curl -f http://localhost:8000/health` |
| B5 | Kein CSP-Header | `nginx/nginx.conf` | Security-Headers (X-Frame-Options etc.) sind vorhanden, aber Content Security Policy fehlt. Wäre zusätzlicher XSS-Schutz. |
| B6 | Timing-sicherer Token-Vergleich | `backend/main.py:198` | `!=` für Token-Vergleich ist anfällig für Timing-Angriffe. **Fix:** `hmac.compare_digest()` verwenden (konstante Laufzeit). |
| B7 | Typ-Hints in Airflow Tasks | `airflow/tasks/*.py` | Task-Funktionen nutzen `**context` ohne Typ-Hinweise. Seit Airflow 2.3+ gibt es `TaskInstance` als Typ. |

---

#### D) Vorgeschlagene Reihenfolge

Die Issues sind nach Abhängigkeiten und Risiko sortiert:

| Schritt | Issues | Aufwand | Beschreibung |
|---------|--------|---------|-------------|
| 1 | C5 | klein | Token-Logik fixen (1 Zeile) |
| 2 | C3 + C4 | klein | Route-Reihenfolge korrigieren + Spaltennamen fixen |
| 3 | C2 | mittel | Rate-Limiting für `/fetch-now` |
| 4 | C1 | mittel | Brevo-Key rotieren, `.env.example` anlegen, ggf. History bereinigen |
| 5 | I6 | klein | XSS-Fix: `escHtml()` in `warnings.html` |
| 6 | I5 + I4 | mittel | Input-Validierung: RegisterRequest + ConditionRule Enums |
| 7 | B1 + B3 | klein | Deprecated Import + Cache Race Condition |
| 8 | B6 | klein | `hmac.compare_digest()` für Token |
| 9 | I1 | gross | `main.py` in Router-Module aufteilen |
| 10 | I2 + I3 | gross | DRY: SQL-Templates + WMO_CODES zentralisieren |
| 11 | B4 + B5 | klein | Docker Healthcheck + CSP Header |
| 12 | I7 | mittel | Batch-SQL in `weather_fetch.py` |

---

#### E) Kritische Dateien (Session 8)

- `backend/main.py` – Token-Logik (C5), Chart-Router-Split (I1)
- `backend/routers/warnings.py` – Route-Reihenfolge (C3), Spaltennamen (C4)
- `backend/routers/weather_fetch.py` – Rate-Limiting (C2), Batch-SQL (I7)
- `backend/schemas.py` – Enum-Validierung (I4), RegisterRequest (I5)
- `backend/database.py` – Deprecated Import (B1)
- `backend/chart_cache.py` – Race Condition (B3)
- `frontend/warnings.html` – XSS-Fix (I6)
- `docker-compose.yml` – Backend Healthcheck (B4)
- `nginx/nginx.conf` – CSP Header (B5)
- `.env` / `.env.example` – Credential-Rotation (C1)
