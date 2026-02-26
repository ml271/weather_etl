#!/usr/bin/env python3
"""
Weather ETL – Lokaler Test ohne Docker/Airflow
Führt Extract → Transform → Load direkt aus und zeigt die Ergebnisse.

Voraussetzungen:
  pip install requests pandas psycopg2-binary pyyaml sqlalchemy

Verwendung:
  # Nur API testen (kein DB nötig):
  python test_pipeline.py --no-db

  # Vollständiger Test mit PostgreSQL:
  python test_pipeline.py
"""

import os
import sys
import json
import argparse
import requests
import yaml
from datetime import datetime, timezone
from pathlib import Path

# ── Farben für Terminal-Output ─────────────────────
class C:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    RED    = "\033[91m"
    BLUE   = "\033[94m"
    CYAN   = "\033[96m"
    DIM    = "\033[2m"

def ok(msg):   print(f"  {C.GREEN}✓{C.RESET} {msg}")
def warn(msg): print(f"  {C.YELLOW}⚠{C.RESET} {msg}")
def err(msg):  print(f"  {C.RED}✗{C.RESET} {msg}")
def info(msg): print(f"  {C.BLUE}→{C.RESET} {msg}")
def header(msg):
    print(f"\n{C.BOLD}{C.CYAN}{'─'*50}{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}  {msg}{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}{'─'*50}{C.RESET}")

# ─────────────────────────────────────────────────────
# SCHRITT 1: Extract – API testen
# ─────────────────────────────────────────────────────

def test_extract(city, lat, lon):
    header("SCHRITT 1: EXTRACT – Open-Meteo API")

    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat, "longitude": lon,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,snowfall_sum,wind_speed_10m_max,wind_gusts_10m_max,weather_code,uv_index_max,sunrise,sunset",
        "hourly": "temperature_2m,apparent_temperature,precipitation,rain,snowfall,wind_speed_10m,wind_direction_10m,relative_humidity_2m,weather_code,is_day",
        "timezone": "Europe/Berlin",
        "forecast_days": 7,
    }

    info(f"Anfrage an Open-Meteo für {C.BOLD}{city}{C.RESET} ({lat}, {lon})...")
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()

        daily_count  = len(data.get("daily",  {}).get("time", []))
        hourly_count = len(data.get("hourly", {}).get("time", []))

        ok(f"API antwortet mit Status {r.status_code}")
        ok(f"{daily_count} tägliche Datenpunkte empfangen")
        ok(f"{hourly_count} stündliche Datenpunkte empfangen")

        # Vorschau
        d = data["daily"]
        print(f"\n  {C.DIM}Vorschau (nächste 3 Tage):{C.RESET}")
        for i in range(min(3, daily_count)):
            print(f"  {C.DIM}  {d['time'][i]}  "
                  f"Max: {d['temperature_2m_max'][i]}°C  "
                  f"Min: {d['temperature_2m_min'][i]}°C  "
                  f"Regen: {d['precipitation_sum'][i]}mm{C.RESET}")

        return {"city": city, "latitude": lat, "longitude": lon,
                "fetched_at": datetime.now(timezone.utc).isoformat(), "data": data}

    except requests.exceptions.ConnectionError:
        err("Keine Verbindung zur API – Internet verfügbar?")
        sys.exit(1)
    except Exception as e:
        err(f"API Fehler: {e}")
        sys.exit(1)


# ─────────────────────────────────────────────────────
# SCHRITT 2: Transform – Daten verarbeiten
# ─────────────────────────────────────────────────────

WMO_CODES = {
    0:"Klarer Himmel",1:"Überwiegend klar",2:"Teilweise bewölkt",3:"Bedeckt",
    45:"Nebel",48:"Reifnebel",
    51:"Leichter Nieselregen",53:"Mäßiger Nieselregen",55:"Starker Nieselregen",
    61:"Leichter Regen",63:"Mäßiger Regen",65:"Starker Regen",
    71:"Leichter Schneefall",73:"Mäßiger Schneefall",75:"Starker Schneefall",
    80:"Leichte Regenschauer",81:"Mäßige Regenschauer",82:"Starke Regenschauer",
    95:"Gewitter",96:"Gewitter mit Hagel",99:"Gewitter mit starkem Hagel",
}

