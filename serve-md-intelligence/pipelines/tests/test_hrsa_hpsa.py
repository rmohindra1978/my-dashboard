"""hrsa_hpsa transform() on a 26-row fixture cut from the real detail file (no network).

Fixture edits vs. the published rows: La Paz County AZ is stored unpadded ("4012"), Loving County TX
has its only (Designated) score suppressed ("*"), and one Withdrawn Maricopa row carries score 25.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from pipelines.base import METRIC_COLS
from pipelines.sources.hrsa_hpsa import HpsaSource, read_hpsa_csv

FIXTURE = Path(__file__).parent / "fixtures" / "hrsa_hpsa" / "BCD_HPSA_FCT_DET_PC_sample.csv"


def _values(mv: pd.DataFrame, metric_id: str) -> dict[str, float | None]:
    sub = mv[mv["metric_id"] == metric_id]
    return {g: (None if pd.isna(v) else float(v)) for g, v in zip(sub["geo_id"], sub["value"], strict=True)}


@pytest.fixture(scope="module")
def tidy():
    return HpsaSource().transform({"detail": FIXTURE})


def test_columns_period_and_universe(tidy):
    mv = tidy.metric_values
    assert list(mv.columns) == METRIC_COLS
    assert set(mv["geo_level"]) == {"county"}
    assert set(mv["period"]) == {"2026-09"}  # YYYY-MM of the extract's record-create date
    assert set(mv["metric_id"]) == {"hpsa_primary_care_flag", "hpsa_score_max"}
    # 5-digit ids, territories (72001) dropped, unpadded La Paz padded to 04012
    assert mv["geo_id"].str.fullmatch(r"\d{5}").all()
    assert set(mv["geo_id"]) == {"04012", "04013", "06037", "48101", "48301", "48315", "48425", "48477"}
    assert not mv.duplicated(["geo_level", "geo_id", "metric_id", "period"]).any()


def test_flag_logic(tidy):
    flag = _values(tidy.metric_values, "hpsa_primary_care_flag")
    assert flag["04013"] == 1.0  # Designated
    assert flag["48101"] == 1.0  # Proposed For Withdrawal counts as active
    assert flag["48477"] == 1.0  # Proposed For Withdrawal + Withdrawn
    assert flag["48315"] == 1.0  # Designated + Withdrawn
    assert flag["48425"] == 0.0  # only Withdrawn -> explicit 0, not missing
    assert flag["48301"] == 1.0


def test_score_max_ignores_withdrawn_and_keeps_suppressed_null(tidy):
    score = _values(tidy.metric_values, "hpsa_score_max")
    assert score["04013"] == 21.0  # Withdrawn row with 25 must not win
    assert score["48315"] == 14.0  # Withdrawn 19 ignored
    assert score["48477"] == 14.0
    assert score["04012"] == 16.0
    assert score["48425"] is None  # no active component
    assert score["48301"] is None  # active but score suppressed -> NULL, never imputed


def test_sample_mode_restricts_to_az_tx():
    mv = HpsaSource(sample=True).transform({"detail": FIXTURE}).metric_values
    assert set(mv["geo_id"].str[:2]) == {"04", "48"}


def test_reads_latin1_and_bom(tmp_path: Path):
    text = FIXTURE.read_text(encoding="utf-8-sig")
    assert FIXTURE.read_bytes().startswith(b"\xef\xbb\xbf")  # fixture itself is UTF-8 with BOM
    latin = tmp_path / "latin.csv"
    latin.write_bytes(text.replace("Loving", "Lovíng").encode("cp1252"))
    df = read_hpsa_csv(latin)
    assert len(df) == 26
    assert "Common State County FIPS Code" in df.columns
