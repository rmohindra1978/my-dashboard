"""SERVE MD Score engine.

Pipeline:  raw metric  ->  normalize (0-100, direction applied)  ->  pillar score  ->  composite (0-100)

All weights, directions and the normalization method come from a `ScoreConfig`; metric metadata comes from
the metric registry. The engine is fully vectorised over a wide features frame (one row per market) so
re-scoring every US county after a weight change is a sub-second operation.

Column conventions on the returned frame:
    norm__<metric_id>     normalized 0-100 value (direction applied)
    pillar__<pillar_id>   pillar score 0-100 (NaN if no data)
    score                 composite 0-100
    coverage_pct          share of total effective weight backed by data
    low_confidence        coverage_pct < config.min_coverage_pct
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backend.app.models.geo import GeoLevel
from backend.app.models.metrics import MetricRegistry
from backend.app.models.scoring import (
    MarketScore,
    MetricContribution,
    MissingMetricPolicy,
    Normalization,
    PillarScore,
    ScoreConfig,
)
from backend.app.registry import effective_direction, effective_metric_weights, load_metric_registry


def normalize(series: pd.Series, method: Normalization, higher_is_better: bool) -> pd.Series:
    """Map a raw metric to 0-100 across all markets in `series`. NaN stays NaN."""
    s = pd.to_numeric(series, errors="coerce").astype(float)
    valid = s.dropna()
    if valid.empty:
        return pd.Series(np.nan, index=s.index, dtype=float)
    if method == Normalization.percentile:
        out = s.rank(pct=True, method="average") * 100.0
    elif method == Normalization.minmax:
        lo, hi = valid.quantile(0.02), valid.quantile(0.98)
        out = ((s.clip(lo, hi) - lo) / (hi - lo) * 100.0) if hi > lo else pd.Series(50.0, index=s.index)
    elif method == Normalization.zscore:
        sd = valid.std(ddof=0)
        z = ((s - valid.mean()) / sd).clip(-3, 3) if sd > 0 else pd.Series(0.0, index=s.index)
        out = (z + 3) / 6 * 100.0
    else:  # pragma: no cover - enum exhaustiveness
        raise ValueError(f"unknown normalization {method}")
    out = out.where(s.notna())
    return out if higher_is_better else 100.0 - out


def _weighted_mean(
    values: pd.DataFrame, weights: dict[str, float], policy: MissingMetricPolicy
) -> tuple[pd.Series, pd.Series]:
    """Row-wise weighted mean over `values[cols]` handling NaN per `policy`. Returns (score, coverage 0-1)."""
    cols = [c for c in weights if c in values.columns and weights[c] > 0]
    if not cols:
        idx = values.index
        return pd.Series(np.nan, index=idx), pd.Series(0.0, index=idx)
    w = np.array([weights[c] for c in cols], dtype=float)
    mat = values[cols].to_numpy(dtype=float)
    present = ~np.isnan(mat)
    total_w = w.sum()
    avail_w = (present * w).sum(axis=1)
    coverage = avail_w / total_w
    if policy == MissingMetricPolicy.zero:
        score = np.nansum(mat * w, axis=1) / total_w
    else:
        with np.errstate(invalid="ignore", divide="ignore"):
            score = np.nansum(mat * w, axis=1) / avail_w
        score = np.where(avail_w > 0, score, np.nan)
        if policy == MissingMetricPolicy.exclude_market:
            score = np.where(present.all(axis=1), score, np.nan)
    return pd.Series(score, index=values.index), pd.Series(coverage, index=values.index)


def score_frame(
    features: pd.DataFrame, config: ScoreConfig, registry: MetricRegistry | None = None
) -> pd.DataFrame:
    """Score every row of `features` (wide frame from repository.features_frame).

    Returns a copy with score columns added."""
    registry = registry or load_metric_registry()
    weights = effective_metric_weights(config, registry)
    directions = effective_direction(config, registry)
    out = features.copy()

    norm_cols: dict[str, str] = {}
    for metric_id, w in weights.items():
        if w <= 0 or metric_id not in out.columns:
            continue
        col = f"norm__{metric_id}"
        out[col] = normalize(out[metric_id], config.normalization, directions[metric_id])
        norm_cols[metric_id] = col

    metric_defs = registry.by_id()
    pillar_cov: dict[str, pd.Series] = {}
    for pillar_id in config.pillars:
        pw = {norm_cols[m]: weights[m] for m in norm_cols if metric_defs[m].pillar == pillar_id}
        score, cov = _weighted_mean(out, pw, config.missing_metric_policy)
        out[f"pillar__{pillar_id}"] = score
        pillar_cov[pillar_id] = cov

    pillar_weights = {f"pillar__{p}": cfg.weight for p, cfg in config.pillars.items()}
    composite, _ = _weighted_mean(out, pillar_weights, config.missing_metric_policy)
    out["score"] = composite.clip(0, 100)

    total_pw = sum(cfg.weight for cfg in config.pillars.values())
    coverage = sum(pillar_cov[p] * cfg.weight for p, cfg in config.pillars.items()) / total_pw * 100.0
    out["coverage_pct"] = coverage.astype(float)
    out["low_confidence"] = out["coverage_pct"] < config.min_coverage_pct
    out["rank"] = out["score"].rank(ascending=False, method="min")
    return out


def explain_market(
    scored: pd.DataFrame,
    geo_level: GeoLevel,
    geo_id: str,
    config: ScoreConfig,
    registry: MetricRegistry | None = None,
) -> MarketScore | None:
    """Build the per-market breakdown (pillar scores + metric contributions) from a scored frame."""
    registry = registry or load_metric_registry()
    rows = scored[scored["geo_id"] == geo_id]
    if rows.empty:
        return None
    row = rows.iloc[0]
    weights = effective_metric_weights(config, registry)
    defs = registry.by_id()
    total_pw = sum(c.weight for c in config.pillars.values())

    pillar_scores: list[PillarScore] = []
    contributions: list[MetricContribution] = []
    for pillar_id, pcfg in config.pillars.items():
        p_metrics = [
            m
            for m in weights
            if defs[m].pillar == pillar_id and weights[m] > 0 and f"norm__{m}" in scored.columns
        ]
        total_mw = sum(weights[m] for m in p_metrics)
        avail_mw = sum(weights[m] for m in p_metrics if pd.notna(row.get(f"norm__{m}")))
        pscore = row.get(f"pillar__{pillar_id}")
        pillar_scores.append(
            PillarScore(
                pillar=pillar_id,
                label=pcfg.label,
                score=None if pd.isna(pscore) else float(pscore),
                weight=pcfg.weight / total_pw,
                coverage_pct=(avail_mw / total_mw * 100.0) if total_mw else 0.0,
            )
        )
        for m in p_metrics:
            norm = row.get(f"norm__{m}")
            raw = row.get(m)
            denom = avail_mw if config.missing_metric_policy == MissingMetricPolicy.renormalize else total_mw
            eff_w = (weights[m] / denom) * (pcfg.weight / total_pw) if denom and pd.notna(norm) else 0.0
            contributions.append(
                MetricContribution(
                    metric_id=m,
                    label=defs[m].label,
                    pillar=pillar_id,
                    raw_value=None if pd.isna(raw) else float(raw),
                    normalized=None if pd.isna(norm) else float(norm),
                    weight=eff_w,
                    contribution=float(norm) * eff_w if pd.notna(norm) else 0.0,
                )
            )

    score = row["score"]
    return MarketScore(
        geo_level=geo_level,
        geo_id=geo_id,
        name=str(row["name"]),
        state_abbr=row.get("state_abbr"),
        score=None if pd.isna(score) else float(score),
        rank=None if pd.isna(row["rank"]) else int(row["rank"]),
        rank_of=int(scored["score"].notna().sum()),
        coverage_pct=float(row["coverage_pct"]),
        low_confidence=bool(row["low_confidence"]),
        pillar_scores=pillar_scores,
        contributions=contributions,
        config_id=config.id,
        config_version=config.version,
    )
