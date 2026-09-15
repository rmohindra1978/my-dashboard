from __future__ import annotations

from pydantic import BaseModel, Field

from backend.app.models.geo import GeoUnit
from backend.app.models.metrics import PillarPanel
from backend.app.models.scoring import MarketScore


class MarketProfile(BaseModel):
    """Everything the dashboard shows for one searched market."""

    geo: GeoUnit
    panels: list[PillarPanel]
    score: MarketScore | None = None
    parent_county: GeoUnit | None = Field(
        default=None, description="For ZCTA / place lookups: the dominant county"
    )
    related: list[GeoUnit] = Field(
        default_factory=list, description="ZCTAs within a county, counties within a place, etc."
    )
    data_vintages: dict[str, str] = Field(default_factory=dict, description="source_id -> vintage label")
