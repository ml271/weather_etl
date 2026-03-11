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

**UI-Aufbau (3-spaltig)**

| Links | Mitte | Rechts |
|---|---|---|
| Station / Ort / Gebiet wählen (Suchfeld oder Dropdown) | Wetter-Parameter wählen (Niederschlag, Temperatur, Wind, …) + Bedingung definieren (z.B. Temperatur > 32) + AND / AND NOT Verknüpfung | Zeitliche Gültigkeit (von / bis) |

**Vorkonfigurierte Warnings (Templates)**
- Hitzwarnung (Temperatur > 32°C)
- Frostwarnung (Temperatur < 0°C)
- Starkregen (Niederschlag > 20mm/h)
- Sturmwarnung (Windgeschwindigkeit > 60 km/h)

**FastAPI Endpoints**
- `GET /warnings/templates` – vorkonfigurierte Warnings
- `POST /warnings/` – neue Warning speichern
- `GET /warnings/` – alle Warnings des Users
- `DELETE /warnings/{id}` – Warning löschen

---

### Session 4 – Airflow Warning-Check DAG + Mail

**Ziel:** Automatische Prüfung und Mail-Benachrichtigung.

**Neuer Airflow DAG:** `check_weather_warnings`
- Läuft stündlich
- Holt aktuelle Wetterdaten pro Station
- Prüft gegen alle aktiven User-Warnings
- Triggert Mail wenn Bedingung erfüllt

**Mail-Setup**
- SMTP via Python (`smtplib`) oder Mailgun
- Template: Station, Warning-Name, aktueller Wert, Schwellwert

---

### Session 5 – Integration & Feinschliff

**Ziel:** Alles zusammenbauen, testen, polish.

- Navigation: Landing Page → Dashboard → Login → Baukasten
- Nginx Routing prüfen
- End-to-End Test: Warning konfigurieren → Airflow triggern → Mail prüfen
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
