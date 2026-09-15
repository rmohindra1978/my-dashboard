"""Expansion ranking engine: score + filter + sort every market at a geo level.

Designed for thousands of markets per call: one warehouse read, one vectorised scoring pass, pandas filtering.
"""

from __future__ import annotations

import time

import duckdb
import pandas as pd

from backend.app.data import repository
from backend.app.engines.scoring.engine import explain_market, score_frame
from backend.app.models.metrics import MetricRegistry
from backend.app.models.ranking import FilterOp, MetricFilter, RankingRequest, RankingResponse, RankingRow
from backend.app.models.scoring import ScoreConfig
from backend.app.registry import load_metric_registry

TABLE_METRICS = [
    "pop_65_plus",
    "pct_65_plus",
    "pop_65_plus_growth_5yr",
    "medicare_benes_total",
    "ma_penetration_pct",
    "dual_eligible_pct",
    "avg_hcc_risk_score",
    "pcp_per_1000_65plus",
    "hpsa_score_max",
    "diabetes_prevalence",
    "median_household_income",
    "median_gross_rent",
]


def apply_filters(df: pd.DataFrame, filters: list[MetricFilter]) -> pd.DataFrame:
    for f in filters:
        if f.metric_id not in df.columns:
            df = df.iloc[0:0]
            break
        col = pd.to_numeric(df[f.metric_id], errors="coerce")
        if f.op == FilterOp.gte:
            df = df[col >= f.value]
        elif f.op == FilterOp.lte:
            df = df[col <= f.value]
        elif f.op == FilterOp.eq:
            df = df[col == f.value]
        elif f.op == FilterOp.between:
            df = df[(col >= f.low) & (col <= f.high)]
    return df


def rank_markets(
    con: duckdb.DuckDBPyConnection,
    req: RankingRequest,
    config: ScoreConfig,
    registry: MetricRegistry | None = None,
) -> RankingResponse:
    t0 = time.perf_counter()
    registry = registry or load_metric_registry()
    features = repository.features_frame(con, req.geo_level, req.states)
    scored = score_frame(features, config, registry)
    filtered = apply_filters(scored, req.filters)

    sort_col = req.sort_by
    if sort_col in config.pillars:
        sort_col = f"pillar__{sort_col}"
    if sort_col not in filtered.columns:
        sort_col = "score"
    filtered = filtered.sort_values(sort_col, ascending=not req.descending, na_position="last")
    filtered = filtered.reset_index(drop=True)
    filtered["rank"] = filtered.index + 1  # rank within the filtered universe

    total = int(len(filtered))
    page = filtered.iloc[req.offset : req.offset + req.limit]
    rows: list[RankingRow] = []
    for _, r in page.iterrows():
        ms = explain_market(page, req.geo_level, str(r["geo_id"]), config, registry)
        if ms is None:
            continue
        ms.rank, ms.rank_of = int(r["rank"]), total
        if not req.include_contributions:
            ms.contributions = []
        metrics = {m: (None if pd.isna(r[m]) else float(r[m])) for m in TABLE_METRICS if m in page.columns}
        rows.append(RankingRow(**ms.model_dump(), metrics=metrics))

    return RankingResponse(
        total=total,
        geo_level=req.geo_level,
        config_id=config.id,
        config_version=config.version,
        rows=rows,
        computed_in_ms=(time.perf_counter() - t0) * 1000.0,
    )
