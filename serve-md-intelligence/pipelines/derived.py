"""Cross-source derived metrics, computed in the warehouse after every load.

Each entry is `metric = numerator / denominator * scale` for every geo level the registry lists for the
metric where both inputs exist (latest non-null period of each). The output period is the numerator's
period and the row's source_id is the metric's registry source. Missing inputs simply yield no rows.
"""

from __future__ import annotations

import logging

import duckdb
import pandas as pd

from backend.app.registry import load_metric_registry
from pipelines.base import upsert_metric_values

log = logging.getLogger("pipelines.derived")

LAND_AREA = "geo_units.land_area_sqmi"

# metric_id -> (numerator metric, denominator metric or LAND_AREA, scale)
DERIVED: dict[str, tuple[str, str, float]] = {
    "pop_density": ("pop_total", LAND_AREA, 1.0),
    "pcp_per_1000_65plus": ("pcp_count", "pop_65_plus", 1000.0),
    "pcp_per_10k_pop": ("pcp_count", "pop_total", 10000.0),
}

_LATEST = """
    SELECT geo_level, geo_id, period, value FROM (
        SELECT geo_level, geo_id, period, value,
               row_number() OVER (PARTITION BY geo_level, geo_id ORDER BY period DESC) AS rn
        FROM metric_values WHERE metric_id = ? AND value IS NOT NULL
    ) WHERE rn = 1
"""


def compute_derived_metrics(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    registry = {m.id: m for m in load_metric_registry().metrics}
    results: dict[str, int] = {}
    for metric_id, (num, den, scale) in DERIVED.items():
        meta = registry[metric_id]
        levels = [level.value for level in meta.geo_levels]
        if den == LAND_AREA:
            den_sql = "SELECT geo_level, geo_id, land_area_sqmi AS value FROM geo_units"
            params: list = [num]
        else:
            den_sql = _LATEST
            params = [num, den]
        placeholders = ",".join("?" for _ in levels)
        df: pd.DataFrame = con.execute(
            f"""
            WITH n AS ({_LATEST}), d AS ({den_sql})
            SELECT n.geo_level, n.geo_id, ? AS metric_id, n.period,
                   CASE WHEN d.value > 0 THEN n.value / d.value * ? END AS value
            FROM n JOIN d ON d.geo_level = n.geo_level AND d.geo_id = n.geo_id
            WHERE n.geo_level IN ({placeholders})
            """,
            [*params, metric_id, scale, *levels],
        ).df()
        results[metric_id] = upsert_metric_values(con, df, meta.source)
        log.info("derived %s: %d rows", metric_id, results[metric_id])
    return results
