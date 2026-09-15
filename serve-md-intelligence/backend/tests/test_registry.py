from __future__ import annotations

from backend.app.registry import (
    effective_direction,
    effective_metric_weights,
    load_default_financial_assumptions,
    load_default_score_config,
    load_metric_registry,
)


def test_registry_loads_and_is_consistent():
    reg = load_metric_registry()
    assert len(reg.metrics) >= 40
    assert set(m.source for m in reg.metrics) <= set(reg.sources)
    pillars = set(load_default_score_config().pillars)
    assert all(m.pillar in pillars for m in reg.metrics)
    for p in pillars:
        assert any(m.pillar == p and m.scoring_default > 0 for m in reg.scorable()), (
            f"pillar {p} has no scorable metric"
        )


def test_default_weights_and_overrides():
    cfg = load_default_score_config()
    w = effective_metric_weights(cfg)
    assert w["pct_65_plus"] > 0
    assert "pop_total" in w and w["pop_total"] == 0  # informational-but-scorable metric defaults to 0 weight
    cfg2 = cfg.model_copy(
        update={"metric_weights": {"pct_65_plus": 0}, "direction_overrides": {"pct_65_plus": False}}
    )
    assert effective_metric_weights(cfg2)["pct_65_plus"] == 0
    assert effective_direction(cfg2)["pct_65_plus"] is False
    assert effective_direction(cfg)["pcp_per_1000_65plus"] is False  # more competition = worse


def test_financial_defaults_load():
    a = load_default_financial_assumptions()
    assert a.model_years == 5
    assert a.payer_mix.ffs_pct + a.payer_mix.ma_pct == 100
