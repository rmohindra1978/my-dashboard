"""dac_clinicians loader: transform() against a small checked-in extract of the CMS national file.

Fixture: 285 real rows (all 31 columns) from ZIPs 85004 / 85008 (Phoenix, AZ) and 78701 (Austin, TX)
plus noise rows (non-PCP specialties, CA rows, PR rows) and a few synthetic multi-location rows
(same NPI twice in 85004, three 85004 NPIs also practising in 85008, one suppressed num_org_mem).
No network access is required.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pandas as pd
import pytest

from backend.app.data.warehouse import warehouse
from pipelines.base import CROSSWALK_COLS, METRIC_COLS
from pipelines.sources import SOURCES
from pipelines.sources.dac_clinicians import (
    PCP_PHYSICIAN_SPECIALTIES,
    PCP_SPECIALTIES,
    CliniciansSource,
    aggregate_zcta,
    read_clinician_rows,
)

FIXTURES = Path(__file__).parent / "fixtures" / "dac_clinicians"
RAW = {
    "clinicians": FIXTURES / "DAC_NationalDownloadableFile_sample.csv",
    "metadata": FIXTURES / "metadata_2026-09-10.json",
}
PERIOD = "2026-09"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch):
    def _boom(*a, **k):
        raise AssertionError("network access attempted during test")

    monkeypatch.setattr(httpx, "get", _boom)
    monkeypatch.setattr(httpx, "stream", _boom)


def _wide(mv: pd.DataFrame, level: str) -> pd.DataFrame:
    return mv[mv["geo_level"] == level].pivot(index="geo_id", columns="metric_id", values="value")


def test_registered_and_fixture_small():
    assert SOURCES["dac_clinicians"] is CliniciansSource
    assert RAW["clinicians"].stat().st_size < 200_000


def test_read_rows_filters_specialty_and_normalises_ids():
    rows = read_clinician_rows(RAW["clinicians"])
    assert set(rows.columns) == {"npi", "pri_spec", "num_org_mem", "state", "zcta"}
    assert set(rows["pri_spec"]) <= PCP_SPECIALTIES
    assert rows["zcta"].str.fullmatch(r"\d{5}").all()  # 9-digit ZIP+4 and 5-digit ZIPs both -> 5 digits
    assert rows["npi"].str.fullmatch(r"\d{10}").all()
    # suppressed num_org_mem ('*') -> NaN, never imputed
    assert rows["num_org_mem"].isna().sum() >= 1
    # state filter used by sample mode
    assert set(read_clinician_rows(RAW["clinicians"], ("AZ", "TX"))["state"]) == {"AZ", "TX"}


def test_zcta_distinct_npi_logic():
    rows = read_clinician_rows(RAW["clinicians"], ("AZ",))
    agg = aggregate_zcta(rows).set_index("geo_id")
    # 100 primary-care location rows in 85004 but 4 NPIs are listed twice -> 96 distinct clinicians
    assert (rows["zcta"] == "85004").sum() == 100
    assert agg.loc["85004", "pcp_count"] == 96
    assert agg.loc["85004", "pcp_physician_count"] == 18
    # a clinician is "large group" if ANY of their rows in the ZCTA has num_org_mem >= 50
    assert agg.loc["85004", "large_group_pcp"] == 71
    # three 85004 clinicians also practise in 85008: counted in both ZCTAs
    assert agg.loc["85008", "pcp_count"] == 51
    both = set(rows.loc[rows["zcta"] == "85004", "npi"]) & set(rows.loc[rows["zcta"] == "85008", "npi"])
    assert len(both) == 3


def test_transform_zcta_only_when_no_crosswalk():
    src = CliniciansSource(sample=True)
    tidy = src.transform(RAW)
    mv = tidy.metric_values
    assert list(mv.columns) == METRIC_COLS
    assert set(mv["metric_id"]) == {"pcp_count", "pcp_physician_count", "large_group_pcp_share"}
    assert set(mv["geo_level"]) == {"zcta"}
    assert set(mv["period"]) == {PERIOD}
    src.validate(tidy)

    w = _wide(mv, "zcta")
    assert set(w.index) == {"85004", "85008", "78701"}  # sample mode -> AZ + TX only; PR always dropped
    assert w.loc["85004", "pcp_count"] == 96
    assert w.loc["85004", "pcp_physician_count"] == 18
    assert w.loc["85004", "large_group_pcp_share"] == pytest.approx(71 / 96)
    assert w.loc["85008", "pcp_count"] == 51
    assert w.loc["85008", "pcp_physician_count"] == 20
    assert w.loc["85008", "large_group_pcp_share"] == pytest.approx(42 / 51)
    assert w.loc["78701", "pcp_count"] == 72
    assert w.loc["78701", "pcp_physician_count"] == 11
    assert w.loc["78701", "large_group_pcp_share"] == pytest.approx(65 / 72)
    assert (w["pcp_physician_count"] <= w["pcp_count"]).all()
    assert w["large_group_pcp_share"].between(0, 1).all()


def test_transform_full_mode_keeps_all_states_but_drops_territories():
    mv = CliniciansSource(sample=False).transform(RAW).metric_values
    w = _wide(mv, "zcta")
    assert set(w.index) == {"85004", "85008", "78701", "90012", "90008"}
    assert w.loc["90012", "pcp_count"] == 4 and w.loc["90012", "pcp_physician_count"] == 1
    assert w.loc["90012", "large_group_pcp_share"] == 0.0


def test_transform_county_aggregation_via_crosswalk():
    src = CliniciansSource(sample=True)
    src.crosswalk = pd.DataFrame(
        [
            ["zcta", "85004", "county", "04013", 1.0],
            ["zcta", "85008", "county", "04013", 1.0],
            ["zcta", "78701", "county", "48453", 1.0],
        ],
        columns=CROSSWALK_COLS,
    )
    tidy = src.transform(RAW)
    src.validate(tidy)
    z = _wide(tidy.metric_values, "zcta")
    c = _wide(tidy.metric_values, "county")
    assert set(c.index) == {"04013", "48453"}
    # Maricopa = distinct clinicians across 85004 + 85008: 96 + 51 - 3 shared = 144 (not 147)
    assert c.loc["04013", "pcp_count"] == 144
    assert c.loc["04013", "pcp_physician_count"] == 38
    assert c.loc["04013", "large_group_pcp_share"] == pytest.approx(111 / 144)
    # a single-ZCTA county equals its ZCTA row exactly
    assert c.loc["48453"].tolist() == z.loc["78701"].tolist()


def test_transform_county_split_zcta_is_weighted():
    src = CliniciansSource(sample=True)
    src.crosswalk = pd.DataFrame(
        [
            ["zcta", "85004", "county", "04013", 1.0],
            ["zcta", "85008", "county", "04013", 0.6],
            ["zcta", "85008", "county", "04021", 0.4],
        ],
        columns=CROSSWALK_COLS,
    )
    c = _wide(src.transform(RAW).metric_values, "county")
    # 96 (85004, w=1) + 48 clinicians only in 85008 x 0.6 = 124.8 -> 125; the 3 shared take max weight 1
    assert c.loc["04013", "pcp_count"] == 125
    assert c.loc["04021", "pcp_count"] == round(51 * 0.4)


def test_universe_drops_non_zcta_zips_and_emits_zeros():
    src = CliniciansSource(sample=True)
    src.universe = {"zcta": {"85004", "78701", "85001"}}
    src.crosswalk = pd.DataFrame(
        [["zcta", "85004", "county", "04013", 1.0], ["zcta", "85008", "county", "04013", 1.0]],
        columns=CROSSWALK_COLS,
    )
    tidy = src.transform(RAW)
    src.validate(tidy)
    w = _wide(tidy.metric_values, "zcta")
    assert set(w.index) == {"85004", "78701", "85001"}  # 85008 dropped (not a ZCTA), 85001 added as 0
    assert w.loc["85001", "pcp_count"] == 0 and w.loc["85001", "pcp_physician_count"] == 0
    assert pd.isna(w.loc["85001", "large_group_pcp_share"])
    # county aggregation only sees rows that survived the universe filter
    c = _wide(tidy.metric_values, "county")
    assert c.loc["04013", "pcp_count"] == 96
    assert c.loc["04013", "large_group_pcp_share"] == pytest.approx(71 / 96)


def test_county_universe_emits_zero_counties():
    src = CliniciansSource(sample=True)
    src.universe = {"county": {"04013", "04012"}}
    src.crosswalk = pd.DataFrame(
        [["zcta", "85004", "county", "04013", 1.0], ["zcta", "78701", "county", "48453", 1.0]],
        columns=CROSSWALK_COLS,
    )
    c = _wide(src.transform(RAW).metric_values, "county")
    assert set(c.index) == {"04013", "04012"}  # 48453 outside the universe is dropped
    assert c.loc["04012", "pcp_count"] == 0 and pd.isna(c.loc["04012", "large_group_pcp_share"])


def test_run_reads_crosswalk_from_warehouse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(CliniciansSource, "extract", lambda self: RAW)
    with warehouse(tmp_path / "w.duckdb", read_only=False) as con:
        src = CliniciansSource(sample=True)
        assert src.run(con) == 9  # 3 ZCTAs x 3 metrics, no crosswalk -> no county rows
        con.execute(
            "INSERT INTO geo_crosswalk VALUES ('zcta','85004','county','04013',1.0), "
            "('zcta','85008','county','04013',1.0)"
        )
        assert CliniciansSource(sample=True).run(con) == 12
        got = con.execute(
            "SELECT value FROM metric_values "
            "WHERE geo_level='county' AND geo_id='04013' AND metric_id='pcp_count'"
        ).fetchone()[0]
        assert got == 144
        assert (
            con.execute(
                "SELECT pcp_count FROM market_features WHERE geo_level='zcta' AND geo_id='85004'"
            ).fetchone()[0]
            == 96
        )
        assert ("dac_clinicians", "ok") in con.execute(
            "SELECT source_id, status FROM pipeline_runs"
        ).fetchall()


def test_specialty_sets():
    assert PCP_PHYSICIAN_SPECIALTIES < PCP_SPECIALTIES
    assert {"NURSE PRACTITIONER", "PHYSICIAN ASSISTANT"} == PCP_SPECIALTIES - PCP_PHYSICIAN_SPECIALTIES
    assert "HOSPITALIST" not in PCP_SPECIALTIES and "PEDIATRIC MEDICINE" not in PCP_SPECIALTIES
