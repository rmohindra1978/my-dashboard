"""Read-side data access for the API and engines. All SQL against the warehouse lives here."""

from __future__ import annotations

import re

import duckdb
import pandas as pd

from backend.app.models.geo import GeoLevel, GeoUnit, SearchResult
from backend.app.models.metrics import MetricValue

_ZIP_RE = re.compile(r"^\d{5}$")
_FIPS_RE = re.compile(r"^\d{5}$")


def _row_to_geo(row: tuple) -> GeoUnit:
    return GeoUnit(
        geo_level=row[0], geo_id=row[1], name=row[2], state_fips=row[3], state_abbr=row[4],
        lat=row[5], lon=row[6], land_area_sqmi=row[7], cbsa_code=row[8], cbsa_name=row[9],
    )


GEO_COLS = "geo_level, geo_id, name, state_fips, state_abbr, lat, lon, land_area_sqmi, cbsa_code, cbsa_name"


def get_geo_unit(con: duckdb.DuckDBPyConnection, level: GeoLevel, geo_id: str) -> GeoUnit | None:
    row = con.execute(
        f"SELECT {GEO_COLS} FROM geo_units WHERE geo_level = ? AND geo_id = ?", [level.value, geo_id]
    ).fetchone()
    return _row_to_geo(row) if row else None


def display_name(unit: GeoUnit) -> str:
    if unit.geo_level == GeoLevel.zcta:
        return f"ZIP {unit.geo_id}" + (f" ({unit.name})" if unit.name and unit.name != unit.geo_id else "")
    if unit.geo_level == GeoLevel.state:
        return unit.name
    return f"{unit.name}, {unit.state_abbr}" if unit.state_abbr else unit.name


def search(con: duckdb.DuckDBPyConnection, query: str, limit: int = 10) -> list[SearchResult]:
    """Resolve free text to markets. Exact ZIP / county FIPS first, then name matches ranked by level and prefix."""
    q = query.strip()
    if not q:
        return []
    results: list[SearchResult] = []
    if _ZIP_RE.match(q):
        for level in (GeoLevel.zcta, GeoLevel.county):
            unit = get_geo_unit(con, level, q)
            if unit:
                results.append(SearchResult(geo_level=unit.geo_level, geo_id=unit.geo_id, name=unit.name,
                                            state_abbr=unit.state_abbr, display=display_name(unit)))
        if results:
            return results[:limit]

    # "Maricopa County, AZ" / "Phoenix, AZ" -> split off state
    name_part, state_part = q, None
    m = re.match(r"^(.*?)[,\s]+([A-Za-z]{2})$", q)
    if m:
        name_part, state_part = m.group(1).strip(), m.group(2).upper()
    like = f"%{name_part.lower()}%"
    prefix = f"{name_part.lower()}%"
    params: list = [like, prefix]
    state_sql = ""
    if state_part:
        state_sql = "AND state_abbr = ?"
        params.append(state_part)
    params.append(limit)
    rows = con.execute(
        f"""
        SELECT {GEO_COLS},
               CASE geo_level WHEN 'place' THEN 0 WHEN 'county' THEN 1 WHEN 'state' THEN 2 ELSE 3 END AS lvl_rank,
               CASE WHEN lower(name) LIKE ? THEN 0 ELSE 1 END AS prefix_rank
        FROM geo_units
        WHERE lower(name) LIKE ? {state_sql}
        ORDER BY prefix_rank, lvl_rank, length(name), name
        LIMIT ?
        """,
        [prefix, like, *params[2:]],
    ).fetchall()
    for row in rows:
        unit = _row_to_geo(row[:10])
        score = 1.0 if row[11] == 0 else 0.7
        results.append(SearchResult(geo_level=unit.geo_level, geo_id=unit.geo_id, name=unit.name,
                                    state_abbr=unit.state_abbr, display=display_name(unit), match_score=score))
    return results


def latest_metric_values(con: duckdb.DuckDBPyConnection, level: GeoLevel, geo_id: str) -> list[MetricValue]:
    rows = con.execute(
        """
        SELECT geo_level, geo_id, metric_id, period, value, source_id
        FROM (
            SELECT *, row_number() OVER (PARTITION BY metric_id ORDER BY period DESC) AS rn
            FROM metric_values WHERE geo_level = ? AND geo_id = ?
        ) WHERE rn = 1
        """,
        [level.value, geo_id],
    ).fetchall()
    return [MetricValue(geo_level=r[0], geo_id=r[1], metric_id=r[2], period=r[3], value=r[4], source_id=r[5])
            for r in rows]


def metric_history(con: duckdb.DuckDBPyConnection, level: GeoLevel, geo_id: str, metric_id: str) -> pd.DataFrame:
    return con.execute(
        "SELECT period, value FROM metric_values WHERE geo_level=? AND geo_id=? AND metric_id=? ORDER BY period",
        [level.value, geo_id, metric_id],
    ).df()


def features_frame(con: duckdb.DuckDBPyConnection, level: GeoLevel, states: list[str] | None = None) -> pd.DataFrame:
    """Wide frame: one row per market at `level` with geo metadata + every metric column present in the warehouse."""
    state_sql, params = "", [level.value]
    if states:
        placeholders = ",".join("?" for _ in states)
        state_sql = f"AND g.state_abbr IN ({placeholders})"
        params.extend(s.upper() for s in states)
    return con.execute(
        f"""
        SELECT g.geo_id, g.name, g.state_abbr, g.lat, g.lon, f.* EXCLUDE (geo_level, geo_id)
        FROM geo_units g
        LEFT JOIN market_features f ON f.geo_level = g.geo_level AND f.geo_id = g.geo_id
        WHERE g.geo_level = ? {state_sql}
        """,
        params,
    ).df()


def crosswalk(con: duckdb.DuckDBPyConnection, from_level: GeoLevel, from_id: str, to_level: GeoLevel) -> pd.DataFrame:
    return con.execute(
        """
        SELECT to_id, weight FROM geo_crosswalk
        WHERE from_level=? AND from_id=? AND to_level=? ORDER BY weight DESC
        """,
        [from_level.value, from_id, to_level.value],
    ).df()


def children(con: duckdb.DuckDBPyConnection, parent_level: GeoLevel, parent_id: str, child_level: GeoLevel,
             min_weight: float = 0.05) -> list[GeoUnit]:
    rows = con.execute(
        f"""
        SELECT {", ".join("g." + c.strip() for c in GEO_COLS.split(","))}
        FROM geo_crosswalk x JOIN geo_units g ON g.geo_level = x.from_level AND g.geo_id = x.from_id
        WHERE x.to_level=? AND x.to_id=? AND x.from_level=? AND x.weight >= ?
        ORDER BY x.weight DESC
        """,
        [parent_level.value, parent_id, child_level.value, min_weight],
    ).fetchall()
    return [_row_to_geo(r) for r in rows]


def source_vintages(con: duckdb.DuckDBPyConnection) -> dict[str, str]:
    rows = con.execute(
        "SELECT source_id, max(vintage) FROM pipeline_runs WHERE status='ok' GROUP BY source_id"
    ).fetchall()
    return {r[0]: r[1] for r in rows if r[1]}
