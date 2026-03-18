"""
Airflow ETL – Check Weather Warnings Task
==========================================

Evaluates all active user-defined weather warnings against the current daily
forecast data and sends HTML email notifications for any new threshold breaches.

This task is read-only with respect to weather data: it never calls the
Open-Meteo API. It queries the ``weather_daily`` table (populated by the main
ETL pipeline) and the ``warnings`` / ``users`` tables managed by the FastAPI
backend.

Notification deduplication:
  The ``warning_notifications`` table records which (warning_id, forecast_date)
  pairs have already triggered an email. Before sending, the task checks this
  table and skips pairs that have already been notified. This guarantees at most
  one email per user per (warning × forecast_date) combination per warning
  lifecycle.

Evaluation logic:
  All conditions in a warning's ``conditions`` list must be simultaneously
  satisfied (AND logic) for the warning to fire. The validity specification
  (``validity`` JSONB) determines which calendar dates the warning is active for.

Email format:
  Emails are rendered as styled HTML using a dark-themed table layout that
  matches the dashboard aesthetic. They are sent via SMTP (configurable; defaults
  to the local MailHog catch-all server on port 1025 for development).

Environment variables:
  POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
  SMTP_HOST     (default: ``mailhog``)
  SMTP_PORT     (default: ``1025``)
  SMTP_USER     (default: empty – no authentication)
  SMTP_PASSWORD (default: empty)
  SMTP_FROM     (default: ``weather-etl@local.dev``)

Dependencies:
  psycopg2-binary, smtplib (standard library)

Author: <project maintainer>
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
    """Create and return a new psycopg2 connection to the PostgreSQL database.

    Connection parameters are read from environment variables with safe
    fallback defaults that match the Docker Compose configuration.

    Returns:
        A new, open ``psycopg2.extensions.connection`` object.

    Raises:
        psycopg2.OperationalError: When the database is unreachable or the
            credentials are invalid.
    """
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=int(os.getenv("POSTGRES_PORT", 5432)),
        dbname=os.getenv("POSTGRES_DB", "weather_db"),
        user=os.getenv("POSTGRES_USER", "weather_user"),
        password=os.getenv("POSTGRES_PASSWORD", "weather_pass"),
    )


# ── Validity check ────────────────────────────────────────────────────────────

def is_valid(validity: dict, check_date: date) -> bool:
    """Determine whether a warning's validity specification covers a given date.

    Supports three validity types defined in the ``ValiditySpec`` schema:

    - ``"date_range"``: The warning is active between ``date_from`` and
      ``date_to`` (both inclusive, ISO-8601 date strings).
    - ``"weekdays"``: The warning is active on specific days of the week.
      Weekday integers follow Python's ``date.weekday()`` convention:
      0 = Monday … 6 = Sunday.
    - ``"months"``: The warning is active during specific calendar months
      (1 = January … 12 = December).

    Any other ``type`` value or a missing / malformed spec returns ``False``.

    Args:
        validity: A dict matching the ``ValiditySpec`` schema, as stored in
                  the ``warnings.validity`` JSONB column.
        check_date: The calendar date to test against the validity spec.

    Returns:
        ``True`` if the warning should be evaluated for ``check_date``,
        ``False`` otherwise.
    """
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
    """Render the HTML body for a weather warning notification email.

    Produces a fully self-contained HTML document with inline CSS styled in
    the same dark blue-grey theme as the dashboard. The email is designed to
    render correctly in major email clients without external stylesheets.

    Args:
        warning_name: The user-defined warning name shown in the email subject
                      line and header.
        city: The city the warning monitors (shown in the "Station" field).
        forecast_date: The affected forecast date as a formatted string, e.g.
                       ``"01.06.2025"``.
        triggered: List of triggered condition dicts. Each dict must contain
                   the keys ``"parameter"`` (or ``"label"``), ``"comparator"``,
                   ``"value"`` (threshold), and ``"actual_value"`` (measured
                   value that exceeded the threshold).

    Returns:
        A complete HTML string suitable for use as the body of a
        ``MIMEText("html")`` email part.
    """
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
                <td style="padding:8px 14px;font-size:9px;letter-spacing:.12em;color:#4a6080;text-transform:uppercase;">Vorhergesagt</td>
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
    """Send an HTML email via SMTP.

    Connects to the configured SMTP server and sends a ``multipart/alternative``
    email with an HTML part. TLS/authentication is only attempted when
    ``SMTP_USER`` is non-empty, allowing the function to work with both
    authenticated SMTP relays (production) and unauthenticated catch-all
    servers like MailHog (development).

    Args:
        to_email: Recipient email address.
        subject: Email subject line.
        html_body: Complete HTML email body as returned by ``build_email_html()``.

    Raises:
        smtplib.SMTPException: When the SMTP server rejects the connection,
            authentication fails, or the message cannot be sent.
        OSError: When the SMTP server host is unreachable.

    Side effects:
        Logs a confirmation message at INFO level including the recipient and
        subject on successful delivery.
    """
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
    """Airflow task entry point for the warning notification step.

    Loads all active user warnings from the database, evaluates each against
    the daily forecast for the next 7 days, and sends HTML email notifications
    for new threshold breaches. Notifications are deduplicated via the
    ``warning_notifications`` table.

    Processing flow for each (warning, forecast_date) pair:
      1. Check temporal validity via ``is_valid()``.
      2. Skip if a notification record already exists for this pair.
      3. Fetch the daily forecast row for the warning's city and date.
      4. Evaluate all conditions via ``evaluate_conditions()`` (AND logic).
      5. If triggered: send email, insert a notification record, commit.

    Each successful email is committed individually (not in a batch) so that
    a failure on one email does not prevent notifications for other warnings.

    This function is registered as a ``PythonOperator`` callable in
    ``airflow/dags/check_weather_warnings.py``.

    Args:
        **context: Airflow task context dict (not used directly in this
                   implementation; included for ``PythonOperator`` compatibility).

    Returns:
        A summary dict::

            {"sent": <int>, "skipped": <int>, "errors": <int>}

        - ``sent``: number of emails sent in this run.
        - ``skipped``: number of (warning, date) pairs skipped because a
          notification was already sent.
        - ``errors``: number of email delivery failures.
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
