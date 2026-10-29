"""census_geo / acs5 / popest transforms and the derived-metrics step, on small checked-in fixtures.

Fixtures (pipelines/tests/fixtures/census/) are cut from the real national Census files for counties
04013 Maricopa AZ, 04021 Pinal AZ, 48301 Loving TX, 35001 Bernalillo NM and 72127 San Juan PR; ZCTAs
85004, 85142 (Maricopa/Pinal split), 79754, 87102, 00901 (PR); places Phoenix, Queen Creek (two-county
place), Albuquerque and San Juan PR. Boundaries are pre-simplified. One synthetic edit: Loving County's
B25077 median home value is replaced by the -666666666 sentinel. No network access is required.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pandas as pd
import pytest

from backend.app.data.warehouse import warehouse
from pipelines.base import CROSSWALK_COLS, GEO_UNIT_COLS, METRIC_COLS, upsert_geo_units, upsert_metric_values
from pipelines.derived import compute_derived_metrics
from pipelines.sources import SOURCES
from pipelines.sources.acs5 import TABLES, AcsSource, compute_metrics
from pipelines.sources.census_geo import URLS, CensusGeoSource, clean_place_name
from pipelines.sources.popest import PopEstSource, growth

FIX = Path(__file__).parent / "fixtures" / "census"
GEO_RAW = {key: FIX / url.rsplit("/", 1)[-1] for key, (url, _) in URLS.items()}
ACS_RAW = {"geos": FIX / "Geos20235YR.txt", **{t: FIX / f"acsdt5y2023-{t}.dat" for t in TABLES}}
POP_RAW = {"agesex": FIX / "cc-est2024-agesex-all.csv"}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch):
    def _boom(*a, **k):
        raise AssertionError("network access attempted during test")

    monkeypatch.setattr(httpx, "get", _boom)
    monkeypatch.setattr(httpx, "stream", _boom)


@pytest.fixture(scope="module")
def geo():
    return CensusGeoSource().transform(GEO_RAW)


def _wide(mv: pd.DataFrame, level: str) -> pd.DataFrame:
    return mv[mv["geo_level"] == level].pivot(index="geo_id", columns="metric_id", values="value")


def test_registered_in_dependency_order_and_fixtures_small():
    order = list(SOURCES)
    assert order[:3] == ["census_geo", "acs5", "popest"]
    assert order.index("census_geo") < order.index("dac_clinicians")
    assert all(p.stat().st_size < 200_000 for p in FIX.iterdir())


@pytest.mark.parametrize(
    "raw,clean",
    [
        ("Phoenix city", "Phoenix"),
        ("Abanda CDP", "Abanda"),
        ("Boise City city", "Boise City"),
        ("Carson City", "Carson City"),
        ("Indianapolis city (balance)", "Indianapolis"),
        ("Nashville-Davidson metropolitan government (balance)", "Nashville-Davidson"),
        ("Queen Creek town", "Queen Creek"),
    ],
)
def test_clean_place_name(raw, clean):
    assert clean_place_name(raw) == clean


def test_geo_units_levels_ids_and_territories(geo):
    gu = geo.geo_units
    assert list(gu.columns) == GEO_UNIT_COLS
    ids = gu.groupby("geo_level")["geo_id"].apply(set).to_dict()
    assert ids["state"] == {"04", "35", "48"}
    assert ids["county"] == {"04013", "04021", "35001", "48301"}
    assert ids["zcta"] == {"85004", "85142", "79754", "87102"}
    assert ids["place"] == {"0455000", "0458150", "3502000"}
    width = {"state": 2, "county": 5, "zcta": 5, "place": 7}
    assert all(len(r.geo_id) == width[r.geo_level] for r in gu.itertuples())
    assert not gu["state_fips"].eq("72").any()


def test_geo_unit_attributes(geo):
    gu = geo.geo_units.set_index(["geo_level", "geo_id"])
    mar = gu.loc[("county", "04013")]
    assert (mar["name"], mar["state_abbr"], mar["cbsa_code"]) == ("Maricopa County", "AZ", "38060")
    assert mar["land_area_sqmi"] == pytest.approx(9202.016)
    assert gu.loc[("place", "0455000"), "name"] == "Phoenix"
    assert gu.loc[("place", "0458150"), "cbsa_name"] == "Phoenix-Mesa-Chandler, AZ"
    z = gu.loc[("zcta", "79754")]
    assert (z["state_fips"], z["state_abbr"], z["name"]) == ("48", "TX", "79754")
    assert pd.isna(z["cbsa_code"])  # Loving County is outside any CBSA
    az = gu.loc[("state", "04")]
    assert (az["name"], az["state_abbr"]) == ("Arizona", "AZ")
    assert 31 < az["lat"] < 37 and -115 < az["lon"] < -109


def test_crosswalk_weights(geo):
    xw = geo.crosswalk
    assert list(xw.columns) == CROSSWALK_COLS
    sums = xw[xw["from_level"] != "state"].groupby(["from_level", "from_id"])["weight"].sum()
    assert sums.to_numpy() == pytest.approx(1.0)
    split = xw[(xw["from_level"] == "zcta") & (xw["from_id"] == "85142")].set_index("to_id")["weight"]
    assert split["04021"] == pytest.approx(177308726 / (177308726 + 85143172))
    qc = xw[(xw["from_level"] == "place") & (xw["from_id"] == "0458150")]
    assert set(qc["to_id"]) == {"04013", "04021"}
    edges = set(xw[["from_level", "from_id", "to_level", "to_id"]].itertuples(index=False, name=None))
    assert ("county", "04013", "state", "04") in edges
    assert ("state", "48", "county", "48301") in edges
    assert not xw["to_id"].str.startswith("72").any()


def test_boundaries_geojson(geo):
    b = geo.boundaries
    assert b.groupby("geo_level").size().to_dict() == {"county": 4, "place": 3, "state": 3, "zcta": 4}
    for g in b["geojson"]:
        parsed = json.loads(g)
        assert parsed["type"] in {"Polygon", "MultiPolygon"} and parsed["coordinates"]


def test_census_geo_sample_mode_az_tx_only():
    gu = CensusGeoSource(sample=True).transform(GEO_RAW).geo_units
    assert set(gu["state_fips"]) == {"04", "48"}


@pytest.fixture(scope="module")
def acs():
    src = AcsSource()
    src.zcta_universe = {"85004", "85142", "79754", "87102"}
    return src.transform(ACS_RAW).metric_values


def test_acs_emits_every_registered_metric(acs):
    assert list(acs.columns) == METRIC_COLS
    expected = {m.id for m in AcsSource().registry.metrics if m.source == "acs5"}
    assert set(acs["metric_id"]) == expected
    assert set(acs["period"]) == {"2019-2023"}
    ids = acs.groupby("geo_level")["geo_id"].apply(set).to_dict()
    assert ids == {
        "state": {"04", "35", "48"},
        "county": {"04013", "04021", "35001", "48301"},
        "zcta": {"85004", "85142", "79754", "87102"},
        "place": {"0455000", "0458150", "3502000"},
    }


def test_acs_maricopa_values(acs):
    m = _wide(acs, "county").loc["04013"]
    assert m["pop_total"] == 4491987
    assert m["pop_65_plus"] == 718079
    assert m["pop_75_plus"] == 302792
    assert m["pct_65_plus"] == pytest.approx(718079 / 4491987 * 100)
    assert m["median_age"] == 37.5
    assert m["median_household_income"] == 85518
    assert m["median_home_value"] == 414700
    for pct in (
        "pct_65_living_alone",
        "pct_65_plus_disability",
        "poverty_rate_65_plus",
        "pct_bachelors_plus",
    ):
        assert 0 < m[pct] < 100


def test_acs_sentinels_are_null(acs):
    assert pd.isna(_wide(acs, "county").loc["48301", "median_home_value"])
    assert pd.isna(_wide(acs, "zcta").loc["79754", "median_home_value"])


def test_acs_partial_cells_and_zero_denominator_are_null():
    cols = [c for cols in TABLES.values() for c in cols]
    w = pd.DataFrame([dict.fromkeys(cols, 0.0), dict.fromkeys(cols, 10.0)], index=["zero", "partial"])
    w.loc["partial", "B01001_E020"] = float("nan")
    out = compute_metrics(w)
    assert pd.isna(out.loc["zero", "pct_65_plus"]) and out.loc["zero", "pop_total"] == 0
    assert pd.isna(out.loc["partial", "pop_65_plus"]) and pd.isna(out.loc["partial", "pct_65_plus"])


def test_acs_sample_without_geography_has_no_zctas():
    mv = AcsSource(sample=True).transform(ACS_RAW).metric_values
    assert set(mv["geo_level"]) == {"state", "county", "place"}
    assert set(mv["geo_id"].str[:2]) == {"04", "48"}


def test_popest_growth():
    mv = PopEstSource().transform(POP_RAW).metric_values
    assert list(mv.columns) == METRIC_COLS and set(mv["period"]) == {"2020-2024"}
    assert set(mv[mv["geo_level"] == "county"]["geo_id"]) == {"04013", "04021", "35001", "48301"}
    assert set(mv[mv["geo_level"] == "state"]["geo_id"]) == {"04", "35", "48"}
    c = _wide(mv, "county")
    assert c.loc["04013", "pop_growth_5yr"] == pytest.approx(5.599172, abs=1e-5)
    raw = pd.read_csv(POP_RAW["agesex"], dtype={"STATE": str, "COUNTY": str, "YEAR": str})
    az = raw[(raw["STATE"] == "04")].groupby("YEAR")["AGE65PLUS_TOT"].sum()
    assert _wide(mv, "state").loc["04", "pop_65_plus_growth_5yr"] == pytest.approx(
        (az["6"] / az["1"] - 1) * 100
    )


def test_popest_zero_base_is_null():
    df = pd.DataFrame(
        {"geo_id": ["x", "x"], "YEAR": ["1", "6"], "POPESTIMATE": [0, 5], "AGE65PLUS_TOT": [10, 12]}
    )
    g = growth(df, "county", "2020-2024").set_index("metric_id")["value"]
    assert pd.isna(g["pop_growth_5yr"]) and g["pop_65_plus_growth_5yr"] == pytest.approx(20.0)


def _mv(rows):
    return pd.DataFrame(rows, columns=METRIC_COLS)


def test_derived_metrics(tmp_path: Path):
    with warehouse(tmp_path / "w.duckdb", read_only=False) as con:
        assert compute_derived_metrics(con) == dict.fromkeys(
            ["pop_density", "pcp_per_1000_65plus", "pcp_per_10k_pop"], 0
        )
        gu = pd.DataFrame(
            [
                ["county", "04013", "Maricopa County", "04", "AZ", 33.3, -112.5, 9202.0, None, None],
                ["zcta", "85004", "85004", "04", "AZ", 33.4, -112.1, 0.0, None, None],
            ],
            columns=GEO_UNIT_COLS,
        )
        upsert_geo_units(con, gu)
        upsert_metric_values(
            con,
            _mv(
                [
                    ["county", "04013", "pop_total", "2019-2023", 4491987.0],
                    ["county", "04013", "pop_65_plus", "2019-2023", 718079.0],
                    ["zcta", "85004", "pop_total", "2019-2023", 9000.0],
                ]
            ),
            "acs5",
        )
        upsert_metric_values(
            con, _mv([["county", "04013", "pcp_count", "2026-09", 3590.0]]), "dac_clinicians"
        )
        res = compute_derived_metrics(con)
        assert res == {"pop_density": 2, "pcp_per_1000_65plus": 1, "pcp_per_10k_pop": 1}
        got = {
            (m, g): (p, v)
            for m, g, p, v in con.execute(
                "SELECT metric_id, geo_id, period, value FROM metric_values "
                "WHERE metric_id IN ('pop_density','pcp_per_1000_65plus','pcp_per_10k_pop')"
            ).fetchall()
        }
        assert got[("pop_density", "04013")] == ("2019-2023", pytest.approx(4491987 / 9202.0))
        assert got[("pop_density", "85004")][1] is None  # zero land area
        assert got[("pcp_per_1000_65plus", "04013")] == ("2026-09", pytest.approx(3590 / 718079 * 1000))
        assert got[("pcp_per_10k_pop", "04013")] == ("2026-09", pytest.approx(3590 / 4491987 * 10000))
        src = dict(
            con.execute("SELECT metric_id, source_id FROM metric_values WHERE geo_id='04013'").fetchall()
        )
        assert src["pop_density"] == "census_geo" and src["pcp_per_10k_pop"] == "dac_clinicians"


def test_census_sources_run_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(CensusGeoSource, "extract", lambda self: GEO_RAW)
    monkeypatch.setattr(AcsSource, "extract", lambda self: ACS_RAW)
    monkeypatch.setattr(PopEstSource, "extract", lambda self: POP_RAW)
    with warehouse(tmp_path / "w.duckdb", read_only=False) as con:
        for cls in (CensusGeoSource, AcsSource, PopEstSource):
            cls().run(con, rebuild_features=False)
        compute_derived_metrics(con)
        zctas = con.execute(
            "SELECT DISTINCT geo_id FROM metric_values WHERE geo_level='zcta' AND metric_id='pop_total'"
        ).fetchall()
        assert {z for (z,) in zctas} == {"85004", "85142", "79754", "87102"}
        dens = con.execute(
            "SELECT value FROM metric_values WHERE geo_id='04013' AND metric_id='pop_density'"
        ).fetchone()[0]
        assert dens == pytest.approx(4491987 / 9202.016)
