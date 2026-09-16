"""CMS Medicare Monthly Enrollment -> medicare_demand metrics (state + county).

Dataset d7fabe1e-d19b-4333-9eff-e80e0643f2fd on data.cms.gov. Only the annual-average rows (MONTH = 'Year')
are used; one file per (geo level, YEAR) is fetched through the keyless Data API with a column projection, so
the whole history (2013 -> latest) is ~3.3k rows x 10 columns per year.

Emitted per YEAR (period = YEAR): medicare_benes_total, medicare_benes_aged, original_medicare_benes,
medicare_ma_benes, ma_penetration_pct, dual_eligible_pct and, when YEAR-5 exists, medicare_benes_growth_5yr.
market_features keeps the latest period; earlier periods feed /history/<metric>.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from backend.app.settings import settings
from pipelines.base import METRIC_COLS, Source, Tidy, suppressed_to_null
from pipelines.cms_api import download_years, keep_states_and_dc, read_pages

DATASET_ID = "d7fabe1e-d19b-4333-9eff-e80e0643f2fd"
FIRST_YEAR = 2013
COLUMNS = [
    "YEAR",
    "MONTH",
    "BENE_GEO_LVL",
    "BENE_STATE_ABRVTN",
    "BENE_FIPS_CD",
    "TOT_BENES",
    "ORGNL_MDCR_BENES",
    "MA_AND_OTH_BENES",
    "AGED_TOT_BENES",
    "DUAL_TOT_BENES",
]
LEVELS = {"State": "state", "County": "county"}
SAMPLE_STATES = ("04", "48")  # AZ, TX

DIRECT = {
    "medicare_benes_total": "TOT_BENES",
    "medicare_benes_aged": "AGED_TOT_BENES",
    "original_medicare_benes": "ORGNL_MDCR_BENES",
    "medicare_ma_benes": "MA_AND_OTH_BENES",
}


class EnrollmentSource(Source):
    source_id = "cms_enrollment"
    geo_levels = ("state", "county")

    def extract(self) -> dict[str, Path]:
        raw: dict[str, Path] = {}
        for api_level, level in LEVELS.items():
            raw.update(
                download_years(
                    DATASET_ID,
                    settings.raw_dir / self.source_id,
                    level,
                    {"MONTH": "Year", "BENE_GEO_LVL": api_level},
                    COLUMNS,
                    FIRST_YEAR,
                )
            )
        if not raw:
            raise RuntimeError("cms_enrollment: the API returned no annual rows")
        return raw

    def transform(self, raw: dict[str, Path]) -> Tidy:
        df = read_pages(raw)
        df = df[(df["MONTH"] == "Year") & df["BENE_GEO_LVL"].isin(LEVELS)].copy()
        df["geo_level"] = df["BENE_GEO_LVL"].map(LEVELS)
        df["geo_id"] = df["BENE_FIPS_CD"].str.strip().str.zfill(2)
        df.loc[df["geo_level"] == "county", "geo_id"] = df["geo_id"].str.zfill(5)
        df = keep_states_and_dc(df, "geo_id")
        # 'Unknown' county rows carry a 999 county code
        df = df[~((df["geo_level"] == "county") & df["geo_id"].str[2:].isin(["999", "000"]))]
        if self.sample:
            df = df[df["geo_id"].str[:2].isin(SAMPLE_STATES)]
        df["period"] = df["YEAR"].str.strip()
        for col in ("TOT_BENES", "ORGNL_MDCR_BENES", "MA_AND_OTH_BENES", "AGED_TOT_BENES", "DUAL_TOT_BENES"):
            df[col] = suppressed_to_null(df[col])
        df = df.drop_duplicates(["geo_level", "geo_id", "period"])

        tot = df["TOT_BENES"].where(df["TOT_BENES"] > 0)
        df["ma_penetration_pct"] = df["MA_AND_OTH_BENES"] / tot * 100
        df["dual_eligible_pct"] = df["DUAL_TOT_BENES"] / tot * 100

        base = df[["geo_level", "geo_id", "period", "TOT_BENES"]].copy()
        base["period"] = (pd.to_numeric(base["period"]) + 5).astype(int).astype(str)
        base = base.rename(columns={"TOT_BENES": "_tot_5yr_ago"})
        df = df.merge(base, on=["geo_level", "geo_id", "period"], how="left")
        prev = df["_tot_5yr_ago"].where(df["_tot_5yr_ago"] > 0)
        df["medicare_benes_growth_5yr"] = (df["TOT_BENES"] / prev - 1) * 100

        metrics = {
            **DIRECT,
            "ma_penetration_pct": "ma_penetration_pct",
            "dual_eligible_pct": "dual_eligible_pct",
        }
        long = df.melt(
            id_vars=["geo_level", "geo_id", "period"],
            value_vars=list(metrics.values()),
            var_name="metric_id",
            value_name="value",
        )
        long["metric_id"] = long["metric_id"].map({v: k for k, v in metrics.items()})
        growth = df.loc[df["_tot_5yr_ago"].notna(), ["geo_level", "geo_id", "period"]].copy()
        growth["metric_id"] = "medicare_benes_growth_5yr"
        growth["value"] = df.loc[growth.index, "medicare_benes_growth_5yr"]
        out = pd.concat([long, growth], ignore_index=True)
        out["value"] = out["value"].replace([np.inf, -np.inf], np.nan).astype(float)
        return Tidy(metric_values=out[METRIC_COLS].reset_index(drop=True))
