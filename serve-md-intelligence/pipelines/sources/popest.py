"""Census Population Estimates (Vintage 2024) county characteristics -> population growth.

cc-est2024-agesex-all.csv has one row per county x YEAR code: 1 = 4/1/2020 estimates base,
2..6 = 7/1/2020..7/1/2024. Growth compares the latest estimate (YEAR 6) with the April 2020 base (YEAR 1),
i.e. ~4.25 years; the registry names it "5yr" for consistency with the other growth metrics. States are the
sum of their counties (the file covers the 50 states + DC only).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from backend.app.settings import settings
from pipelines.base import METRIC_COLS, Source, Tidy, download, suppressed_to_null
from pipelines.fips import SAMPLE_STATE_FIPS, STATE_FIPS

URL = "https://www2.census.gov/programs-surveys/popest/datasets/2020-2024/counties/asrh/cc-est2024-agesex-all.csv"
BASE_YEAR, LATEST_YEAR = "1", "6"
COLUMNS = {"POPESTIMATE": "pop_growth_5yr", "AGE65PLUS_TOT": "pop_65_plus_growth_5yr"}


def growth(frame: pd.DataFrame, key: str) -> pd.DataFrame:
    """frame: key, YEAR, value columns -> key + growth % per COLUMNS metric."""
    base = frame[frame["YEAR"] == BASE_YEAR].groupby(key)[list(COLUMNS)].sum(min_count=1)
    latest = frame[frame["YEAR"] == LATEST_YEAR].groupby(key)[list(COLUMNS)].sum(min_count=1)
    pct = (latest / base.where(base > 0) - 1) * 100
    return pct.rename(columns=COLUMNS)


class PopEstSource(Source):
    source_id = "popest"
    geo_levels = ("county", "state")

    def extract(self) -> dict[str, Path]:
        return {"agesex": download(URL, settings.raw_dir / self.source_id, URL.rsplit("/", 1)[-1])}

    def transform(self, raw: dict[str, Path]) -> Tidy:
        df = pd.read_csv(
            raw["agesex"], dtype=str, encoding="latin-1", usecols=["STATE", "COUNTY", "YEAR", *COLUMNS]
        )
        states = SAMPLE_STATE_FIPS if self.sample else STATE_FIPS
        df["STATE"] = df["STATE"].str.zfill(2)
        df = df[df["STATE"].isin(states)].copy()
        df["county"] = df["STATE"] + df["COUNTY"].str.zfill(3)
        for c in COLUMNS:
            df[c] = suppressed_to_null(df[c])
        out = []
        for level, key in (("county", "county"), ("state", "STATE")):
            g = growth(df, key)
            for metric_id in COLUMNS.values():
                s = g[metric_id].dropna()
                out.append(
                    pd.DataFrame(
                        {
                            "geo_level": level,
                            "geo_id": s.index,
                            "metric_id": metric_id,
                            "period": self.vintage,
                            "value": s.to_numpy(),
                        }
                    )
                )
        return Tidy(metric_values=pd.concat(out, ignore_index=True)[METRIC_COLS])
