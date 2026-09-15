"""DuckDB warehouse: schema definition and a thin connection helper.

Tables
  geo_units        one row per market unit at every geo level
  geo_crosswalk    weighted many-to-many mapping between geo levels (ZCTA->county, place->county, ...)
  metric_values    tidy/long observations; every dataset lands here (extensible without schema changes)
  market_features  wide, latest-period pivot of metric_values used by the scoring & ranking engines
  geo_boundaries   GeoJSON geometry per unit (counties by default)
  app_score_configs / app_financial_scenarios / app_saved_markets   user-editable application state
  pipeline_runs    provenance of each source load
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import duckdb

from backend.app.settings import settings

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS geo_units (
    geo_level       VARCHAR NOT NULL,
    geo_id          VARCHAR NOT NULL,
    name            VARCHAR NOT NULL,
    state_fips      VARCHAR,
    state_abbr      VARCHAR,
    lat             DOUBLE,
    lon             DOUBLE,
    land_area_sqmi  DOUBLE,
    cbsa_code       VARCHAR,
    cbsa_name       VARCHAR,
    PRIMARY KEY (geo_level, geo_id)
);

CREATE TABLE IF NOT EXISTS geo_crosswalk (
    from_level  VARCHAR NOT NULL,
    from_id     VARCHAR NOT NULL,
    to_level    VARCHAR NOT NULL,
    to_id       VARCHAR NOT NULL,
    weight      DOUBLE NOT NULL,
    PRIMARY KEY (from_level, from_id, to_level, to_id)
);

CREATE TABLE IF NOT EXISTS metric_values (
    geo_level   VARCHAR NOT NULL,
    geo_id      VARCHAR NOT NULL,
    metric_id   VARCHAR NOT NULL,
    period      VARCHAR NOT NULL,
    value       DOUBLE,
    source_id   VARCHAR NOT NULL,
    loaded_at   TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (geo_level, geo_id, metric_id, period)
);

CREATE TABLE IF NOT EXISTS geo_boundaries (
    geo_level   VARCHAR NOT NULL,
    geo_id      VARCHAR NOT NULL,
    geojson     JSON NOT NULL,
    PRIMARY KEY (geo_level, geo_id)
);

CREATE TABLE IF NOT EXISTS app_score_configs (
    id          VARCHAR NOT NULL,
    version     INTEGER NOT NULL,
    name        VARCHAR NOT NULL,
    config      JSON NOT NULL,
    created_at  TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (id, version)
);

CREATE TABLE IF NOT EXISTS app_financial_scenarios (
    id          VARCHAR PRIMARY KEY,
    name        VARCHAR NOT NULL,
    geo_level   VARCHAR,
    geo_id      VARCHAR,
    assumptions JSON NOT NULL,
    created_at  TIMESTAMP DEFAULT current_timestamp,
    updated_at  TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS app_saved_markets (
    geo_level   VARCHAR NOT NULL,
    geo_id      VARCHAR NOT NULL,
    note        VARCHAR,
    created_at  TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (geo_level, geo_id)
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    source_id    VARCHAR NOT NULL,
    started_at   TIMESTAMP NOT NULL,
    finished_at  TIMESTAMP,
    status       VARCHAR NOT NULL,
    rows_loaded  BIGINT,
    vintage      VARCHAR,
    message      VARCHAR
);
"""

MARKET_FEATURES_SQL = """
CREATE OR REPLACE TABLE market_features AS
WITH latest AS (
    SELECT geo_level, geo_id, metric_id, value,
           row_number() OVER (PARTITION BY geo_level, geo_id, metric_id ORDER BY period DESC) AS rn
    FROM metric_values
    WHERE value IS NOT NULL
)
PIVOT (SELECT geo_level, geo_id, metric_id, value FROM latest WHERE rn = 1)
ON metric_id USING first(value)
GROUP BY geo_level, geo_id;
"""


def connect(path: Path | None = None, read_only: bool | None = None) -> duckdb.DuckDBPyConnection:
    """Open (and create if needed) the warehouse. Use `:memory:` for tests."""
    target = path or settings.warehouse_path
    if str(target) != ":memory:":
        Path(target).parent.mkdir(parents=True, exist_ok=True)
    ro = settings.read_only_warehouse if read_only is None else read_only
    return duckdb.connect(str(target), read_only=ro)


def ensure_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(SCHEMA_SQL)
    tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    if "market_features" not in tables:
        con.execute(
            "CREATE TABLE market_features (geo_level VARCHAR, geo_id VARCHAR)"
        )


def rebuild_market_features(con: duckdb.DuckDBPyConnection) -> int:
    """Re-pivot metric_values -> market_features. Call after any load. Returns row count."""
    n = con.execute("SELECT count(*) FROM metric_values").fetchone()[0]
    if n == 0:
        con.execute("CREATE OR REPLACE TABLE market_features (geo_level VARCHAR, geo_id VARCHAR)")
        return 0
    con.execute(MARKET_FEATURES_SQL)
    return con.execute("SELECT count(*) FROM market_features").fetchone()[0]


@contextmanager
def warehouse(path: Path | None = None, read_only: bool | None = None) -> Iterator[duckdb.DuckDBPyConnection]:
    con = connect(path, read_only)
    try:
        if not (settings.read_only_warehouse if read_only is None else read_only):
            ensure_schema(con)
        yield con
    finally:
        con.close()
