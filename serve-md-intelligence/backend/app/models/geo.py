from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class GeoLevel(str, Enum):
    state = "state"
    county = "county"
    zcta = "zcta"
    place = "place"


class GeoUnit(BaseModel):
    """A geographic market unit. `geo_id` conventions:
    state -> 2-digit FIPS, county -> 5-digit FIPS, zcta -> 5-digit ZCTA, place -> 7-digit state+place FIPS.
    """

    geo_level: GeoLevel
    geo_id: str
    name: str
    state_fips: str | None = None
    state_abbr: str | None = None
    lat: float | None = None
    lon: float | None = None
    land_area_sqmi: float | None = None
    cbsa_code: str | None = None
    cbsa_name: str | None = None


class SearchResult(BaseModel):
    geo_level: GeoLevel
    geo_id: str
    name: str
    state_abbr: str | None = None
    display: str = Field(description="Human label, e.g. 'Maricopa County, AZ' or 'ZIP 85004 (Phoenix, AZ)'")
    match_score: float = Field(ge=0, le=1, default=1.0)


class CrosswalkEntry(BaseModel):
    from_level: GeoLevel
    from_id: str
    to_level: GeoLevel
    to_id: str
    weight: float = Field(ge=0, le=1, description="Population share of `from` that falls in `to`")
