from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.app.data import repository
from backend.app.engines.scoring import explain_market, score_frame
from backend.app.engines.scoring.engine import normalize
from backend.app.models.geo import GeoLevel
from backend.app.models.scoring import MissingMetricPolicy, Normalization, PillarConfig, ScoreConfig


def test_normalize_percentile_direction_and_nan():
    s = pd.Series([10.0, 20.0, np.nan, 40.0])
    up = normalize(s, Normalization.percentile, True)
    down = normalize(s, Normalization.percentile, False)
    assert up.iloc[3] == 100.0 and up.iloc[0] < up.iloc[1]
    assert np.isnan(up.iloc[2]) and np.isnan(down.iloc[2])
    assert down.iloc[3] == 0.0


@pytest.mark.parametrize("method", list(Normalization))
def test_normalize_bounds(method):
    s = pd.Series(np.linspace(-5, 500, 200))
    out = normalize(s, method, True)
    assert out.min() >= 0 and out.max() <= 100


def test_scores_all_counties_in_range(con, score_config):
    scored = score_frame(repository.features_frame(con, GeoLevel.county), score_config)
    assert len(scored) == 12
    assert scored["score"].between(0, 100).all()
    assert scored["coverage_pct"].between(0, 100).all()
    assert sorted(scored["rank"].astype(int)) == list(range(1, 13))
    for p in score_config.pillars:
        assert f"pillar__{p}" in scored.columns


def test_pillar_weight_change_moves_scores(con, score_config):
    f = repository.features_frame(con, GeoLevel.county)
    base = score_frame(f, score_config).set_index("geo_id")["score"]
    heavy = score_config.model_copy(deep=True)
    for p in heavy.pillars.values():
        p.weight = 0
    heavy.pillars["health_need"].weight = 100
    alt = score_frame(f, heavy).set_index("geo_id")
    assert not np.allclose(base.values, alt["score"].values)
    assert np.allclose(alt["score"].values, alt["pillar__health_need"].values, equal_nan=True)


def test_metric_weight_zero_removes_contribution(con, score_config):
    f = repository.features_frame(con, GeoLevel.county)
    cfg = score_config.model_copy(deep=True)
    cfg.metric_weights = {"pct_65_plus": 0}
    scored = score_frame(f, cfg)
    ms = explain_market(scored, GeoLevel.county, "04013", cfg)
    assert ms is not None
    assert all(c.metric_id != "pct_65_plus" for c in ms.contributions)
    assert abs(sum(c.contribution for c in ms.contributions) - ms.score) < 1e-6


def test_missing_metric_policies():
    f = pd.DataFrame(
        {
            "geo_id": ["a", "b", "c"],
            "name": list("abc"),
            "state_abbr": ["XX"] * 3,
            "pct_65_plus": [10.0, 20.0, 30.0],
            "medicare_benes_total": [np.nan, 50.0, 100.0],
        }
    )
    cfg = ScoreConfig(
        id="t",
        name="t",
        pillars={
            "demographics_growth": PillarConfig(label="d", weight=50),
            "medicare_demand": PillarConfig(label="m", weight=50),
        },
        metric_weights={"pct_65_plus": 1, "medicare_benes_total": 1},
    )
    # zero out every other default weight so only our two metrics count
    from backend.app.registry import load_metric_registry

    for m in load_metric_registry().scorable():
        cfg.metric_weights.setdefault(m.id, 0)

    ren = score_frame(f, cfg.model_copy(update={"missing_metric_policy": MissingMetricPolicy.renormalize}))
    assert ren.loc[0, "coverage_pct"] == 50.0 and ren.loc[0, "low_confidence"]
    assert not np.isnan(ren.loc[0, "score"])
    zero = score_frame(f, cfg.model_copy(update={"missing_metric_policy": MissingMetricPolicy.zero}))
    assert zero.loc[0, "score"] < ren.loc[0, "score"]
    exc = score_frame(f, cfg.model_copy(update={"missing_metric_policy": MissingMetricPolicy.exclude_market}))
    assert np.isnan(exc.loc[0, "score"]) and not np.isnan(exc.loc[1, "score"])


def test_explain_market_structure(con, score_config):
    scored = score_frame(repository.features_frame(con, GeoLevel.county), score_config)
    ms = explain_market(scored, GeoLevel.county, "04013", score_config)
    assert ms is not None and ms.name == "Maricopa County" and ms.rank_of == 12
    assert len(ms.pillar_scores) == 5
    assert abs(sum(p.weight for p in ms.pillar_scores) - 1) < 1e-9
    assert explain_market(scored, GeoLevel.county, "99999", score_config) is None
