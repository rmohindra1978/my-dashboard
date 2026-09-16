"""CMS Medicare Geographic Variation PUF (National, State & County) -> Original Medicare utilization metrics.

Dataset 6219697b-8f6c-4164-bed4-cd9317c58ebc on data.cms.gov, rows with BENE_AGE_LVL = 'All'. One projected
file per (geo level, YEAR) is fetched through the keyless Data API (2014 -> latest release year, ~3.3k rows
each).

Emitted per YEAR (period = YEAR): medicare_spend_per_capita_std, ed_visits_per_1000, readmission_rate
(fraction -> percent) and ip_stays_per_1000. `avg_hcc_risk_score` is only emitted if the release carries
BENE_AVG_RISK_SCRE again - CMS dropped the average HCC risk score from the 2014-2024 PUF (see
docs/methodology.md). Suppressed cells (`*`) become NULL.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from backend.app.settings import settings
from pipelines.base import METRIC_COLS, Source, Tidy, suppressed_to_null
from pipelines.cms_api import download_years, keep_states_and_dc, read_pages

DATASET_ID = "6219697b-8f6c-4164-bed4-cd9317c58ebc"
FIRST_YEAR = 2014
# source column -> (metric_id, multiplier). Columns absent from the release are skipped (the API ignores
# unknown names in `column=`), which is how the risk score degrades gracefully.
METRIC_COLUMNS: dict[str, tuple[str, float]] = {
    "BENE_AVG_RISK_SCRE": ("avg_hcc_risk_score", 1.0),
    "TOT_MDCR_STDZD_PYMT_PC": ("medicare_spend_per_capita_std", 1.0),
    "ER_VISITS_PER_1000_BENES": ("ed_visits_per_1000", 1.0),
    "ACUTE_HOSP_READMSN_PCT": ("readmission_rate", 100.0),
    "IP_CVRD_STAYS_PER_1000_BENES": ("ip_stays_per_1000", 1.0),
}
COLUMNS = ["YEAR", "BENE_GEO_LVL", "BENE_GEO_CD", "BENE_AGE_LVL", *METRIC_COLUMNS]
LEVELS = {"State": "state", "County": "county"}
SAMPLE_STATES = ("04", "48")  # AZ, TX


class GeoVariationSource(Source):
    source_id = "cms_geo_variation"
    geo_levels = ("state", "county")

    def extract(self) -> dict[str, Path]:
        raw: dict[str, Path] = {}
        for api_level, level in LEVELS.items():
            raw.update(
                download_years(
                    DATASET_ID,
                    settings.raw_dir / self.source_id,
                    level,
                    {"BENE_AGE_LVL": "All", "BENE_GEO_LVL": api_level},
                    COLUMNS,
                    FIRST_YEAR,
                )
            )
        if not raw:
            raise RuntimeError("cms_geo_variation: the API returned no rows")
        return raw

    def transform(self, raw: dict[str, Path]) -> Tidy:
        df = read_pages(raw)
        df = df[(df["BENE_AGE_LVL"] == "All") & df["BENE_GEO_LVL"].isin(LEVELS)].copy()
        df["geo_level"] = df["BENE_GEO_LVL"].map(LEVELS)
        df["geo_id"] = df["BENE_GEO_CD"].str.strip()
        df = df[df["geo_id"].str.fullmatch(r"\d{2}|\d{5}")]
        df.loc[df["geo_level"] == "county", "geo_id"] = df["geo_id"].str.zfill(5)
        df = keep_states_and_dc(df, "geo_id")
        # county code 000 = state-level 'UNKNOWN' remainder
        df = df[~((df["geo_level"] == "county") & df["geo_id"].str[2:].isin(["000", "999"]))]
        if self.sample:
            df = df[df["geo_id"].str[:2].isin(SAMPLE_STATES)]
        df["period"] = df["YEAR"].str.strip()
        df = df.drop_duplicates(["geo_level", "geo_id", "period"])

        parts = []
        for col, (metric_id, mult) in METRIC_COLUMNS.items():
            if col not in df.columns:
                continue
            part = df[["geo_level", "geo_id", "period"]].copy()
            part["metric_id"] = metric_id
            part["value"] = suppressed_to_null(df[col]) * mult
            parts.append(part)
        out = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=METRIC_COLS)
        return Tidy(metric_values=out[METRIC_COLS].reset_index(drop=True))
