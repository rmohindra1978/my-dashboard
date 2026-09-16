"""ETL building blocks shared by every source loader.

A `Source` turns a public dataset into two tidy frames:
    geo_units      -> columns of warehouse.geo_units (optional; only geography sources emit these)
    metric_values  -> geo_level, geo_id, metric_id, period, value

Adding a dataset = subclass `Source`, declare `source_id` (must exist in config/metrics.yaml), implement
`extract()` (download to data/raw with caching) and `transform()` (return tidy frames), then register the
class in pipelines/sources/__init__.py. Loading, provenance and the market_features rebuild are handled here.
"""

from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import httpx
import pandas as pd

from backend.app.data.warehouse import rebuild_market_features
from backend.app.models.metrics import MetricRegistry
from backend.app.registry import load_metric_registry
from backend.app.settings import settings

log = logging.getLogger("pipelines")

GEO_UNIT_COLS = [
    "geo_level",
    "geo_id",
    "name",
    "state_fips",
    "state_abbr",
    "lat",
    "lon",
    "land_area_sqmi",
    "cbsa_code",
    "cbsa_name",
]
METRIC_COLS = ["geo_level", "geo_id", "metric_id", "period", "value"]
CROSSWALK_COLS = ["from_level", "from_id", "to_level", "to_id", "weight"]


@dataclass
class Tidy:
    metric_values: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=METRIC_COLS))
    geo_units: pd.DataFrame | None = None
    crosswalk: pd.DataFrame | None = None
    boundaries: pd.DataFrame | None = None  # geo_level, geo_id, geojson (str)


def download(
    url: str,
    dest_dir: Path | None = None,
    filename: str | None = None,
    force: bool = False,
    timeout: float = 300.0,
) -> Path:
    """Download `url` into data/raw/<sha-prefixed filename> once; reuse the cached copy afterwards."""
    dest_dir = dest_dir or settings.raw_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = filename or (
        hashlib.sha1(url.encode()).hexdigest()[:10] + "_" + url.rstrip("/").split("/")[-1].split("?")[0]
    )
    path = dest_dir / name
    if path.exists() and path.stat().st_size > 0 and not force:
        log.info("cache hit %s", path.name)
        return path
    log.info("downloading %s", url)
    tmp = path.with_suffix(path.suffix + ".part")
    with httpx.stream(
        "GET",
        url,
        follow_redirects=True,
        timeout=timeout,
        headers={"User-Agent": "serve-md-intelligence/0.1"},
    ) as r:
        r.raise_for_status()
        with open(tmp, "wb") as fh:
            for chunk in r.iter_bytes(1 << 20):
                fh.write(chunk)
    tmp.replace(path)
    return path


def suppressed_to_null(s: pd.Series) -> pd.Series:
    """CMS/HRSA suppression markers ('*', '', 'N/A', '(D)', ...) -> NaN, everything else numeric."""
    cleaned = s.astype(str).str.strip().str.replace(",", "", regex=False).str.replace("$", "", regex=False)
    cleaned = cleaned.replace(
        {
            "*": None,
            "": None,
            "N/A": None,
            "NA": None,
            "(D)": None,
            "(X)": None,
            "-": None,
            "–": None,
            "nan": None,
            "None": None,
            "null": None,
            "(NA)": None,
        }
    )
    return pd.to_numeric(cleaned, errors="coerce")


