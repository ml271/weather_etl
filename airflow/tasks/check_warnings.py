"""
Check Weather Warnings Task – prüft User-Warnungen gegen Vorhersagedaten und sendet Emails.
Liest ausschließlich aus der DB (keine neuen API-Calls).
"""
import os
import json
import logging
import smtplib
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)


# ── DB ────────────────────────────────────────────────────────────────────────

def get_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=int(os.getenv("POSTGRES_PORT", 5432)),
        dbname=os.getenv("POSTGRES_DB", "weather_db"),
        user=os.getenv("POSTGRES_USER", "weather_user"),
        password=os.getenv("POSTGRES_PASSWORD", "weather_pass"),
    )


# ── Validity check ────────────────────────────────────────────────────────────

def is_valid(validity: dict, check_date: date) -> bool:
    """Returns True if this warning applies to check_date."""
    vtype = validity.get("type", "")
    if vtype == "date_range":
        df = validity.get("date_from")
        dt = validity.get("date_to")
        if df and dt:
            return date.fromisoformat(df) <= check_date <= date.fromisoformat(dt)
        return False
    elif vtype == "weekdays":
        # 0 = Montag … 6 = Sonntag
        return check_date.weekday() in (validity.get("weekdays") or [])
    elif vtype == "months":
        return check_date.month in (validity.get("months") or [])
    return False


# ── Condition evaluation ──────────────────────────────────────────────────────

def evaluate_conditions(conditions: list, record: dict) -> list:
    """
    Evaluates all conditions (AND logic) against a daily forecast record.
    Returns the list of triggered conditions with actual values,
    or an empty list if any condition is not met.
    """
    triggered = []
    for rule in conditions:
        param     = rule.get("parameter")
        comp      = rule.get("comparator", ">")
        threshold = float(rule.get("value", 0))
        value     = record.get(param)

        if value is None:
            return []  # missing data → not triggered

        value = float(value)
        ops = {
            ">":  value > threshold,
            ">=": value >= threshold,
            "<":  value < threshold,
            "<=": value <= threshold,
            "==": value == threshold,
        }
        if ops.get(comp, False):
            triggered.append({**rule, "actual_value": value})
        else:
            return []  # AND logic: any failure → not triggered

    return triggered


# ── Email ─────────────────────────────────────────────────────────────────────

