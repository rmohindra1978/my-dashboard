"""Loads the synthetic fixture CSVs from data/fixtures. Used by `make data-sample`, tests and CI."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from backend.app.data.warehouse import rebuild_market_features
from backend.app.settings import settings
from pipelines.base import Tidy, load_tidy, record_run


class SampleFixtureSource:
    """Not a registry `Source`: fixture rows carry their real `source_id`s so provenance stays truthful."""

    source_id = "sample"

    def __init__(self, fixtures_dir: Path | None = None):
        self.dir = fixtures_dir or settings.fixtures_dir

    def run(self, con: duckdb.DuckDBPyConnection, rebuild_features: bool = True) -> int:
        started = datetime.now(timezone.utc)
        geo = pd.read_csv(
            self.dir / "geo_units.csv", dtype={"geo_id": str, "state_fips": str, "cbsa_code": str}
        )
        xw = pd.read_csv(self.dir / "geo_crosswalk.csv", dtype={"from_id": str, "to_id": str})
        mv = pd.read_csv(self.dir / "metric_values.csv", dtype={"geo_id": str, "period": str})
        total = 0
        load_tidy(con, Tidy(metric_values=mv.iloc[0:0], geo_units=geo, crosswalk=xw), "sample")
        for source_id, part in mv.groupby("source_id"):
            total += load_tidy(con, Tidy(metric_values=part.drop(columns=["source_id"])), str(source_id))
        if rebuild_features:
            rebuild_market_features(con)
        record_run(con, "sample", started, "ok", total, "synthetic")
        return total