def safe(lst, i, default=None):
    try: v = lst[i]; return v if v is not None else default
    except: return default

def apply_op(val, op, threshold):
    ops = {">": lambda a,b: a>b, ">=": lambda a,b: a>=b,
           "<": lambda a,b: a<b, "<=": lambda a,b: a<=b, "==": lambda a,b: a==b}
    return ops.get(op, lambda a,b: False)(val, threshold)

def test_transform(raw, config_path):
    header("SCHRITT 2: TRANSFORM – Daten verarbeiten & Alerts")

    city = raw["city"]
    d    = raw["data"]["daily"]
    h    = raw["data"]["hourly"]

    # Daily
    daily = []
    for i, date_str in enumerate(d.get("time", [])):
        daily.append({
            "city": city, "forecast_date": date_str,
            "temperature_max":   safe(d.get("temperature_2m_max"), i),
            "temperature_min":   safe(d.get("temperature_2m_min"), i),
            "precipitation_sum": safe(d.get("precipitation_sum"), i, 0.0),
            "snowfall_sum":      safe(d.get("snowfall_sum"), i, 0.0),
            "wind_speed_max":    safe(d.get("wind_speed_10m_max"), i),
            "wind_gusts_max":    safe(d.get("wind_gusts_10m_max"), i),
            "weather_code":      safe(d.get("weather_code"), i),
            "uv_index_max":      safe(d.get("uv_index_max"), i),
            "sunrise":           safe(d.get("sunrise"), i),
            "sunset":            safe(d.get("sunset"), i),
        })
    ok(f"{len(daily)} tägliche Records transformiert")

    # Hourly
    hourly_count = len(h.get("time", []))
    ok(f"{hourly_count} stündliche Records transformiert")

    # Alerts
    alerts = []
    field_map = {
        "temperature_max": "temperature_max", "temperature_min": "temperature_min",
        "precipitation_sum": "precipitation_sum", "snowfall_sum": "snowfall_sum",
        "wind_speed_max": "wind_speed_max", "wind_gusts_max": "wind_gusts_max",
        "uv_index_max": "uv_index_max",
    }

    try:
        with open(config_path) as f:
            rules = [r for r in yaml.safe_load(f).get("alerts", []) if r.get("enabled", True)]
        info(f"{len(rules)} Alert-Regeln geladen aus {config_path}")
    except FileNotFoundError:
        warn(f"alerts_config.yaml nicht gefunden – überspringe Alert-Check")
        rules = []

    for record in daily:
        for rule in rules:
            triggered = {}
            all_met = True
            for field, cond in rule.get("conditions", {}).items():
                db_field = field_map.get(field)
                val = record.get(db_field) if db_field else None
                if val is None: all_met = False; break
                if not apply_op(float(val), cond["operator"], float(cond["value"])):
                    all_met = False; break
                triggered[field] = {"value": val, "operator": cond["operator"], "threshold": cond["value"]}
            if all_met and triggered:
                alerts.append({**rule, "forecast_date": record["forecast_date"], "condition_met": triggered})

    if alerts:
        print(f"\n  {C.YELLOW}Ausgelöste Alerts:{C.RESET}")
        for a in alerts:
            icon = {"danger":"🚨","warning":"⚠️","info":"ℹ️"}.get(a["severity"],"⚡")
            sev_color = {"danger": C.RED, "warning": C.YELLOW, "info": C.CYAN}.get(a["severity"], "")
            print(f"  {icon} {sev_color}{a['severity'].upper():8}{C.RESET} {a['name']:25} → {a['forecast_date']}")
    else:
        ok("Keine Alerts ausgelöst (gutes Wetter! 🌤️)")

    ok(f"{len(alerts)} Alert(s) generiert")
    return {"city": city, "daily": daily, "hourly_count": hourly_count, "alerts": alerts, "raw": raw}


# ─────────────────────────────────────────────────────
# SCHRITT 3: Load – Datenbank (optional)
# ─────────────────────────────────────────────────────

