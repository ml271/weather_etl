"""
Stations Router – GET /stations/search?q=
Durchsucht die stations-Tabelle nach Name oder Region (case-insensitiv).
"""
from typing import Optional
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from database import get_db
from models import Station

router = APIRouter(prefix="/stations", tags=["Stations"])


class StationSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    station_id: int
    name:       str
    region:     Optional[str] = None
    country:    Optional[str] = None
    lat:        Decimal
    lon:        Decimal

    @classmethod
    def from_orm_station(cls, s: Station) -> "StationSchema":
        return cls(
            station_id=s.id,
            name=s.name,
            region=s.region,
            country=s.country,
            lat=s.lat,
            lon=s.lon,
        )


@router.get("/search", response_model=list[StationSchema])
def search_stations(
    q: str = Query(default="", description="Suchbegriff: Stadtname oder Bundesland"),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    Sucht Stationen nach Name oder Region.
    - Leerer Suchbegriff → Top-`limit` Stationen alphabetisch.
    - Kurze Suche (< 2 Zeichen) → Prefix-Match auf Name.
    - Sonst → ILIKE-Suche auf Name UND Region.
    """
    q = q.strip()

    query = db.query(Station)

    if q:
        pattern = f"%{q}%"
        query = query.filter(
            Station.name.ilike(pattern) | Station.region.ilike(pattern)
        )

    stations = query.order_by(Station.name).limit(limit).all()
    return [StationSchema.from_orm_station(s) for s in stations]
