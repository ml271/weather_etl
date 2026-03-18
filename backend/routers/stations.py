"""
Stations Router – City / Location Search Autocomplete
======================================================

Provides a single search endpoint that allows the frontend to find weather
stations (cities) by name or region. The result list is used to populate the
city search autocomplete widget in the dashboard header.

When the user selects a city from the search results, its ``lat`` and ``lon``
coordinates are appended to the dashboard URL as query parameters
(``?city=München&lat=48.135&lon=11.582``). Those coordinates are then passed
to ``POST /weather/fetch-now`` if the city has no data yet.

The ``stations`` table is pre-seeded in ``docker/init.sql`` with ~75 German,
Austrian, and Swiss cities. Additional stations can be inserted manually.

Search behaviour:
  - Empty query (``q=""``): returns the first ``limit`` stations in alphabetical order.
  - Any non-empty query: performs a case-insensitive ILIKE match on both ``name``
    and ``region`` (e.g. querying "Bayern" returns all Bavarian cities).

Dependencies:
  sqlalchemy, pydantic >= 2.0

Author: <project maintainer>
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
    """Serialised representation of a ``Station`` ORM row for API responses.

    Note: The field is named ``station_id`` (not ``id``) to avoid collision
    with Pydantic's internal ``model_id`` field and to make the client-side
    JSON more self-describing.

    Attributes:
        station_id: Database primary key of the station.
        name: City or station name (e.g. "München").
        region: Administrative region / Bundesland (e.g. "Bayern"). May be
            ``None`` for non-German entries.
        country: Country name (e.g. "Germany", "Austria", "Switzerland").
        lat: Geographic latitude in decimal degrees (WGS-84).
        lon: Geographic longitude in decimal degrees (WGS-84).
    """
    model_config = ConfigDict(from_attributes=True)

    station_id: int
    name:       str
    region:     Optional[str] = None
    country:    Optional[str] = None
    lat:        Decimal
    lon:        Decimal

    @classmethod
    def from_orm_station(cls, s: Station) -> "StationSchema":
        """Construct a ``StationSchema`` from a ``Station`` ORM instance.

        Maps the ORM ``id`` field to the schema's ``station_id`` field, since
        the ORM model uses ``id`` as the primary key name.

        Args:
            s: A ``Station`` ORM instance loaded from the database.

        Returns:
            A fully populated ``StationSchema`` instance.
        """
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
    """Search the station registry by city name or region.

    Performs a case-insensitive substring match (SQL ``ILIKE``) on both the
    ``name`` and ``region`` columns. An empty search term returns all stations
    up to ``limit``, ordered alphabetically by name.

    Args:
        q: Search string. Matched as ``%q%`` against both ``name`` and
           ``region``. An empty string returns all stations (up to ``limit``).
        limit: Maximum number of stations to return. Must be between 1 and 100
               inclusive (default: 20).
        db: SQLAlchemy session injected by FastAPI's dependency system.

    Returns:
        A list of up to ``limit`` ``StationSchema`` objects ordered by
        ``name`` ascending.

    Example:
        ``GET /stations/search?q=frei`` returns stations including "Freiburg".
        ``GET /stations/search?q=Bayern`` returns all stations in Bavaria.
        ``GET /stations/search`` returns the first 20 stations alphabetically.
    """
    q = q.strip()

    query = db.query(Station)

    if q:
        # Match the search term anywhere in name OR region (case-insensitive)
        pattern = f"%{q}%"
        query = query.filter(
            Station.name.ilike(pattern) | Station.region.ilike(pattern)
        )

    stations = query.order_by(Station.name).limit(limit).all()
    return [StationSchema.from_orm_station(s) for s in stations]
