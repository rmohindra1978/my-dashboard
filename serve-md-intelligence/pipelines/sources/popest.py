"""Census Population Estimates, Vintage 2024 county characteristics by age and sex -> 5-year growth.

`cc-est2024-agesex-all.csv` has one row per county x YEAR code. YEAR 1 = 4/1/2020 estimates base,
YEAR 2..6 = 7/1/2020..7/1/2024 estimates. Growth compares YEAR 6 against the YEAR 1 base for total
population (POPESTIMATE) and 65+ (AGE65PLUS_TOT); state values are computed from summed county counts.
Percent metrics are stored on a 0-100 scale.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from backend.app.settings import settings
from pipelines.base import METRIC_COLS, Source, Tidy, download
from pipelines.fips import SAMPLE_STATE_FIPS, STATE_FIPS

URL = "https://www2.census.gov/programs-surveys/popest/datasets/2020-2024/counties/asrh/cc-est2024-agesex-all.csv"
BASE_YEAR_CODE = "1"  # 4/1/2020 estimates base
LATEST_YEAR_CODE = "6"  # 7/1/2024
COUNTS = {"POPESTIMATE": "pop_growth_5yr", "AGE65PLUS_TOT": "pop_65_plus_growth_5yr"}


def read_counties(path: Path, states: frozenset[str] | tuple[str, ...]) -> pd.DataFrame:
    df = pd.read_csv(
        path, dtype=str, encoding="latin-1", usecols=["SUMLEV", "STATE", "COUNTY", "YEAR", *COUNTS]
    )
    df = df[(df["SUMLEV"] == "050") & df["YEAR"].isin([BASE_YEAR_CODE, LATEST_YEAR_CODE])]
    df["geo_id"] = df["STATE"].str.zfill(2) + df["COUNTY"].str.zfill(3)
    df = df[df["geo_id"].str[:2].isin(states)]
    for c in COUNTS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df[["geo_id", "YEAR", *COUNTS]]


def growth(df: pd.DataFrame, level: str, period: str) -> pd.DataFrame:
    wide = df.pivot_table(index="geo_id", columns="YEAR", values=list(COUNTS), aggfunc="sum")
    frames = []
    for col, metric in COUNTS.items():
        base, latest = wide[(col, BASE_YEAR_CODE)], wide[(col, LATEST_YEAR_CODE)]
        value = (latest - base) / base.where(base > 0) * 100.0
        frames.append(
            pd.DataFrame(
                {
                    "geo_level": level,
                    "geo_id": value.index,
                    "metric_id": metric,
                    "period": period,
                    "value": value.values,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


class PopEstSource(Source):
    source_id = "popest"
    geo_levels = ("county", "state")

    def extract(self) -> dict[str, Path]:
        return {"agesex": download(URL, settings.raw_dir / self.source_id, "cc-est2024-agesex-all.csv")}

    def transform(self, raw: dict[str, Path]) -> Tidy:
        counties = read_counties(raw["agesex"], SAMPLE_STATE_FIPS if self.sample else STATE_FIPS)
        states = counties.assign(geo_id=counties["geo_id"].str[:2])
        mv = pd.concat(
            [growth(counties, "county", self.vintage), growth(states, "state", self.vintage)],
            ignore_index=True,
        )
        return Tidy(metric_values=mv[METRIC_COLS])
