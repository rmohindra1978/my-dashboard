from __future__ import annotations

from pydantic import BaseModel, Field

from backend.app.models.geo import GeoLevel


class SourceDef(BaseModel):
    id: str
    name: str
    publisher: str
    url: str
    vintage: str
    geo_levels: list[GeoLevel]
    notes: str | None = None


class MetricDef(BaseModel):
    id: str
    label: str
    description: str
    pillar: str
    unit: str
    format: str = "decimal2"
    higher_is_better: bool | None
    geo_levels: list[GeoLevel]
    source: str
    derivation: str
    scoring_default: float = Field(ge=0, default=0)


class MetricRegistry(BaseModel):
    sources: dict[str, SourceDef]
    metrics: list[MetricDef]

    def by_id(self) -> dict[str, MetricDef]:
        return {m.id: m for m in self.metrics}

    def for_pillar(self, pillar: str) -> list[MetricDef]:
        return [m for m in self.metrics if m.pillar == pillar]

    def scorable(self) -> list[MetricDef]:
        return [m for m in self.metrics if m.higher_is_better is not None]


class MetricValue(BaseModel):
    """One observation of one metric for one geography. This mirrors the `metric_values` table."""

    geo_level: GeoLevel
    geo_id: str
    metric_id: str
    period: str = Field(description="Vintage / period label, e.g. '2023', '2019-2023', '2026-05'")
    value: float | None
    source_id: str


class MetricReading(BaseModel):
    """A metric as displayed on a market profile: value plus registry metadata."""

    metric_id: str
    label: str
    value: float | None
    unit: str
    format: str
    period: str | None = None
    source_id: str
    source_name: str
    higher_is_better: bool | None
    percentile: float | None = Field(default=None, description="0-100 rank among peers at the same geo level")


class PillarPanel(BaseModel):
    pillar: str
    label: str
    metrics: list[MetricReading]
