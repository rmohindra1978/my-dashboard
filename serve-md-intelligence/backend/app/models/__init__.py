"""Pydantic contracts shared by the API, the engines, the pipelines and (via OpenAPI) the frontend."""

from backend.app.models.financial import (
    AnnualSummary,
    FinancialAssumptions,
    FinancialResult,
    FinancialScenario,
    MonthlyLine,
    SensitivityRequest,
    SensitivityResponse,
)
from backend.app.models.geo import CrosswalkEntry, GeoLevel, GeoUnit, SearchResult
from backend.app.models.market import MarketProfile
from backend.app.models.metrics import (
    MetricDef,
    MetricReading,
    MetricRegistry,
    MetricValue,
    PillarPanel,
    SourceDef,
)
from backend.app.models.ranking import FilterOp, MetricFilter, RankingRequest, RankingResponse, RankingRow
from backend.app.models.scoring import (
    MarketScore,
    MetricContribution,
    MissingMetricPolicy,
    Normalization,
    PillarConfig,
    PillarScore,
    ScoreConfig,
    ScoreExplainRequest,
)

__all__ = [
    "AnnualSummary",
    "CrosswalkEntry",
    "FilterOp",
    "FinancialAssumptions",
    "FinancialResult",
    "FinancialScenario",
    "GeoLevel",
    "GeoUnit",
    "MarketProfile",
    "MarketScore",
    "MetricContribution",
    "MetricDef",
    "MetricFilter",
    "MetricReading",
    "MetricRegistry",
    "MetricValue",
    "MissingMetricPolicy",
    "MonthlyLine",
    "Normalization",
    "PillarConfig",
    "PillarPanel",
    "PillarScore",
    "RankingRequest",
    "RankingResponse",
    "RankingRow",
    "ScoreConfig",
    "ScoreExplainRequest",
    "SearchResult",
    "SensitivityRequest",
    "SensitivityResponse",
    "SourceDef",
]
