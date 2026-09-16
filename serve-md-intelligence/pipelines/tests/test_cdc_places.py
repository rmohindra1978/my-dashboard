"""cdc_places transform() on a 78-row fixture cut from the real Socrata export (no network).

Fixture edits vs. the published rows: a 2022 DIABETES pair for Maricopa with value 99.9 (must lose
to 2023), Maricopa's CHD pair copied to unpadded LocationID "1001" (Autauga AL), King County TX
OBESITY age-adjusted cell blanked with footnote "*" (crude fallback). The US row (LocationID 59),
Loving County TX (all cells suppressed) and an unregistered measure (TEETHLOST) are real.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from pipelines.base import METRIC_COLS
from pipelines.sources.cdc_places import MEASURES, PlacesSource

FIXTURE = Path(__file__).parent / "fixtures" / "cdc_places" / "places_county_sample.csv"


def _value(mv: pd.DataFrame, level: str, geo_id: str, metric_id: str) -> float | None:
    sub = mv[(mv["geo_level"] == level) & (mv["geo_id"] == geo_id) & (mv["metric_id"] == metric_id)]
    assert len(sub) == 1, (level, geo_id, metric_id, len(sub))
    v = sub["value"].iloc[0]
    return None if pd.isna(v) else float(v)


@pytest.fixture(scope="module")
def tidy():
    return PlacesSource().transform({"county": FIXTURE})


def test_shape_measures_and_ids(tidy):
    mv = tidy.metric_values
    assert list(mv.columns) == METRIC_COLS
    assert set(mv["metric_id"]) == set(MEASURES.values())  # TEETHLOST never leaks through
    assert set(mv["period"]) == {"2023"}
    county = mv[mv["geo_level"] == "county"]
    assert county["geo_id"].str.fullmatch(r"\d{5}").all()
    assert set(county["geo_id"]) == {"01001", "04012", "04013", "06037", "48269", "48301"}  # US row dropped
    assert not mv.duplicated(["geo_level", "geo_id", "metric_id", "period"]).any()


def test_age_adjusted_latest_year_and_complement(tidy):
    mv = tidy.metric_values
    assert (
        _value(mv, "county", "04013", "diabetes_prevalence") == 9.6
    )  # AgeAdjPrv 2023, not CrdPrv 10.6 / 2022 99.9
    assert _value(mv, "county", "04013", "hypertension_prevalence") == 28.6
    assert _value(mv, "county", "04013", "no_checkup_pct") == pytest.approx(100 - 72.0)
    assert _value(mv, "county", "01001", "chd_prevalence") == 5.0  # padded from "1001"


def test_suppression_and_crude_fallback(tidy):
    mv = tidy.metric_values
    assert _value(mv, "county", "48301", "diabetes_prevalence") is None  # suppressed -> NULL
    assert _value(mv, "county", "48269", "obesity_prevalence") == 37.8  # AgeAdj blank -> CrdPrv


def test_state_population_weighted(tidy):
    mv = tidy.metric_values
    # AZ = La Paz (11.5, 14,156 adults) + Maricopa (9.6, 3,572,375 adults)
    expected = (11.5 * 14156 + 9.6 * 3572375) / (14156 + 3572375)
    assert _value(mv, "state", "04", "diabetes_prevalence") == pytest.approx(expected)
    assert _value(mv, "state", "04", "no_checkup_pct") == pytest.approx(
        100 - (69.5 * 14156 + 72.0 * 3572375) / (14156 + 3572375)
    )
    # TX: Loving is all-NULL and drops out of the weighting; King alone remains
    assert _value(mv, "state", "48", "diabetes_prevalence") == pytest.approx(12.2)
    assert set(mv[mv["geo_level"] == "state"]["geo_id"]) == {"01", "04", "06", "48"}


def test_sample_mode_restricts_to_az_tx():
    mv = PlacesSource(sample=True).transform({"county": FIXTURE}).metric_values
    assert set(mv["geo_id"].str[:2]) == {"04", "48"}
