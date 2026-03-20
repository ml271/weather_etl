"""
User-Defined Weather Warnings Router – CRUD for ``/warnings/``
==============================================================

Allows authenticated users to create, read, update, and delete their own
weather warning rules. These rules are evaluated by the Airflow
``check_weather_warnings`` DAG every 2 hours, which sends an HTML email
notification when all conditions in a rule are simultaneously satisfied by the
daily forecast for the configured city.

Warning ownership:
  All endpoints (except ``GET /warnings/templates``) require a valid JWT via
  the ``get_current_user`` dependency. Each user can only read and modify their
  own warnings; attempting to access another user's warning returns 404 (not
  403) to avoid leaking information about the existence of other users' data.

Templates:
  ``GET /warnings/templates`` is public and returns the pre-seeded quick-start
  templates from the ``warning_templates`` table. The frontend uses these to
  populate the "Add warning" form with sensible defaults.

JSONB serialisation:
  ``conditions`` and ``validity`` are stored as JSONB in the database. On
  write they are serialised from the validated Pydantic models; on read they
  are returned as raw Python objects (list / dict) via the ``Any``-typed
  ``WarningOut`` fields.

Dependencies:
  sqlalchemy, routers.auth (for ``get_current_user``)

Author: <project maintainer>
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from database import get_db
from models import Warning, WarningTemplate
from schemas import WarningCreate, WarningOut, WarningTemplateOut
from routers.auth import get_current_user
from models import User

router = APIRouter(prefix="/warnings", tags=["Warnings"])


# ── Templates ────────────────────────────────────────────────────────────────

@router.get("/templates", response_model=list[WarningTemplateOut])
def get_templates(db: Session = Depends(get_db)):
    """Return all predefined warning templates.

    Templates are read-only and available to all users (no authentication
    required). They are seeded at database initialisation time via
    ``docker/init.sql`` and serve as starting points for creating custom
    warnings.

    Args:
        db: SQLAlchemy session injected by FastAPI's dependency system.

    Returns:
        A list of ``WarningTemplateOut`` objects ordered by ``id`` ascending.
        Each object contains a ``conditions`` list ready to be cloned into a
        new warning.
    """
    return db.query(WarningTemplate).order_by(WarningTemplate.id).all()


# ── User Warnings ─────────────────────────────────────────────────────────────

@router.get("/", response_model=list[WarningOut])
def list_warnings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return all warnings belonging to the authenticated user.

    Args:
        current_user: The authenticated user, resolved by ``get_current_user``.
        db: SQLAlchemy session injected by FastAPI's dependency system.

    Returns:
        A list of ``WarningOut`` objects for the current user, ordered by
        ``created_at`` descending (newest first).
    """
    return (
        db.query(Warning)
        .filter(Warning.user_id == current_user.id)
        .order_by(Warning.created_at.desc())
        .all()
    )


