from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, model_validator

from backend.app.models.geo import GeoLevel


class Normalization(str, Enum):
    percentile = "percentile"
    minmax = "minmax"
    zscore = "zscore"


class MissingMetricPolicy(str, Enum):
    renormalize = "renormalize"
    zero = "zero"
    exclude_market = "exclude_market"


class PillarConfig(BaseModel):
    label: str
    weight: float = Field(ge=0)
    description: str | None = None


class ScoreConfig(BaseModel):
    """A complete, self-contained SERVE MD Score definition. Saved configs are versioned by `id`+`version`."""

    id: str
    name: str
    description: str | None = None
    version: int = 1
    normalization: Normalization = Normalization.percentile
    missing_metric_policy: MissingMetricPolicy = MissingMetricPolicy.renormalize
    min_coverage_pct: float = Field(default=60, ge=0, le=100)
    pillars: dict[str, PillarConfig]
    metric_weights: dict[str, float] = Field(
        default_factory=dict,
        description="metric_id -> weight within its pillar; omitted metrics use metrics.yaml scoring_default",
    )
    direction_overrides: dict[str, bool] = Field(
        default_factory=dict, description="metric_id -> higher_is_better override"
    )
    created_at: datetime | None = None

    @model_validator(mode="after")
    def _weights_positive(self) -> ScoreConfig:
        if not self.pillars:
            raise ValueError("at least one pillar is required")
        if sum(p.weight for p in self.pillars.values()) <= 0:
            raise ValueError("pillar weights must sum to a positive number")
        for mid, w in self.metric_weights.items():
            if w < 0:
                raise ValueError(f"metric weight for {mid} must be >= 0")
        return self


class MetricContribution(BaseModel):
    metric_id: str
    label: str
    pillar: str
    raw_value: float | None
    normalized: float | None = Field(description="0-100 after direction is applied")
    weight: float = Field(
        description="effective weight of this metric in the composite (sums to 1 across metrics)"
    )
    contribution: float = Field(description="normalized * weight, in composite points")


class PillarScore(BaseModel):
    pillar: str
    label: str
    score: float | None = Field(ge=0, le=100)
    weight: float
    coverage_pct: float = Field(description="share of the pillar's metric weight backed by non-null data")


class MarketScore(BaseModel):
    geo_level: GeoLevel
    geo_id: str
    name: str
    state_abbr: str | None = None
    score: float | None = Field(ge=0, le=100)
    rank: int | None = None
    rank_of: int | None = None
    coverage_pct: float
    low_confidence: bool
    pillar_scores: list[PillarScore]
    contributions: list[MetricContribution] = Field(default_factory=list)
    config_id: str
    config_version: int


class ScoreExplainRequest(BaseModel):
    geo_level: GeoLevel
    geo_id: str
    config: ScoreConfig | None = Field(
        default=None, description="Ad-hoc config; if omitted the saved config_id is used"
    )
    config_id: str | None = None