class Source(ABC):
    source_id: str
    geo_levels: tuple[str, ...] = ("county",)

    def __init__(self, registry: MetricRegistry | None = None, sample: bool = False):
        self.registry = registry or load_metric_registry()
        self.sample = sample
        if self.source_id not in self.registry.sources:
            raise KeyError(f"source '{self.source_id}' is not declared in config/metrics.yaml")
        self.meta = self.registry.sources[self.source_id]

    @property
    def vintage(self) -> str:
        return self.meta.vintage

    @abstractmethod
    def extract(self) -> dict[str, Path]:
        """Download/cached raw inputs; returns name -> local path."""

    @abstractmethod
    def transform(self, raw: dict[str, Path]) -> Tidy:
        """Raw files -> tidy frames. Must only emit metric_ids that exist in the registry for this source."""

    def validate(self, tidy: Tidy) -> None:
        known = {m.id for m in self.registry.metrics if m.source == self.source_id}
        mv = tidy.metric_values
        if not mv.empty:
            missing = set(mv.columns) ^ set(METRIC_COLS)
            if missing:
                raise ValueError(f"{self.source_id}: metric_values columns mismatch: {missing}")
            bad = set(mv["metric_id"].unique()) - known
            if bad:
                raise ValueError(f"{self.source_id}: emitted metric_ids not in registry: {sorted(bad)}")
            if mv.duplicated(["geo_level", "geo_id", "metric_id", "period"]).any():
                raise ValueError(f"{self.source_id}: duplicate (geo, metric, period) rows")

    def run(self, con: duckdb.DuckDBPyConnection, rebuild_features: bool = True) -> int:
        started = datetime.now(timezone.utc)
        try:
            raw = self.extract()
            tidy = self.transform(raw)
            self.validate(tidy)
            rows = load_tidy(con, tidy, self.source_id)
            if rebuild_features:
                rebuild_market_features(con)
            record_run(con, self.source_id, started, "ok", rows, self.vintage)
            log.info("%s: loaded %d metric rows", self.source_id, rows)
            return rows
        except Exception as exc:  # noqa: BLE001 - provenance must record any failure
            record_run(con, self.source_id, started, "error", 0, self.vintage, str(exc)[:500])
            raise


def record_run(
    con: duckdb.DuckDBPyConnection,
    source_id: str,
    started: datetime,
    status: str,
    rows: int,
    vintage: str,
    message: str | None = None,
) -> None:
    con.execute(
        "INSERT INTO pipeline_runs VALUES (?, ?, ?, ?, ?, ?, ?)",
        [source_id, started, datetime.now(timezone.utc), status, rows, vintage, message],
    )


def upsert_geo_units(con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> int:
    df = df.reindex(columns=GEO_UNIT_COLS)
    df = df.drop_duplicates(["geo_level", "geo_id"])
    con.register("_geo_in", df)
    con.execute("INSERT OR REPLACE INTO geo_units SELECT * FROM _geo_in")
    con.unregister("_geo_in")
    return len(df)


def upsert_crosswalk(con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> int:
    df = df.reindex(columns=CROSSWALK_COLS).drop_duplicates(["from_level", "from_id", "to_level", "to_id"])
    con.register("_xw_in", df)
    con.execute("INSERT OR REPLACE INTO geo_crosswalk SELECT * FROM _xw_in")
    con.unregister("_xw_in")
    return len(df)


def upsert_boundaries(con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> int:
    df = df.reindex(columns=["geo_level", "geo_id", "geojson"]).drop_duplicates(["geo_level", "geo_id"])
    con.register("_b_in", df)
    con.execute("INSERT OR REPLACE INTO geo_boundaries SELECT geo_level, geo_id, geojson::JSON FROM _b_in")
    con.unregister("_b_in")
    return len(df)


def upsert_metric_values(con: duckdb.DuckDBPyConnection, df: pd.DataFrame, source_id: str) -> int:
    if df.empty:
        return 0
    df = df.reindex(columns=METRIC_COLS).copy()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["source_id"] = source_id
    df["geo_id"] = df["geo_id"].astype(str)
    df["period"] = df["period"].astype(str)
    con.register("_mv_in", df)
    con.execute(
        "INSERT OR REPLACE INTO metric_values (geo_level, geo_id, metric_id, period, value, source_id) "
        "SELECT geo_level, geo_id, metric_id, period, value, source_id FROM _mv_in"
    )
    con.unregister("_mv_in")
    return len(df)


def load_tidy(con: duckdb.DuckDBPyConnection, tidy: Tidy, source_id: str) -> int:
    if tidy.geo_units is not None and not tidy.geo_units.empty:
        upsert_geo_units(con, tidy.geo_units)
    if tidy.crosswalk is not None and not tidy.crosswalk.empty:
        upsert_crosswalk(con, tidy.crosswalk)
    if tidy.boundaries is not None and not tidy.boundaries.empty:
        upsert_boundaries(con, tidy.boundaries)
    return upsert_metric_values(con, tidy.metric_values, source_id)
