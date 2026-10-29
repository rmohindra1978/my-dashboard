"""Cross-source derived metrics, computed in the warehouse after the source loads.

Each derived metric divides a numerator metric by a denominator taken from another source (or from
geo_units.land_area_sqmi). Inputs use their latest period; the output period is the numerator's period and
the output source_id is the metric's registered source. Missing inputs simply produce no rows.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import duckdb

from backend.app.registry import load_metric_registry

log = logging.getLogger("pipelines.derived")


@dataclass(frozen=True)
class Ratio:
    metric_id: str
    numerator: str
    denominator: str  # metric id, or "land_area_sqmi" for the geo_units column
    scale: float


DERIVED: tuple[Ratio, ...] = (
    Ratio("pop_density", "pop_total", "land_area_sqmi", 1.0),
    Ratio("pcp_per_1000_65plus", "pcp_count", "pop_65_plus", 1000.0),
    Ratio("pcp_per_10k_pop", "pcp_count", "pop_total", 10000.0),
)

_LATEST = """
    SELECT geo_level, geo_id, period, value FROM (
        SELECT geo_level, geo_id, period, value,
               row_number() OVER (PARTITION BY geo_level, geo_id ORDER BY period DESC) AS rn
        FROM metric_values WHERE metric_id = ? AND value IS NOT NULL
    ) WHERE rn = 1
"""


def compute_derived_metrics(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Upsert every DERIVED metric for each geo level where both inputs exist. Returns rows per metric."""
    registry = {m.id: m for m in load_metric_registry().metrics}
    counts: dict[str, int] = {}
    for r in DERIVED:
        meta = registry[r.metric_id]
        levels = [lv.value if hasattr(lv, "value") else str(lv) for lv in meta.geo_levels]
        if r.denominator == "land_area_sqmi":
            den_sql, den_params = (
                "SELECT geo_level, geo_id, land_area_sqmi AS value FROM geo_units WHERE land_area_sqmi > 0",
                [],
            )
        else:
            den_sql, den_params = _LATEST, [r.denominator]
        placeholders = ",".join("?" for _ in levels)
        sql = f"""
            INSERT OR REPLACE INTO metric_values (geo_level, geo_id, metric_id, period, value, source_id)
            SELECT n.geo_level, n.geo_id, ?, n.period, n.value / d.value * ?, ?
            FROM ({_LATEST}) n
            JOIN ({den_sql}) d USING (geo_level, geo_id)
            WHERE d.value > 0 AND n.geo_level IN ({placeholders})
        """
        before = con.execute(
            "SELECT count(*) FROM metric_values WHERE metric_id = ?", [r.metric_id]
        ).fetchone()[0]
        con.execute(sql, [r.metric_id, r.scale, meta.source, r.numerator, *den_params, *levels])
        after = con.execute(
            "SELECT count(*) FROM metric_values WHERE metric_id = ?", [r.metric_id]
        ).fetchone()[0]
        counts[r.metric_id] = after
        log.info("derived %s: %d rows (%+d)", r.metric_id, after, after - before)
    return counts