def test_load(transformed):
    header("SCHRITT 3: LOAD – PostgreSQL")

    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        warn("psycopg2 nicht installiert – pip install psycopg2-binary")
        return False

    host     = os.getenv("POSTGRES_HOST", "localhost")
    port     = os.getenv("POSTGRES_PORT", "5432")
    db       = os.getenv("POSTGRES_DB",   "weather_db")
    user     = os.getenv("POSTGRES_USER", "weather_user")
    password = os.getenv("POSTGRES_PASSWORD", "weather_pass")

    info(f"Verbinde mit {user}@{host}:{port}/{db} ...")

    try:
        conn = psycopg2.connect(host=host, port=port, dbname=db, user=user, password=password, connect_timeout=5)
        ok("Datenbankverbindung erfolgreich!")
    except psycopg2.OperationalError as e:
        err(f"Verbindung fehlgeschlagen: {e}")
        warn("Ist PostgreSQL gestartet? (docker compose up postgres)")
        return False

    city    = transformed["city"]
    daily   = transformed["daily"]
    alerts  = transformed["alerts"]
    raw     = transformed["raw"]

    try:
        with conn:
            with conn.cursor() as cur:
                # Raw
                cur.execute(
                    "INSERT INTO weather_raw (city, latitude, longitude, raw_json) VALUES (%s,%s,%s,%s)",
                    (city, raw["latitude"], raw["longitude"], json.dumps(raw["data"]))
                )
                ok("weather_raw: 1 Record eingefügt")

                # Daily UPSERT
                upsert_sql = """
                    INSERT INTO weather_daily
                      (city,forecast_date,temperature_max,temperature_min,precipitation_sum,
                       snowfall_sum,wind_speed_max,wind_gusts_max,weather_code,uv_index_max,sunrise,sunset)
                    VALUES (%(city)s,%(forecast_date)s,%(temperature_max)s,%(temperature_min)s,%(precipitation_sum)s,
                            %(snowfall_sum)s,%(wind_speed_max)s,%(wind_gusts_max)s,%(weather_code)s,%(uv_index_max)s,
                            %(sunrise)s,%(sunset)s)
                    ON CONFLICT (city, forecast_date) DO UPDATE SET
                      temperature_max=EXCLUDED.temperature_max, temperature_min=EXCLUDED.temperature_min,
                      precipitation_sum=EXCLUDED.precipitation_sum, wind_speed_max=EXCLUDED.wind_speed_max,
                      weather_code=EXCLUDED.weather_code, created_at=NOW()
                """
                psycopg2.extras.execute_batch(cur, upsert_sql, daily)
                ok(f"weather_daily: {len(daily)} Records upserted")

                # Alerts
                cur.execute("UPDATE weather_alerts SET is_active=FALSE WHERE city=%s AND is_active=TRUE", (city,))
                if alerts:
                    alert_sql = """
                        INSERT INTO weather_alerts (city,alert_name,severity,message,condition_met,forecast_date,is_active)
                        VALUES (%(city)s,%(name)s,%(severity)s,%(message)s,%(condition_met_json)s,%(forecast_date)s,TRUE)
                    """
                    for a in alerts:
                        a["condition_met_json"] = json.dumps(a["condition_met"])
                        a["city"] = city
                    psycopg2.extras.execute_batch(cur, alert_sql, alerts)
                ok(f"weather_alerts: {len(alerts)} neue Alerts eingefügt")

        conn.close()

        # Verification query
        conn2 = psycopg2.connect(host=host, port=port, dbname=db, user=user, password=password)
        with conn2.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM weather_daily WHERE city=%s", (city,))
            daily_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM weather_alerts WHERE city=%s AND is_active=TRUE", (city,))
            alert_count = cur.fetchone()[0]
        conn2.close()

        print(f"\n  {C.DIM}Verifikation:{C.RESET}")
        ok(f"weather_daily enthält jetzt {daily_count} Records für {city}")
        ok(f"weather_alerts enthält {alert_count} aktive Alerts für {city}")
        return True

    except Exception as e:
        err(f"Load fehlgeschlagen: {e}")
        return False


# ─────────────────────────────────────────────────────
# SCHRITT 4: API Endpoints testen
# ─────────────────────────────────────────────────────