def build_email_html(warning_name: str, city: str, forecast_date: str, triggered: list) -> str:
    rows = ""
    for t in triggered:
        label = t.get("label") or t.get("parameter", "")
        rows += f"""
              <tr>
                <td style="padding:10px 14px;font-family:'Courier New',monospace;font-size:13px;
                           color:#c8d8f0;border-bottom:1px solid #1a2a3f;">{label}</td>
                <td style="padding:10px 14px;font-family:'Courier New',monospace;font-size:13px;
                           color:#4a9eff;border-bottom:1px solid #1a2a3f;">{t['comparator']} {t['value']}</td>
                <td style="padding:10px 14px;font-family:'Courier New',monospace;font-size:13px;
                           color:#ff9d4a;font-weight:bold;border-bottom:1px solid #1a2a3f;">{t['actual_value']:.1f}</td>
              </tr>"""

    return f"""<!DOCTYPE html>
<html lang="de">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#080c12;font-family:'Courier New',monospace;color:#c8d8f0;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#080c12;padding:40px 20px;">
    <tr><td align="center">
      <table width="580" cellpadding="0" cellspacing="0"
             style="background:#0d1520;border:1px solid #1a2a3f;border-radius:8px;overflow:hidden;max-width:580px;">

        <!-- Header bar -->
        <tr>
          <td style="background:#1a2a3f;padding:22px 28px;">
            <div style="font-size:9px;letter-spacing:.22em;color:#4a6080;text-transform:uppercase;">
              Weather Station &nbsp;·&nbsp; Alert Notification
            </div>
            <div style="font-size:22px;font-weight:bold;color:#ff9d4a;margin-top:8px;letter-spacing:.03em;">
              ⚡&nbsp; {warning_name.upper()}
            </div>
          </td>
        </tr>

        <!-- Station + Date row -->
        <tr>
          <td style="padding:22px 28px 0;">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td width="50%" style="padding-right:20px;">
                  <div style="font-size:9px;letter-spacing:.18em;color:#4a6080;text-transform:uppercase;margin-bottom:4px;">Station</div>
                  <div style="font-size:17px;color:#c8d8f0;">{city}</div>
                </td>
                <td width="50%">
                  <div style="font-size:9px;letter-spacing:.18em;color:#4a6080;text-transform:uppercase;margin-bottom:4px;">Vorhersagedatum</div>
                  <div style="font-size:17px;color:#c8d8f0;">{forecast_date}</div>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Divider -->
        <tr><td style="padding:18px 28px 0;"><div style="height:1px;background:#1a2a3f;"></div></td></tr>

        <!-- Conditions table -->
        <tr>
          <td style="padding:18px 28px 24px;">
            <div style="font-size:9px;letter-spacing:.18em;color:#4a6080;text-transform:uppercase;margin-bottom:12px;">
              Ausgelöste Bedingungen
            </div>
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="border:1px solid #1a2a3f;border-radius:4px;overflow:hidden;">
              <tr style="background:#1a2a3f;">
                <td style="padding:8px 14px;font-size:9px;letter-spacing:.12em;color:#4a6080;text-transform:uppercase;">Parameter</td>
                <td style="padding:8px 14px;font-size:9px;letter-spacing:.12em;color:#4a6080;text-transform:uppercase;">Schwellwert</td>
                <td style="padding:8px 14px;font-size:9px;letter-spacing:.12em;color:#4a6080;text-transform:uppercase;">Gemessen</td>
              </tr>
              {rows}
            </table>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="padding:16px 28px 22px;border-top:1px solid #1a2a3f;">
            <div style="font-size:9px;color:#4a6080;letter-spacing:.1em;text-transform:uppercase;">
              Weather ETL Monitoring System &nbsp;·&nbsp; Automatische Benachrichtigung
            </div>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def send_email(to_email: str, subject: str, html_body: str):
    smtp_host = os.getenv("SMTP_HOST", "mailhog")
    smtp_port = int(os.getenv("SMTP_PORT", "1025"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASSWORD", "")
    smtp_from = os.getenv("SMTP_FROM", "weather-etl@local.dev")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = smtp_from
    msg["To"]      = to_email
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        if smtp_user:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_from, [to_email], msg.as_string())

    logger.info(f"Email sent → {to_email}: {subject}")


# ── Airflow Task Entry Point ──────────────────────────────────────────────────

def check_warnings(**context):
    """
    Loads all active user warnings, checks them against the next 7 days of daily forecast,
    and sends one email per (warning × forecast_date) — no duplicates.
    """
    today = date.today()
    forecast_dates = [today + timedelta(days=i) for i in range(7)]

    sent_count    = 0
    skipped_count = 0
    error_count   = 0

    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

            # ── Load all active warnings + user email ──────────────────────
            cur.execute("""
                SELECT w.id, w.city, w.name, w.conditions, w.validity,
                       u.email, u.username
                FROM   warnings w
                JOIN   users    u ON w.user_id = u.id
                WHERE  w.active = TRUE AND u.is_active = TRUE
            """)
            warnings = cur.fetchall()
            logger.info(f"Checking {len(warnings)} active warning(s) over {len(forecast_dates)} days")

            for warning in warnings:
                wid        = warning["id"]
                city       = warning["city"]
                wname      = warning["name"]
                email      = warning["email"]
                conditions = (
                    warning["conditions"]
                    if isinstance(warning["conditions"], list)
                    else json.loads(warning["conditions"])
                )
                validity = (
                    warning["validity"]
                    if isinstance(warning["validity"], dict)
                    else json.loads(warning["validity"])
                )

                for fdate in forecast_dates:

                    # ── Check temporal validity ────────────────────────────
                    if not is_valid(validity, fdate):
                        continue

                    # ── Already notified? ──────────────────────────────────
                    cur.execute("""
                        SELECT 1 FROM warning_notifications
                        WHERE warning_id = %s AND forecast_date = %s
                    """, (wid, fdate))
                    if cur.fetchone():
                        skipped_count += 1
                        continue

                    # ── Fetch daily forecast for city + date ───────────────
                    cur.execute("""
                        SELECT temperature_max, temperature_min,
                               precipitation_sum, snowfall_sum,
                               wind_speed_max, wind_gusts_max,
                               uv_index_max, weather_code
                        FROM   weather_daily
                        WHERE  city = %s AND forecast_date = %s
                    """, (city, fdate))
                    record = cur.fetchone()
                    if not record:
                        continue  # no data for this city yet

                    # ── Evaluate conditions ────────────────────────────────
                    triggered = evaluate_conditions(conditions, dict(record))
                    if not triggered:
                        continue

                    # ── Send email ─────────────────────────────────────────
                    date_str = fdate.strftime("%d.%m.%Y")
                    subject  = f"⚡ Wetterwarnung: {wname} – {city} am {date_str}"
                    html     = build_email_html(wname, city, date_str, triggered)

                    try:
                        send_email(email, subject, html)
                        cur.execute("""
                            INSERT INTO warning_notifications (warning_id, forecast_date)
                            VALUES (%s, %s) ON CONFLICT DO NOTHING
                        """, (wid, fdate))
                        conn.commit()
                        sent_count += 1
                    except Exception as e:
                        logger.error(f"Email to {email} failed for warning {wname}: {e}")
                        error_count += 1

    finally:
        conn.close()

    logger.info(
        f"Warning check done — sent: {sent_count}, "
        f"already notified: {skipped_count}, errors: {error_count}"
    )
    return {"sent": sent_count, "skipped": skipped_count, "errors": error_count}
