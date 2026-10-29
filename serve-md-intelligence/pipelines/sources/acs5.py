"""ACS 2019-2023 5-year table-based Summary File -> demographic, aging and socioeconomic metrics.

One pipe-delimited file per detailed table covers every summary level; rows are keyed by GEO_ID
(e.g. 0500000US04013). We keep state (040), county (050), ZCTA (860) and place (160) rows for the 50 states
+ DC and read only the estimate columns each metric needs. ACS annotation sentinels (-666666666,
-999999999, -888888888, -222222222, -333333333, -555555555) and any other negative estimate become NULL.

Cell references follow the 2023 table shells; see the `derivation` of each metric in config/metrics.yaml.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.csv as pacsv

from backend.app.settings import settings
from pipelines.base import METRIC_COLS, Source, Tidy, download
from pipelines.fips import SAMPLE_STATE_FIPS, STATE_FIPS, is_sample_zcta, is_us_zcta

log = logging.getLogger("pipelines.acs5")

BASE = "https://www2.census.gov/programs-surveys/acs/summary_file/2023/table-based-SF/data/5YRData"
# GEO_ID prefix = summary level + geographic component + "US" (ZCTAs use "860Z200US").
# Only whole geographies (component 00) are kept.
SUMLEVELS = {"0400000US": "state", "0500000US": "county", "860Z200US": "zcta", "1600000US": "place"}


def _cells(table: str, *nums: int) -> list[str]:
    return [f"{table}_E{n:03d}" for n in nums]


# B01001 sex by age: 65+ = male E020-E025, female E044-E049; 75+ = male E023-E025, female E047-E049.
AGE_65 = _cells("B01001", *range(20, 26), *range(44, 50))
AGE_75 = _cells("B01001", *range(23, 26), *range(47, 50))
# B18101 sex by age by disability: 65-74 / 75+ universes and "with a disability" cells, male + female.
DIS_UNIVERSE = _cells("B18101", 15, 18, 34, 37)
DIS_WITH = _cells("B18101", 16, 19, 35, 38)
# B17001 poverty by sex by age: 65-74 / 75+ below poverty (E015, E016, E029, E030) and at/above (E044, E045,
# E058, E059).
POV_BELOW = _cells("B17001", 15, 16, 29, 30)
POV_ABOVE = _cells("B17001", 44, 45, 58, 59)
BACHELORS_PLUS = _cells("B15003", 22, 23, 24, 25)


def _sum(df: pd.DataFrame, cols: list[str]) -> pd.Series:
    return df[cols].sum(axis=1, min_count=len(cols))


def _ratio(num: pd.Series, den: pd.Series, scale: float = 100.0) -> pd.Series:
    out = num / den.where(den > 0) * scale
    return out.replace([np.inf, -np.inf], np.nan)


# metric_id -> (columns needed, function of the wide estimate frame)
METRICS: dict[str, tuple[list[str], Callable[[pd.DataFrame], pd.Series]]] = {
    "pop_total": (["B01001_E001"], lambda d: d["B01001_E001"]),
    "pop_65_plus": (AGE_65, lambda d: _sum(d, AGE_65)),
    "pct_65_plus": (["B01001_E001", *AGE_65], lambda d: _ratio(_sum(d, AGE_65), d["B01001_E001"])),
    "pop_75_plus": (AGE_75, lambda d: _sum(d, AGE_75)),
    "median_age": (["B01002_E001"], lambda d: d["B01002_E001"]),
    "pct_65_living_alone": (
        ["B11007_E002", "B11007_E003"],
        lambda d: _ratio(d["B11007_E003"], d["B11007_E002"]),
    ),
    "pct_65_plus_disability": (
        DIS_UNIVERSE + DIS_WITH,
        lambda d: _ratio(_sum(d, DIS_WITH), _sum(d, DIS_UNIVERSE)),
    ),
    "median_household_income": (["B19013_E001"], lambda d: d["B19013_E001"]),
    "per_capita_income": (["B19301_E001"], lambda d: d["B19301_E001"]),
    "poverty_rate_65_plus": (
        POV_BELOW + POV_ABOVE,
        lambda d: _ratio(_sum(d, POV_BELOW), _sum(d, POV_BELOW) + _sum(d, POV_ABOVE)),
    ),
    "unemployment_rate": (
        ["B23025_E003", "B23025_E005"],
        lambda d: _ratio(d["B23025_E005"], d["B23025_E003"]),
    ),
    "median_home_value": (["B25077_E001"], lambda d: d["B25077_E001"]),
    "median_gross_rent": (["B25064_E001"], lambda d: d["B25064_E001"]),
    "pct_bachelors_plus": (
        ["B15003_E001", *BACHELORS_PLUS],
        lambda d: _ratio(_sum(d, BACHELORS_PLUS), d["B15003_E001"]),
    ),
    "pct_hispanic": (["B03002_E001", "B03002_E012"], lambda d: _ratio(d["B03002_E012"], d["B03002_E001"])),
    "pct_black": (["B03002_E001", "B03002_E004"], lambda d: _ratio(d["B03002_E004"], d["B03002_E001"])),
}


def needed_columns() -> dict[str, list[str]]:
    """table id (lower case, e.g. 'b01001') -> sorted estimate columns to read."""
    out: dict[str, set[str]] = {}
    for cols, _ in METRICS.values():
        for c in cols:
            out.setdefault(c.split("_")[0].lower(), set()).add(c)
    return {t: sorted(cs) for t, cs in sorted(out.items())}


def geo_from_geoid(geoid: pd.Series) -> pd.DataFrame:
    """'0500000US04013' -> geo_level 'county', geo_id '04013' (unknown summary levels -> NaN level)."""
    return pd.DataFrame({"geo_level": geoid.str[:9].map(SUMLEVELS), "geo_id": geoid.str[9:]})


def keep_mask(geo: pd.DataFrame, sample: bool) -> pd.Series:
    states = set(SAMPLE_STATE_FIPS) if sample else set(STATE_FIPS)
    is_zcta = geo["geo_level"] == "zcta"
    zcta_ok = geo["geo_id"].map(is_sample_zcta if sample else is_us_zcta).astype(bool)
    other_ok = geo["geo_level"].notna() & ~is_zcta & geo["geo_id"].str[:2].isin(states)
    return (is_zcta & zcta_ok) | other_ok


def read_table(path: Path, columns: list[str], sample: bool) -> pd.DataFrame:
    """Read GEO_ID + `columns` from one summary-file table; returns a frame indexed by (geo_level, geo_id)."""
    tbl = pacsv.read_csv(
        path,
        parse_options=pacsv.ParseOptions(delimiter="|"),
        convert_options=pacsv.ConvertOptions(
            include_columns=["GEO_ID", *columns],
            column_types={"GEO_ID": pa.string(), **{c: pa.float64() for c in columns}},
        ),
    )
    df = tbl.to_pandas()
    geo = geo_from_geoid(df["GEO_ID"])
    keep = keep_mask(geo, sample)
    vals = df.loc[keep, columns]
    vals = vals.where(vals >= 0)  # ACS sentinels are large negative numbers
    vals.index = pd.MultiIndex.from_frame(geo[keep])
    return vals


class AcsSource(Source):
    source_id = "acs5"
    geo_levels = ("state", "county", "zcta", "place")

    def extract(self) -> dict[str, Path]:
        dest = settings.raw_dir / self.source_id
        return {
            t: download(f"{BASE}/acsdt5y2023-{t}.dat", dest, f"acsdt5y2023-{t}.dat") for t in needed_columns()
        }

    def transform(self, raw: dict[str, Path]) -> Tidy:
        frames = [read_table(raw[t], cols, self.sample) for t, cols in needed_columns().items()]
        wide = pd.concat(frames, axis=1, join="outer")
        log.info("acs5: %s geographies", wide.index.get_level_values(0).value_counts().to_dict())
        out = []
        for metric_id, (_, fn) in METRICS.items():
            s = fn(wide).dropna()
            out.append(
                pd.DataFrame(
                    {
                        "geo_level": s.index.get_level_values(0),
                        "geo_id": s.index.get_level_values(1),
                        "metric_id": metric_id,
                        "period": self.vintage,
                        "value": s.to_numpy(),
                    }
                )
            )
        return Tidy(metric_values=pd.concat(out, ignore_index=True)[METRIC_COLS])
