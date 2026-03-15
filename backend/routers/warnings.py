"""
Warnings Router – User-defined weather warnings / alerts
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Warning, WarningTemplate
from schemas import WarningCreate, WarningOut, WarningTemplateOut
from routers.auth import get_current_user
from models import User

router = APIRouter(prefix="/warnings", tags=["Warnings"])


# ── Templates ────────────────────────────────────────────────────────────────

@router.get("/templates", response_model=list[WarningTemplateOut])
def get_templates(db: Session = Depends(get_db)):
    return db.query(WarningTemplate).order_by(WarningTemplate.id).all()


# ── User warnings ─────────────────────────────────────────────────────────────

@router.get("/", response_model=list[WarningOut])
def list_warnings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
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
    warning = Warning(
        user_id    = current_user.id,
        station_id = body.station_id,
        city       = body.city,
        name       = body.name,
        conditions = [c.model_dump() for c in body.conditions],
        validity   = body.validity.model_dump(),
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
    w = db.get(Warning, warning_id)
    if not w or w.user_id != current_user.id:
        raise HTTPException(404, "Warning not found")
    w.station_id = body.station_id
    w.city       = body.city
    w.name       = body.name
    w.conditions = [c.model_dump() for c in body.conditions]
    w.validity   = body.validity.model_dump()
    db.commit()
    db.refresh(w)
    return w


@router.delete("/{warning_id}", status_code=204)
def delete_warning(
    warning_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    w = db.get(Warning, warning_id)
    if not w or w.user_id != current_user.id:
        raise HTTPException(404, "Warning not found")
    db.delete(w)
    db.commit()
