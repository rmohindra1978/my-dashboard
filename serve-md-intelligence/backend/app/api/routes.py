"""HTTP surface. Thin: validation via Pydantic, logic in engines/services."""

from __future__ import annotations

import io
import json

import duckdb
import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

from backend.app.api import services
from backend.app.api.deps import Auth, Con
from backend.app.data import repository
from backend.app.engines.financial import run_model, run_sensitivity
from backend.app.engines.ranking import rank_markets
from backend.app.engines.scoring import score_frame
from backend.app.models.financial import (
    FinancialAssumptions,
    FinancialResult,
    FinancialScenario,
    SensitivityRequest,
    SensitivityResponse,
)
from backend.app.models.geo import GeoLevel, SearchResult
from backend.app.models.market import MarketProfile
from backend.app.models.metrics import MetricRegistry
from backend.app.models.ranking import RankingRequest, RankingResponse
from backend.app.models.scoring import MarketScore, ScoreConfig, ScoreExplainRequest
from backend.app.registry import load_default_financial_assumptions, load_metric_registry

router = APIRouter(prefix="/api", dependencies=[Auth])


class Health(BaseModel):
    status: str
    geo_units: int
    metric_rows: int
    sources_loaded: dict[str, str]


@router.get("/health", response_model=Health)
def health(con: duckdb.DuckDBPyConnection = Con) -> Health:
    geo = con.execute("SELECT count(*) FROM geo_units").fetchone()[0]
    mv = con.execute("SELECT count(*) FROM metric_values").fetchone()[0]
    return Health(status="ok", geo_units=geo, metric_rows=mv, sources_loaded=repository.source_vintages(con))


# ---------------------------------------------------------------- metadata
@router.get("/meta/metrics", response_model=MetricRegistry)
def metrics_registry() -> MetricRegistry:
    return load_metric_registry()


@router.get("/meta/states")
def states(con: duckdb.DuckDBPyConnection = Con) -> list[dict]:
    rows = con.execute(
        "SELECT geo_id, name, state_abbr FROM geo_units WHERE geo_level='state' ORDER BY name"
    ).fetchall()
    return [{"fips": r[0], "name": r[1], "abbr": r[2]} for r in rows]


# ---------------------------------------------------------------- search & profile
@router.get("/search", response_model=list[SearchResult])
def search(
    q: str = Query(min_length=1), limit: int = Query(default=10, le=50), con: duckdb.DuckDBPyConnection = Con
) -> list[SearchResult]:
    return repository.search(con, q, limit)


@router.get("/markets/{level}/{geo_id}", response_model=MarketProfile)
def market(
    level: GeoLevel, geo_id: str, config_id: str = "default", con: duckdb.DuckDBPyConnection = Con
) -> MarketProfile:
    return services.market_profile(con, level, geo_id, services.get_score_config(con, config_id))


@router.get("/markets/{level}/{geo_id}/history/{metric_id}")
def history(level: GeoLevel, geo_id: str, metric_id: str, con: duckdb.DuckDBPyConnection = Con) -> list[dict]:
    df = repository.metric_history(con, level, geo_id, metric_id)
    return [
        {"period": r.period, "value": None if pd.isna(r.value) else float(r.value)} for r in df.itertuples()
    ]


# ---------------------------------------------------------------- scoring
@router.get("/score/configs", response_model=list[ScoreConfig])
def score_configs(con: duckdb.DuckDBPyConnection = Con) -> list[ScoreConfig]:
    return services.list_score_configs(con)


@router.get("/score/configs/{config_id}", response_model=ScoreConfig)
def score_config(
    config_id: str, version: int | None = None, con: duckdb.DuckDBPyConnection = Con
) -> ScoreConfig:
    return services.get_score_config(con, config_id, version)


@router.post("/score/configs", response_model=ScoreConfig, status_code=201)
def save_score_config(config: ScoreConfig, con: duckdb.DuckDBPyConnection = Con) -> ScoreConfig:
    return services.save_score_config(con, config)


@router.post("/score/explain", response_model=MarketScore)
def explain(req: ScoreExplainRequest, con: duckdb.DuckDBPyConnection = Con) -> MarketScore:
    cfg = services.resolve_config(con, req.config, req.config_id)
    profile = services.market_profile(con, req.geo_level, req.geo_id, cfg)
    if profile.score is None:
        raise HTTPException(404, "no metric data for this market")
    return profile.score


# ---------------------------------------------------------------- ranking
@router.post("/rank", response_model=RankingResponse)
def rank(req: RankingRequest, con: duckdb.DuckDBPyConnection = Con) -> RankingResponse:
    cfg = services.resolve_config(con, req.config, req.config_id)
    return rank_markets(con, req, cfg)


@router.post("/rank/export.csv")
def rank_csv(req: RankingRequest, con: duckdb.DuckDBPyConnection = Con) -> Response:
    cfg = services.resolve_config(con, req.config, req.config_id)
    req = req.model_copy(update={"limit": 50000, "offset": 0, "include_contributions": False})
    res = rank_markets(con, req, cfg)
    rows = []
    for r in res.rows:
        row = {
            "rank": r.rank,
            "geo_id": r.geo_id,
            "name": r.name,
            "state": r.state_abbr,
            "score": r.score,
            "coverage_pct": r.coverage_pct,
            "low_confidence": r.low_confidence,
        }
        row.update({f"pillar_{p.pillar}": p.score for p in r.pillar_scores})
        row.update(r.metrics)
        rows.append(row)
    buf = io.StringIO()
    pd.DataFrame(rows).to_csv(buf, index=False)
    return Response(
        buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=servemd_rankings_{req.geo_level.value}.csv"},
    )