@router.post("/", response_model=WarningOut, status_code=201)
def create_warning(
    body: WarningCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new weather warning for the authenticated user.

    Serialises ``conditions`` (list of ``ConditionRule``) and ``validity``
    (``ValiditySpec``) from the validated Pydantic model to plain Python
    dicts before storing them as JSONB. This ensures clean round-trip
    serialisation without Pydantic metadata.

    Args:
        body: Warning definition including ``city``, ``name``, ``conditions``,
              and ``validity``.
        current_user: The authenticated user, resolved by ``get_current_user``.
        db: SQLAlchemy session injected by FastAPI's dependency system.

    Returns:
        The newly created warning as a ``WarningOut`` object with its assigned
        database ID and timestamps.
    """
    warning = Warning(
        user_id       = current_user.id,
        station_id    = body.station_id,
        city          = body.city,
        name          = body.name,
        # Dump Pydantic models to plain dicts for JSONB storage
        conditions    = [c.model_dump() for c in body.conditions],
        validity      = body.validity.model_dump(),
        notify_timing = body.notify_timing or "as_available",
    )
    db.add(warning)
    db.commit()
    db.refresh(warning)
    return warning


@router.get("/{warning_id}", response_model=WarningOut)
def get_warning(
    warning_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return a single warning by ID, scoped to the authenticated user.

    Args:
        warning_id: Database primary key of the warning to retrieve.
        current_user: The authenticated user, resolved by ``get_current_user``.
        db: SQLAlchemy session injected by FastAPI's dependency system.

    Returns:
        The requested warning as a ``WarningOut`` object.

    Raises:
        HTTPException(404): When the warning does not exist or belongs to a
            different user. A 404 is returned instead of 403 to avoid
            disclosing the existence of other users' warnings.
    """
    w = db.get(Warning, warning_id)
    if not w or w.user_id != current_user.id:
        raise HTTPException(404, "Warning not found")
    return w


@router.put("/{warning_id}", response_model=WarningOut)
def update_warning(
    warning_id: int,
    body: WarningCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Replace all fields of an existing warning (full update / PUT semantics).

    All warning fields are replaced with the values from ``body``. The
    ``updated_at`` column is refreshed automatically by the SQLAlchemy
    ``onupdate`` trigger defined in the ``Warning`` model.

    Args:
        warning_id: Database primary key of the warning to update.
        body: New warning definition. All fields are required (PUT semantics;
              partial updates are not supported).
        current_user: The authenticated user, resolved by ``get_current_user``.
        db: SQLAlchemy session injected by FastAPI's dependency system.

    Returns:
        The updated warning as a ``WarningOut`` object.

    Raises:
        HTTPException(404): When the warning does not exist or belongs to a
            different user.
    """
    w = db.get(Warning, warning_id)
    if not w or w.user_id != current_user.id:
        raise HTTPException(404, "Warning not found")
    w.station_id    = body.station_id
    w.city          = body.city
    w.name          = body.name
    w.conditions    = [c.model_dump() for c in body.conditions]
    w.validity      = body.validity.model_dump()
    w.notify_timing = body.notify_timing or "as_available"
    db.commit()
    db.refresh(w)
    return w


@router.delete("/{warning_id}", status_code=204)
def delete_warning(
    warning_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Permanently delete a warning.

    The corresponding ``warning_notifications`` rows are cascade-deleted by
    the foreign-key constraint defined in the database schema, so no manual
    cleanup is needed.

    Args:
        warning_id: Database primary key of the warning to delete.
        current_user: The authenticated user, resolved by ``get_current_user``.
        db: SQLAlchemy session injected by FastAPI's dependency system.

    Returns:
        HTTP 204 No Content on success (no response body).

    Raises:
        HTTPException(404): When the warning does not exist or belongs to a
            different user.
    """
    w = db.get(Warning, warning_id)
    if not w or w.user_id != current_user.id:
        raise HTTPException(404, "Warning not found")
    db.delete(w)
    db.commit()


# ── Triggered Warnings ────────────────────────────────────────────────────────

@router.get("/triggered")
def get_triggered_warnings(
    city: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the user's warnings that have been triggered for a city.

    Joins ``warning_notifications`` with ``warnings`` and ``weather_daily`` to
    return each triggered warning together with the actual forecast values that
    caused the trigger. Only warnings belonging to the authenticated user and
    matching the given city are returned.

    Results are ordered by ``forecast_date`` descending so the most imminent
    triggers appear first.

    Args:
        city: Filter results to this city.
        current_user: The authenticated user.
        db: SQLAlchemy session.

    Returns:
        A list of dicts with keys: ``warning_id``, ``name``, ``city``,
        ``forecast_date``, ``conditions`` (list of condition dicts with an
        added ``actual_value`` key showing the forecast value for that day).
    """
    rows = db.execute(text("""
        SELECT
            w.id            AS warning_id,
            w.name          AS name,
            w.city          AS city,
            wn.forecast_date AS forecast_date,
            w.conditions    AS conditions,
            d.temperature_max, d.temperature_min, d.precipitation_sum,
            d.snowfall_sum, d.wind_speed_10m_max, d.wind_gusts_10m_max,
            d.uv_index_max
        FROM warning_notifications wn
        JOIN warnings w  ON w.id  = wn.warning_id
        JOIN weather_daily d ON d.city = w.city AND d.forecast_date = wn.forecast_date
        WHERE w.user_id = :user_id
          AND w.city    = :city
          AND wn.forecast_date >= CURRENT_DATE
        ORDER BY wn.forecast_date ASC
    """), {"user_id": current_user.id, "city": city}).mappings().all()

    result = []
    for row in rows:
        daily_vals = {
            "temperature_max":    row["temperature_max"],
            "temperature_min":    row["temperature_min"],
            "precipitation_sum":  row["precipitation_sum"],
            "snowfall_sum":       row["snowfall_sum"],
            "wind_speed_10m_max": row["wind_speed_10m_max"],
            "wind_gusts_10m_max": row["wind_gusts_10m_max"],
            "uv_index_max":       row["uv_index_max"],
        }
        enriched_conditions = []
        for cond in (row["conditions"] or []):
            param = cond.get("parameter", "")
            actual = daily_vals.get(param)
            enriched_conditions.append({**cond, "actual_value": actual})

        result.append({
            "warning_id":    row["warning_id"],
            "name":          row["name"],
            "city":          row["city"],
            "forecast_date": str(row["forecast_date"]),
            "conditions":    enriched_conditions,
        })
    return result