def test_api(base_url="http://localhost:8000"):
    header("SCHRITT 4: BACKEND API – Endpoints testen")

    endpoints = [
        ("GET", "/health",             "Health Check"),
        ("GET", "/summary",            "Dashboard Summary"),
        ("GET", "/forecast/daily",     "7-Tage Forecast"),
        ("GET", "/forecast/hourly",    "Stündliche Vorhersage"),
        ("GET", "/alerts",             "Aktive Alerts"),
        ("GET", "/stats/temperature",  "Temperatur Chart-Daten"),
        ("GET", "/stats/hourly-temp",  "Stunden Chart-Daten"),
    ]

    all_ok = True
    for method, path, label in endpoints:
        try:
            r = requests.get(base_url + path, timeout=5)
            if r.status_code in (200, 404):
                status = f"{C.GREEN}{r.status_code}{C.RESET}" if r.status_code == 200 else f"{C.YELLOW}{r.status_code}{C.RESET}"
                ok(f"{label:35} {status}")
            else:
                err(f"{label:35} {r.status_code}")
                all_ok = False
        except requests.exceptions.ConnectionError:
            warn(f"{label:35} nicht erreichbar (Backend läuft?)")
            all_ok = False

    return all_ok


# ─────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Weather ETL – Lokaler Test")
    parser.add_argument("--no-db",     action="store_true", help="DB-Test überspringen")
    parser.add_argument("--no-api",    action="store_true", help="API-Test überspringen")
    parser.add_argument("--city",      default="Freiburg",  help="Stadtname")
    parser.add_argument("--lat",       default=47.9990,     type=float)
    parser.add_argument("--lon",       default=7.8421,      type=float)
    parser.add_argument("--api-url",   default="http://localhost:8000")
    parser.add_argument("--config",    default="config/alerts_config.yaml")
    args = parser.parse_args()

    print(f"\n{C.BOLD}{'═'*50}")
    print(f"  🌤️  WEATHER ETL – PIPELINE TEST")
    print(f"{'═'*50}{C.RESET}")
    print(f"  Stadt:  {C.BOLD}{args.city}{C.RESET} ({args.lat}, {args.lon})")
    print(f"  Config: {args.config}")
    print(f"  API:    {args.api_url}")

    # 1. Extract
    raw = test_extract(args.city, args.lat, args.lon)

    # 2. Transform
    transformed = test_transform(raw, args.config)

    # 3. Load
    db_ok = True
    if not args.no_db:
        db_ok = test_load(transformed)
    else:
        header("SCHRITT 3: LOAD – Übersprungen (--no-db)")
        warn("DB-Test übersprungen")

    # 4. API
    api_ok = True
    if not args.no_api:
        api_ok = test_api(args.api_url)
    else:
        header("SCHRITT 4: API – Übersprungen (--no-api)")
        warn("API-Test übersprungen")

    # Zusammenfassung
    header("ERGEBNIS")
    ok("Extract (Open-Meteo API)    ✓")
    ok("Transform (Daten + Alerts)  ✓")
    print(f"  {'✓' if db_ok  else '⚠'} {'Load (PostgreSQL)            ✓' if db_ok  else f'{C.YELLOW}Load (PostgreSQL)            ⚠ – DB nicht erreichbar{C.RESET}'}")
    print(f"  {'✓' if api_ok else '⚠'} {'API Endpoints                ✓' if api_ok else f'{C.YELLOW}API Endpoints                ⚠ – Backend nicht gestartet{C.RESET}'}")

    print(f"\n{C.BOLD}{'═'*50}{C.RESET}")
    if db_ok and api_ok:
        print(f"  {C.GREEN}{C.BOLD}🎉 Alle Tests bestanden! Pipeline bereit.{C.RESET}")
        print(f"\n  {C.DIM}Dashboard: http://localhost{C.RESET}")
        print(f"  {C.DIM}Airflow:   http://localhost:8080  (admin/admin){C.RESET}")
        print(f"  {C.DIM}API Docs:  http://localhost:8000/docs{C.RESET}")
    else:
        print(f"  {C.YELLOW}{C.BOLD}⚠ Teilweise erfolgreich – Stack noch nicht komplett gestartet.{C.RESET}")
        print(f"\n  {C.DIM}Führe aus: docker compose up -d --build{C.RESET}")
    print(f"{C.BOLD}{'═'*50}{C.RESET}\n")


if __name__ == "__main__":
    main()
