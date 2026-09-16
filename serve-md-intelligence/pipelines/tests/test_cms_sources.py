"""Offline tests for the CMS loaders: transform() over small checked-in API pages, no network."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from pipelines import cms_api
from pipelines.base import METRIC_COLS
from pipelines.sources.cms_enrollment import EnrollmentSource
from pipelines.sources.cms_geo_variation import GeoVariationSource

FIXTURES = Path(__file__).parent / "fixtures"


def _pages(source_id: str) -> dict[str, Path]:
    return {p.stem: p for p in sorted((FIXTURES / source_id).glob("*.json"))}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch):
    def boom(*a, **k):  # pragma: no cover
        raise AssertionError("network access attempted")

    monkeypatch.setattr("httpx.stream", boom)


def _value(mv: pd.DataFrame, level: str, geo_id: str, metric: str, period: str) -> float:
    row = mv[
        (mv.geo_level == level) & (mv.geo_id == geo_id) & (mv.metric_id == metric) & (mv.period == period)
    ]
    assert len(row) == 1, (level, geo_id, metric, period)
    return float(row["value"].iloc[0])


def test_enrollment_transform():
    src = EnrollmentSource()
    tidy = src.transform(_pages("cms_enrollment"))
    mv = tidy.metric_values
    src.validate(tidy)
    assert list(mv.columns) == METRIC_COLS
    assert set(mv.metric_id) == {
        "medicare_benes_total",
        "medicare_benes_aged",
        "original_medicare_benes",
        "medicare_ma_benes",
        "ma_penetration_pct",
        "dual_eligible_pct",
        "medicare_benes_growth_5yr",
    }
    # 50 states + DC only; PR / VI state and county rows and 'Unknown' (xx999) counties are dropped
    states = set(mv[mv.geo_level == "state"].geo_id)
    assert len(states) == 51 and {"72", "78"}.isdisjoint(states) and "11" in states
    counties = set(mv[mv.geo_level == "county"].geo_id)
    assert {"72127", "78030", "04999", "48999"}.isdisjoint(counties)
    assert all(len(c) == 5 for c in counties) and all(len(s) == 2 for s in states)
    # Maricopa County AZ, 2025 annual averages (values as published by CMS)
    assert _value(mv, "county", "04013", "medicare_benes_total", "2025") == 801802
    assert _value(mv, "county", "04013", "medicare_ma_benes", "2025") == 407595
    assert _value(mv, "county", "04013", "original_medicare_benes", "2025") == 394208
    assert _value(mv, "county", "04013", "medicare_benes_aged", "2025") == 739089
    assert _value(mv, "county", "04013", "ma_penetration_pct", "2025") == pytest.approx(407595 / 801802 * 100)
    assert _value(mv, "county", "04013", "dual_eligible_pct", "2025") == pytest.approx(118115 / 801802 * 100)
    # 5-year growth uses YEAR-5 (2025 vs 2020, 2024 vs 2019); 2019/2020 have no base year in the fixture
    assert _value(mv, "county", "04013", "medicare_benes_growth_5yr", "2025") == pytest.approx(
        (801802 / 722899 - 1) * 100
    )
    growth_periods = set(mv[mv.metric_id == "medicare_benes_growth_5yr"].period)
    assert growth_periods == {"2024", "2025"}
    # history: one total per year
    hist = mv[(mv.geo_id == "04013") & (mv.metric_id == "medicare_benes_total")]
    assert sorted(hist.period) == ["2019", "2020", "2024", "2025"]
    assert not mv.duplicated(["geo_level", "geo_id", "metric_id", "period"]).any()


def test_enrollment_sample_subset():
    mv = EnrollmentSource(sample=True).transform(_pages("cms_enrollment")).metric_values
    assert set(mv.geo_id.str[:2]) == {"04", "48"}


def test_geo_variation_transform():
    src = GeoVariationSource()
    tidy = src.transform(_pages("cms_geo_variation"))
    mv = tidy.metric_values
    src.validate(tidy)
    assert list(mv.columns) == METRIC_COLS
    # the 2014-2024 release has no BENE_AVG_RISK_SCRE column -> avg_hcc_risk_score is not emitted
    assert set(mv.metric_id) == {
        "medicare_spend_per_capita_std",
        "ed_visits_per_1000",
        "readmission_rate",
        "ip_stays_per_1000",
    }
    states = set(mv[mv.geo_level == "state"].geo_id)
    assert len(states) == 51 and {"72", "78", ""}.isdisjoint(states)
    counties = set(mv[mv.geo_level == "county"].geo_id)
    assert {"78030", "04000", "48000"}.isdisjoint(counties)
    # Maricopa County AZ 2024
    assert _value(mv, "county", "04013", "medicare_spend_per_capita_std", "2024") == pytest.approx(13276.22)
    assert _value(mv, "county", "04013", "ed_visits_per_1000", "2024") == pytest.approx(542.4782)
    assert _value(mv, "county", "04013", "ip_stays_per_1000", "2024") == pytest.approx(202.7427)
    assert _value(mv, "county", "04013", "readmission_rate", "2024") == pytest.approx(16.73)  # 0.1673 -> %
    # suppressed '*' -> NULL, never imputed
    assert pd.isna(_value(mv, "county", "48301", "readmission_rate", "2024"))
    ed = mv[(mv.geo_id == "04013") & (mv.metric_id == "ed_visits_per_1000")]
    assert sorted(ed.period) == ["2023", "2024"]


def test_geo_variation_emits_risk_score_when_column_present(tmp_path: Path):
    rows = json.loads((FIXTURES / "cms_geo_variation" / "county_2024_p0.json").read_text())
    for r in rows:
        r["BENE_AVG_RISK_SCRE"] = "1.05" if r["BENE_GEO_CD"] == "04013" else "*"
    p = tmp_path / "county_2024_p0.json"
    p.write_text(json.dumps(rows))
    mv = GeoVariationSource().transform({"county_2024_p0": p}).metric_values
    assert _value(mv, "county", "04013", "avg_hcc_risk_score", "2024") == 1.05


def test_download_years_pagination_and_caching(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """download_years walks years until an empty result, paginates, never caches empty pages, reuses files."""
    served: dict[tuple[str, str], list[dict]] = {
        ("2023", "0"): [{"YEAR": "2023", "i": str(i)} for i in range(cms_api.PAGE_SIZE)],
        ("2023", str(cms_api.PAGE_SIZE)): [{"YEAR": "2023", "i": "x"}],
        ("2024", "0"): [{"YEAR": "2024", "i": "0"}],
    }
    calls: list[str] = []

    def fake_download(url: str, dest_dir: Path, filename: str, **_):
        calls.append(url)
        year = url.split("filter%5BYEAR%5D=")[1].split("&")[0]
        offset = url.split("offset=")[1].split("&")[0]
        path = dest_dir / filename
        dest_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(served.get((year, offset), [])))
        return path

    monkeypatch.setattr(cms_api, "download", fake_download)
    out = cms_api.download_years("ds", tmp_path, "county", {"A": "b"}, ["YEAR", "i"], 2023, last_year=2026)
    assert sorted(out) == ["county_2023_p0", "county_2023_p1", "county_2024_p0"]
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "county_2023_p0.json",
        "county_2023_p1.json",
        "county_2024_p0.json",
    ]
    assert len(calls) == 4  # 2 pages 2023, 1 page 2024, 1 empty probe for 2025 (stops before 2026)
    assert "column=YEAR%2Ci" in calls[0] and "filter%5BA%5D=b" in calls[0]
    df = cms_api.read_pages(out)
    assert len(df) == cms_api.PAGE_SIZE + 2 and df["i"].dtype == object
