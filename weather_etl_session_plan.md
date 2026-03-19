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

| # | Aufgabe | Aufwand |
|---|---------|---------|
| 0 | Navigation: Configurator → Dashboard (nicht Landing Page) | klein |
| 2 | Charts: Gesamte Sonnenscheindauer (Stunden) als Zahl im Barplot | mittel |
| 3 | Configurator: Sonnenscheindauer-Einheit min/h → h/Tag | klein |
| 3.2 | Alert speichern: Timing-Auswahl für Email-Notification (vollst. mit Logik) | groß |
| 4 | Quick Fix: Neue Station triggert ETL nicht – Berlin-Bug (auth entfernen) | mittel |
| 9 | Sidebar: General / My Alerts / Triggered Alerts + "not signed in" Fix | groß |
| 11 | Terminologie Warnings vs. Alerts vereinheitlichen | mittel |

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

#### Festgelegte Reihenfolge

1. Erklärungen (5 → 6 → 1.2 → 4/SYNC) ✅ erledigt
2. Berlin-Bug Quick Fix (0 → 4)
3. Sidebar Alerts umstrukturieren (9)
4. Configurator Einheit (3)
5. Sunshine Chart (2)
6. Email Notification Timing (3.2)
7. Terminologie (11)
8. Präsentation .pptx bearbeiten (1)

#### Kritische Dateien

- `frontend/js/app.js` – Navigation, Sidebar, Charts
- `frontend/index.html` – Sidebar-Struktur
- `frontend/css/style.css` – Sidebar-Styling
- `backend/main.py` – API, Charts
- `backend/models.py` – Alert-Model (Timing-Felder)
- `backend/routers/weather_fetch.py` – fetch-now Auth entfernen
- `docker/init.sql` – DB-Schema
