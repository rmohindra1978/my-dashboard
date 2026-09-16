from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from backend.app.models.geo import GeoLevel
from backend.app.models.scoring import MarketScore, ScoreConfig


class FilterOp(str, Enum):
    gte = "gte"
    lte = "lte"
    eq = "eq"
    between = "between"


class MetricFilter(BaseModel):
    metric_id: str
    op: FilterOp
    value: float | None = None
    low: float | None = None
    high: float | None = None


class RankingRequest(BaseModel):
    geo_level: GeoLevel = GeoLevel.county
    config_id: str | None = Field(
        default="default", description="saved config to use when `config` is omitted"
    )
    config: ScoreConfig | None = None
    states: list[str] | None = Field(default=None, description="2-letter state codes; None = all")
    filters: list[MetricFilter] = Field(default_factory=list)
    limit: int = Field(default=100, ge=1, le=50000)
    offset: int = Field(default=0, ge=0)
    include_contributions: bool = False
    sort_by: str = Field(default="score", description="'score', a pillar id, or a metric_id")
    descending: bool = True


class RankingRow(MarketScore):
    metrics: dict[str, float | None] = Field(
        default_factory=dict, description="key raw metrics for the table view"
    )


class RankingResponse(BaseModel):
    total: int
    geo_level: GeoLevel
    config_id: str
    config_version: int
    rows: list[RankingRow]
    computed_in_ms: float