# ---------------------------------------------------------------- map
class MapRequest(BaseModel):
    config: ScoreConfig | None = None
    config_id: str | None = None
    states: list[str] | None = None


def _clean(v: object) -> object:
    if not isinstance(v, str) and pd.isna(v):
        return None
    return v.item() if hasattr(v, "item") else v


def _build_map_layer(
    con: duckdb.DuckDBPyConnection, level: GeoLevel, cfg: ScoreConfig, state_list: list[str] | None
) -> Response:
    scored = score_frame(repository.features_frame(con, level, state_list), cfg)
    props = scored.set_index("geo_id")
    rows = con.execute(
        "SELECT geo_id, geojson::VARCHAR FROM geo_boundaries WHERE geo_level=?", [level.value]
    ).fetchall()
    keep = [
        "name",
        "state_abbr",
        "score",
        "rank",
        "coverage_pct",
        "low_confidence",
        *[c for c in props.columns if c.startswith("pillar__")],
        "pop_65_plus",
        "pct_65_plus",
        "medicare_benes_total",
        "ma_penetration_pct",
        "pcp_per_1000_65plus",
    ]

    def attrs_for(geo_id: str, p: pd.Series) -> dict[str, object]:
        attrs: dict[str, object] = {"geo_id": geo_id, "geo_level": level.value}
        for k in keep:
            if k in p.index:
                attrs[k] = _clean(p[k])
        return attrs

    features = []
    for geo_id, geom in rows:
        if geo_id not in props.index:
            continue
        features.append(
            {
                "type": "Feature",
                "id": geo_id,
                "geometry": json.loads(geom),
                "properties": attrs_for(geo_id, props.loc[geo_id]),
            }
        )
    if not features:
        # no boundaries loaded: fall back to point features from centroids so the map still works
        for geo_id, p in props.iterrows():
            if pd.isna(p.get("lat")) or pd.isna(p.get("lon")):
                continue
            features.append(
                {
                    "type": "Feature",
                    "id": geo_id,
                    "geometry": {"type": "Point", "coordinates": [float(p["lon"]), float(p["lat"])]},
                    "properties": attrs_for(str(geo_id), p),
                }
            )
    return Response(
        json.dumps({"type": "FeatureCollection", "features": features}), media_type="application/geo+json"
    )


@router.get("/map/{level}")
def map_layer(
    level: GeoLevel,
    config_id: str = "default",
    states: str | None = None,
    con: duckdb.DuckDBPyConnection = Con,
) -> Response:
    """GeoJSON FeatureCollection with score/pillars/key metrics in each feature's properties."""
    cfg = services.get_score_config(con, config_id)
    state_list = [s.strip().upper() for s in states.split(",")] if states else None
    return _build_map_layer(con, level, cfg, state_list)


@router.post("/map/{level}")
def map_layer_adhoc(level: GeoLevel, req: MapRequest, con: duckdb.DuckDBPyConnection = Con) -> Response:
    """Same as GET but scores with an unsaved (ad hoc) config posted in the body."""
    cfg = req.config or services.get_score_config(con, req.config_id or "default")
    state_list = [s.strip().upper() for s in req.states] if req.states else None
    return _build_map_layer(con, level, cfg, state_list)


# ---------------------------------------------------------------- financial
@router.get("/financial/defaults", response_model=FinancialAssumptions)
def financial_defaults() -> FinancialAssumptions:
    return load_default_financial_assumptions()


@router.post("/financial/run", response_model=FinancialResult)
def financial_run(assumptions: FinancialAssumptions, include_monthly: bool = True) -> FinancialResult:
    return run_model(assumptions, include_monthly=include_monthly)


@router.post("/financial/sensitivity", response_model=SensitivityResponse)
def financial_sensitivity(req: SensitivityRequest) -> SensitivityResponse:
    try:
        return run_sensitivity(req)
    except (KeyError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/financial/scenarios", response_model=list[FinancialScenario])
def scenarios(con: duckdb.DuckDBPyConnection = Con) -> list[FinancialScenario]:
    return services.list_scenarios(con)


@router.get("/financial/scenarios/{scenario_id}", response_model=FinancialScenario)
def scenario(scenario_id: str, con: duckdb.DuckDBPyConnection = Con) -> FinancialScenario:
    return services.get_scenario(con, scenario_id)


@router.put("/financial/scenarios/{scenario_id}", response_model=FinancialScenario)
def put_scenario(
    scenario_id: str, scenario: FinancialScenario, con: duckdb.DuckDBPyConnection = Con
) -> FinancialScenario:
    return services.save_scenario(con, scenario.model_copy(update={"id": scenario_id}))


@router.delete("/financial/scenarios/{scenario_id}", status_code=204)
def delete_scenario(scenario_id: str, con: duckdb.DuckDBPyConnection = Con) -> Response:
    services.delete_scenario(con, scenario_id)
    return Response(status_code=204)
