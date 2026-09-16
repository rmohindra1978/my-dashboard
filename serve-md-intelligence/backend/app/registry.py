"""Loads the YAML configuration files into typed models. Cached per process; call `reload()` in tests."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from backend.app.models.financial import FinancialAssumptions
from backend.app.models.metrics import MetricRegistry
from backend.app.models.scoring import ScoreConfig
from backend.app.settings import settings


def _read_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@lru_cache(maxsize=1)
def load_metric_registry(path: Path | None = None) -> MetricRegistry:
    raw = _read_yaml(path or settings.metrics_file)
    sources = {sid: {"id": sid, **sdef} for sid, sdef in raw.get("sources", {}).items()}
    registry = MetricRegistry(sources=sources, metrics=raw.get("metrics", []))
    _validate_registry(registry)
    return registry


def _validate_registry(registry: MetricRegistry) -> None:
    ids = [m.id for m in registry.metrics]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate metric ids in metrics.yaml: {sorted(dupes)}")
    unknown_sources = {m.source for m in registry.metrics} - set(registry.sources)
    if unknown_sources:
        raise ValueError(f"metrics reference unknown sources: {sorted(unknown_sources)}")
    pillars = set(load_default_score_config().pillars)
    unknown_pillars = {m.pillar for m in registry.metrics} - pillars
    if unknown_pillars:
        raise ValueError(f"metrics reference unknown pillars: {sorted(unknown_pillars)}")


@lru_cache(maxsize=1)
def load_default_score_config(path: Path | None = None) -> ScoreConfig:
    return ScoreConfig(**_read_yaml(path or settings.scoring_default_file))


@lru_cache(maxsize=1)
def load_default_financial_assumptions(path: Path | None = None) -> FinancialAssumptions:
    return FinancialAssumptions(**_read_yaml(path or settings.financial_default_file))


def effective_metric_weights(config: ScoreConfig, registry: MetricRegistry | None = None) -> dict[str, float]:
    """metric_id -> weight within pillar, applying config overrides on top of registry defaults.
    Informational metrics (higher_is_better is None) are never scored."""
    registry = registry or load_metric_registry()
    weights: dict[str, float] = {}
    for m in registry.scorable():
        if m.pillar not in config.pillars:
            continue
        weights[m.id] = float(config.metric_weights.get(m.id, m.scoring_default))
    return weights


def effective_direction(config: ScoreConfig, registry: MetricRegistry | None = None) -> dict[str, bool]:
    registry = registry or load_metric_registry()
    return {m.id: config.direction_overrides.get(m.id, bool(m.higher_is_better)) for m in registry.scorable()}


def reload() -> None:
    load_metric_registry.cache_clear()
    load_default_score_config.cache_clear()
    load_default_financial_assumptions.cache_clear()
