from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from backend.app.data.warehouse import warehouse
from pipelines.base import METRIC_COLS, Source, Tidy, suppressed_to_null
from pipelines.build import build


def test_suppressed_to_null():
    s = pd.Series(["1,234", "*", "", "N/A", "$5.50", "(D)", "7"])
    out = suppressed_to_null(s)
    assert out.tolist()[0] == 1234.0 and out.tolist()[4] == 5.5 and out.tolist()[6] == 7.0
    assert out.isna().tolist() == [False, True, True, True, False, True, False]


def test_sample_build_populates_warehouse(tmp_path: Path):
    path = tmp_path / "w.duckdb"
    res = build([], sample=True, warehouse_path=path)
    assert res["sample"] > 800
    with warehouse(path, read_only=True) as con:
        assert con.execute("SELECT count(*) FROM geo_units WHERE geo_level='county'").fetchone()[0] == 12
        assert con.execute("SELECT count(*) FROM market_features").fetchone()[0] == 27
        cols = {r[0] for r in con.execute("DESCRIBE market_features").fetchall()}
        assert {"pct_65_plus", "ma_penetration_pct", "pcp_per_1000_65plus"} <= cols
        runs = con.execute("SELECT source_id, status FROM pipeline_runs").fetchall()
        assert ("sample", "ok") in runs


class _BadSource(Source):
    source_id = "acs5"

    def extract(self):
        return {}

    def transform(self, raw):
        return Tidy(
            metric_values=pd.DataFrame(
                [["county", "04013", "not_a_metric", "2023", 1.0]], columns=METRIC_COLS
            )
        )


class _GoodSource(Source):
    source_id = "acs5"

    def extract(self):
        return {}

    def transform(self, raw):
        return Tidy(
            metric_values=pd.DataFrame(
                [
                    ["county", "04013", "pct_65_plus", "2019-2023", 17.5],
                    ["county", "04013", "pct_65_plus", "2018-2022", 16.9],
                ],
                columns=METRIC_COLS,
            )
        )


def test_source_validation_and_provenance(tmp_path: Path):
    path = tmp_path / "w.duckdb"
    with warehouse(path, read_only=False) as con:
        with pytest.raises(ValueError, match="not in registry"):
            _BadSource().run(con)
        assert con.execute("SELECT status FROM pipeline_runs WHERE source_id='acs5'").fetchone()[0] == "error"
        assert _GoodSource().run(con) == 2
        # latest period wins in market_features; re-running upserts idempotently
        assert _GoodSource().run(con) == 2
        assert con.execute("SELECT count(*) FROM metric_values").fetchone()[0] == 2
        assert (
            con.execute("SELECT pct_65_plus FROM market_features WHERE geo_id='04013'").fetchone()[0] == 17.5
        )
