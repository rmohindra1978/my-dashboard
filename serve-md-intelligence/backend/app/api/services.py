"""Application services shared by routers: market profiles, score-config persistence, scenario persistence."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import duckdb
import pandas as pd
from fastapi import HTTPException

from backend.app.data import repository
from backend.app.engines.scoring import explain_market, score_frame
from backend.app.models.financial import FinancialAssumptions, FinancialScenario
from backend.app.models.geo import GeoLevel, GeoUnit
from backend.app.models.market import MarketProfile
from backend.app.models.metrics import MetricReading, PillarPanel
from backend.app.models.scoring import MarketScore, ScoreConfig
from backend.app.registry import load_default_score_config, load_metric_registry


# ---------------------------------------------------------------- score configs
def list_score_configs(con: duckdb.DuckDBPyConnection) -> list[ScoreConfig]:
    rows = con.execute(
        """
        SELECT config FROM app_score_configs a
        WHERE version = (SELECT max(version) FROM app_score_configs b WHERE b.id = a.id)
        ORDER BY id
        """
    ).fetchall()
    saved = [ScoreConfig(**json.loads(r[0])) for r in rows]
    if not any(c.id == "default" for c in saved):
        saved.insert(0, load_default_score_config())
    return saved


def get_score_config(
    con: duckdb.DuckDBPyConnection, config_id: str, version: int | None = None
) -> ScoreConfig:
    if version is None:
        row = con.execute(
            "SELECT config FROM app_score_configs WHERE id=? ORDER BY version DESC LIMIT 1", [config_id]
        ).fetchone()
    else:
        row = con.execute(
            "SELECT config FROM app_score_configs WHERE id=? AND version=?", [config_id, version]
        ).fetchone()
    if row:
        return ScoreConfig(**json.loads(row[0]))
    if config_id == "default":
        return load_default_score_config()
    raise HTTPException(404, f"score config '{config_id}' not found")


def save_score_config(con: duckdb.DuckDBPyConnection, config: ScoreConfig) -> ScoreConfig:
    """Saving never overwrites: each save creates version = max(version)+1 for that id."""
    registry = load_metric_registry()
    known = {m.id for m in registry.metrics}
    unknown = set(config.metric_weights) - known
    if unknown:
        raise HTTPException(422, f"unknown metric ids in metric_weights: {sorted(unknown)}")
    row = con.execute(
        "SELECT coalesce(max(version), 0) FROM app_score_configs WHERE id=?", [config.id]
    ).fetchone()
    new = config.model_copy(update={"version": int(row[0]) + 1, "created_at": datetime.now(timezone.utc)})
    con.execute(
        "INSERT INTO app_score_configs (id, version, name, config) VALUES (?, ?, ?, ?)",
        [new.id, new.version, new.name, new.model_dump_json()],
    )
    return new


def resolve_config(
    con: duckdb.DuckDBPyConnection, config: ScoreConfig | None, config_id: str | None
) -> ScoreConfig:
    if config is not None:
        return config
    return get_score_config(con, config_id or "default")


# ---------------------------------------------------------------- market profile
def _fmt_panels(
    con: duckdb.DuckDBPyConnection, unit: GeoUnit, peers: pd.DataFrame, config: ScoreConfig
) -> list[PillarPanel]:
    registry = load_metric_registry()
    values = {v.metric_id: v for v in repository.latest_metric_values(con, unit.geo_level, unit.geo_id)}
    panels: list[PillarPanel] = []
    for pillar_id, pcfg in config.pillars.items():
        readings: list[MetricReading] = []
        for m in registry.for_pillar(pillar_id):
            if unit.geo_level not in m.geo_levels:
                continue
            v = values.get(m.id)
            pct = None
            if v is not None and v.value is not None and m.id in peers.columns:
                col = pd.to_numeric(peers[m.id], errors="coerce").dropna()
                if len(col) > 1:
                    pct = float((col < v.value).mean() * 100.0)
            readings.append(
                MetricReading(
                    metric_id=m.id,
                    label=m.label,
                    value=None if v is None else v.value,
                    unit=m.unit,
                    format=m.format,
                    period=None if v is None else v.period,
                    source_id=m.source,
                    source_name=registry.sources[m.source].name,
                    higher_is_better=m.higher_is_better,
                    percentile=pct,
                )
            )
        panels.append(PillarPanel(pillar=pillar_id, label=pcfg.label, metrics=readings))
    return panels


def market_profile(
    con: duckdb.DuckDBPyConnection, level: GeoLevel, geo_id: str, config: ScoreConfig
) -> MarketProfile:
    unit = repository.get_geo_unit(con, level, geo_id)
    if unit is None:
        raise HTTPException(404, f"{level.value} '{geo_id}' not found")
    peers = repository.features_frame(
        con,
        level,
        [unit.state_abbr] if level in (GeoLevel.zcta, GeoLevel.place) and unit.state_abbr else None,
    )
    score: MarketScore | None = None
    if not peers.empty:
        scored = score_frame(peers, config)
        score = explain_market(scored, level, geo_id, config)

    parent = None
    related: list[GeoUnit] = []
    if level in (GeoLevel.zcta, GeoLevel.place):
        xw = repository.crosswalk(con, level, geo_id, GeoLevel.county)
        if not xw.empty:
            parent = repository.get_geo_unit(con, GeoLevel.county, str(xw.iloc[0]["to_id"]))
    elif level == GeoLevel.county:
        related = repository.children(con, GeoLevel.county, geo_id, GeoLevel.zcta)
    return MarketProfile(
        geo=unit,
        panels=_fmt_panels(con, unit, peers, config),
        score=score,
        parent_county=parent,
        related=related,
        data_vintages=repository.source_vintages(con),
    )


# ---------------------------------------------------------------- financial scenarios
def list_scenarios(con: duckdb.DuckDBPyConnection) -> list[FinancialScenario]:
    rows = con.execute(
        "SELECT id, name, geo_level, geo_id, assumptions, created_at, updated_at "
        "FROM app_financial_scenarios ORDER BY updated_at DESC"
    ).fetchall()
    return [
        FinancialScenario(
            id=r[0],
            name=r[1],
            geo_level=r[2],
            geo_id=r[3],
            assumptions=FinancialAssumptions(**json.loads(r[4])),
            created_at=r[5],
            updated_at=r[6],
        )
        for r in rows
    ]


def get_scenario(con: duckdb.DuckDBPyConnection, scenario_id: str) -> FinancialScenario:
    row = con.execute(
        "SELECT id, name, geo_level, geo_id, assumptions, created_at, updated_at "
        "FROM app_financial_scenarios WHERE id=?",
        [scenario_id],
    ).fetchone()
    if not row:
        raise HTTPException(404, f"scenario '{scenario_id}' not found")
    return FinancialScenario(
        id=row[0],
        name=row[1],
        geo_level=row[2],
        geo_id=row[3],
        assumptions=FinancialAssumptions(**json.loads(row[4])),
        created_at=row[5],
        updated_at=row[6],
    )


def save_scenario(con: duckdb.DuckDBPyConnection, scenario: FinancialScenario) -> FinancialScenario:
    now = datetime.now(timezone.utc)
    con.execute(
        """
        INSERT INTO app_financial_scenarios (id, name, geo_level, geo_id, assumptions, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (id) DO UPDATE SET
            name=excluded.name, geo_level=excluded.geo_level, geo_id=excluded.geo_id,
            assumptions=excluded.assumptions, updated_at=excluded.updated_at
        """,
        [
            scenario.id,
            scenario.name,
            scenario.geo_level.value if scenario.geo_level else None,
            scenario.geo_id,
            scenario.assumptions.model_dump_json(),
            now,
            now,
        ],
    )
    return get_scenario(con, scenario.id)


def delete_scenario(con: duckdb.DuckDBPyConnection, scenario_id: str) -> None:
    con.execute("DELETE FROM app_financial_scenarios WHERE id=?", [scenario_id])
