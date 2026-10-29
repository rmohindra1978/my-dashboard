"""census_geo / acs5 / popest loaders and the derived-metrics step, against small checked-in extracts.

Fixtures are real rows from the national files: Maricopa (04013) + Pima (04019) AZ, the Capitol Planning
Region CT (09110), and Puerto Rico rows (state 72 / ZCTA 00601) that must be dropped. Shapefiles are heavily
simplified copies of the 2023/2020 cartographic boundary features. No network access is required.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pandas as pd
import pytest

from backend.app.data.warehouse import warehouse
from pipelines.base import Tidy, load_tidy
from pipelines.derived import compute_derived_metrics
from pipelines.fips import is_sample_zcta, is_us_zcta
from pipelines.sources import SOURCES
from pipelines.sources.acs5 import AcsSource, needed_columns
from pipelines.sources.census_geo import URLS, CensusGeoSource, place_display_name
from pipelines.sources.popest import PopEstSource

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch):
    def _boom(*a, **k):
        raise AssertionError("network access attempted during test")

    monkeypatch.setattr(httpx, "get", _boom)
    monkeypatch.setattr(httpx, "stream", _boom)


def _geo_raw() -> dict[str, Path]:
    d = FIX / "census_geo"
    return {
        k: d / u.rsplit("/", 1)[-1].replace(".zip", ".txt")
        if k.startswith("gaz")
        else d / u.rsplit("/", 1)[-1]
        for k, u in URLS.items()
    }


@pytest.fixture(scope="module")
def geo() -> Tidy:
    return CensusGeoSource().transform(_geo_raw())


def _wide(mv: pd.DataFrame) -> pd.DataFrame:
    return mv.pivot_table(index=["geo_level", "geo_id"], columns="metric_id", values="value")


def test_registered_in_dependency_order_and_fixtures_small():
    order = list(SOURCES)
    assert order[:3] == ["census_geo", "acs5", "popest"]
    assert order.index("census_geo") < order.index("dac_clinicians")
    for sub in ("census_geo", "acs5", "popest"):
        assert sum(p.stat().st_size for p in (FIX / sub).iterdir()) < 200_000


def test_place_display_name():
    assert place_display_name("Phoenix city") == "Phoenix"
    assert place_display_name("Abanda CDP") == "Abanda"
    assert place_display_name("Nashville-Davidson metropolitan government (balance)") == "Nashville-Davidson"
    assert place_display_name("Anchorage municipality") == "Anchorage"


def test_zcta_helpers():
    assert is_us_zcta("85004") and is_us_zcta("06103")
    assert not is_us_zcta("00601") and not is_us_zcta("96910") and not is_us_zcta("8500")
    assert is_sample_zcta("85004") and is_sample_zcta("78701") and not is_sample_zcta("06103")


def test_geo_units(geo: Tidy):
    g = geo.geo_units.set_index(["geo_level", "geo_id"])
    assert g.groupby(level=0).size().to_dict() == {"county": 3, "place": 3, "state": 2, "zcta": 3}
    assert not any(i.startswith("72") for i in g.loc["county"].index)  # Puerto Rico dropped
    assert "00601" not in g.loc["zcta"].index
    mar = g.loc[("county", "04013")]
    assert mar["name"] == "Maricopa County" and mar["state_abbr"] == "AZ"
    assert mar["cbsa_code"] == "38060" and mar["cbsa_name"].startswith("Phoenix-Mesa")
    assert mar["land_area_sqmi"] == pytest.approx(9202, rel=0.01)
    assert g.loc[("place", "0455000"), "name"] == "Phoenix"
    assert g.loc[("place", "0455000"), "cbsa_code"] == "38060"
    z = g.loc[("zcta", "85004")]
    assert (
        z["state_abbr"] == "AZ" and z["cbsa_code"] == "38060" and z["lat"] == pytest.approx(33.45, abs=0.05)
    )
    assert g.loc[("zcta", "06103"), "state_abbr"] == "CT"  # state from the majority county
    assert g.loc[("state", "04"), "name"] == "Arizona" and g.loc[("state", "04"), "land_area_sqmi"] > 100_000


def test_crosswalk(geo: Tidy):
    x = geo.crosswalk
    sums = x.groupby(["from_level", "from_id", "to_level"])["weight"].sum()
    assert sums.to_numpy() == pytest.approx(1.0)
    zc = x[(x.from_level == "zcta") & (x.to_level == "county")].set_index("from_id")
    assert zc.loc["85004", "to_id"] == "04013"
    # CT ZCTAs map to 2023 planning regions (polygon overlap), not the retired 2020 counties
    assert set(zc.loc[["06103"], "to_id"]) == {"09110"}
    pl = x[x.from_level == "place"].set_index("from_id")
    assert pl.loc["0455000", "to_id"] == "04013" and pl.loc["0477000", "to_id"] == "04019"
    assert len(x[(x.from_level == "county") & (x.to_level == "state")]) == 3


def test_boundaries(geo: Tidy):
    b = geo.boundaries
    assert set(b.geo_level) == {"state", "county", "zcta", "place"}
    for gj in b.geojson:
        assert json.loads(gj)["type"] in {"Polygon", "MultiPolygon"}
    assert not b.geo_id.str.startswith("72").any()


def test_acs5_metrics():
    d = FIX / "acs5"
    mv = AcsSource().transform({t: d / f"acsdt5y2023-{t}.dat" for t in needed_columns()}).metric_values
    assert set(mv.period) == {"2019-2023"}
    w = _wide(mv)
    assert set(w.index.get_level_values(0)) == {"state", "county", "zcta", "place"}
    assert ("state", "72") not in w.index and ("zcta", "00601") not in w.index
    assert not w.index.duplicated().any()  # component rows (0500001US...) ignored
    m = w.loc[("county", "04013")]
    assert m["pop_total"] == 4_491_987
    assert m["median_household_income"] == 85_518
    assert m["pop_65_plus"] == pytest.approx(718_079)
    assert m["pct_65_plus"] == pytest.approx(718_079 / 4_491_987 * 100)
    assert m["pop_75_plus"] < m["pop_65_plus"]
    for pct in (
        "pct_65_plus",
        "pct_65_living_alone",
        "pct_65_plus_disability",
        "poverty_rate_65_plus",
        "unemployment_rate",
        "pct_bachelors_plus",
        "pct_hispanic",
        "pct_black",
    ):
        assert 0 < m[pct] < 100, pct
    assert w.loc[("place", "0455000"), "pop_total"] == 1_624_832
    assert w.loc[("zcta", "85004"), "pop_total"] == 11_178


def test_acs5_sentinels_become_null(tmp_path: Path):
    src = FIX / "acs5"
    raw = {t: src / f"acsdt5y2023-{t}.dat" for t in needed_columns()}
    lines = raw["b19013"].read_text().splitlines()
    lines = [lines[0]] + [
        ln.replace("|85518|", "|-666666666|") if ln.startswith("0500000US04013|") else ln for ln in lines[1:]
    ]
    raw["b19013"] = tmp_path / "acsdt5y2023-b19013.dat"
    raw["b19013"].write_text("\n".join(lines) + "\n")
    mv = AcsSource().transform(raw).metric_values
    hit = mv[(mv.geo_id == "04013") & (mv.metric_id == "median_household_income")]
    assert hit.empty


def test_popest_growth():
    mv = PopEstSource().transform({"agesex": FIX / "popest" / "cc-est2024-agesex-all.csv"}).metric_values
    w = _wide(mv)
    m = w.loc[("county", "04013")]
    assert m["pop_growth_5yr"] == pytest.approx((4_673_096 / 4_425_315 - 1) * 100)
    assert m["pop_65_plus_growth_5yr"] == pytest.approx((789_700 / 691_207 - 1) * 100)
    assert ("state", "04") in w.index and ("state", "48") in w.index
    assert set(mv.period) == {"2020-2024"}


def test_derived_metrics(tmp_path: Path):
    with warehouse(tmp_path / "w.duckdb", read_only=False) as con:
        assert compute_derived_metrics(con) == {
            "pop_density": 0,
            "pcp_per_1000_65plus": 0,
            "pcp_per_10k_pop": 0,
        }
        geo_units = pd.DataFrame(
            [["county", "04013", "Maricopa County", "04", "AZ", 33.3, -112.5, 9200.0, None, None]],
            columns=[
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
            ],
        )
        mv = pd.DataFrame(
            [
                ["county", "04013", "pop_total", "2019-2023", 4_600_000.0],
                ["county", "04013", "pop_65_plus", "2019-2023", 700_000.0],
            ],
            columns=["geo_level", "geo_id", "metric_id", "period", "value"],
        )
        load_tidy(con, Tidy(metric_values=mv, geo_units=geo_units), "acs5")
        load_tidy(
            con,
            Tidy(
                metric_values=pd.DataFrame(
                    [["county", "04013", "pcp_count", "2026-09", 3500.0]],
                    columns=["geo_level", "geo_id", "metric_id", "period", "value"],
                )
            ),
            "dac_clinicians",
        )
        counts = compute_derived_metrics(con)
        assert counts == {"pop_density": 1, "pcp_per_1000_65plus": 1, "pcp_per_10k_pop": 1}
        rows = dict(
            con.execute(
                "SELECT metric_id, value FROM metric_values WHERE metric_id IN "
                "('pop_density','pcp_per_1000_65plus','pcp_per_10k_pop')"
            ).fetchall()
        )
        assert rows["pop_density"] == pytest.approx(500.0)
        assert rows["pcp_per_1000_65plus"] == pytest.approx(5.0)
        assert rows["pcp_per_10k_pop"] == pytest.approx(3500 / 4_600_000 * 10_000)
        src = dict(
            con.execute(
                "SELECT metric_id, source_id || ':' || period FROM metric_values "
                "WHERE metric_id LIKE 'pcp_per%'"
            ).fetchall()
        )
        assert src["pcp_per_1000_65plus"] == "dac_clinicians:2026-09"
        assert compute_derived_metrics(con) == counts  # idempotent
