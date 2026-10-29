"""ACS 2019-2023 5-year table-based Summary File -> demographic and socioeconomic metrics.

One pipe-delimited file per table (`acsdt5y2023-<table>.dat`) covers every geography; rows are keyed by
GEO_ID (e.g. 0500000US04013). `Geos20235YR.txt` supplies summary level, component and USPS state for
each GEO_ID, which is how ZCTAs (no state in their id) are restricted to the 50 states + DC.

Summary levels kept: 040 state, 050 county, 860 ZCTA, 160 place (component 00 only). Cells were checked
against ACS20235YR_Table_Shells.txt. ACS annotation sentinels (-666666666, -999999999, -888888888,
-222222222, -333333333, -555555555) and any other negative value become NULL; ratios with a zero
denominator are NULL. Percent metrics are stored on a 0-100 scale.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from backend.app.settings import settings
from pipelines.base import METRIC_COLS, Source, Tidy, download
from pipelines.sources.census_geo import ACS_DATA, ACS_DOC, STATES

log = logging.getLogger("pipelines.acs5")

SUMLEVELS = {"040": "state", "050": "county", "860": "zcta", "160": "place"}
SAMPLE_STATE_ABBR = ("AZ", "TX")


def _cells(table: str, *nums: int) -> list[str]:
    return [f"{table}_E{n:03d}" for n in nums]


B01001_65 = _cells("B01001", *range(20, 26), *range(44, 50))
B01001_75 = _cells("B01001", *range(23, 26), *range(47, 50))
B18101_DISAB = _cells("B18101", 16, 19, 35, 38)
B18101_UNIV = _cells("B18101", 15, 18, 34, 37)
B17001_BELOW = _cells("B17001", 15, 16, 29, 30)
B17001_ABOVE = _cells("B17001", 44, 45, 58, 59)
B15003_BA = _cells("B15003", 22, 23, 24, 25)

TABLES: dict[str, list[str]] = {
    "b01001": ["B01001_E001", *B01001_65],
    "b01002": ["B01002_E001"],
    "b11007": ["B11007_E002", "B11007_E003"],
    "b18101": [*B18101_UNIV, *B18101_DISAB],
    "b17001": [*B17001_BELOW, *B17001_ABOVE],
    "b23025": ["B23025_E003", "B23025_E005"],
    "b15003": ["B15003_E001", *B15003_BA],
    "b03002": ["B03002_E001", "B03002_E004", "B03002_E012"],
    "b19013": ["B19013_E001"],
    "b19301": ["B19301_E001"],
    "b25077": ["B25077_E001"],
    "b25064": ["B25064_E001"],
}


def table_url(table: str) -> str:
    return f"{ACS_DATA}acsdt5y2023-{table}.dat"


def read_geos(
    path: Path, states: tuple[str, ...] | frozenset[str], zctas: set[str] | None = None
) -> pd.DataFrame:
    """GEO_ID -> geo_level, geo_id for the kept summary levels inside `states` (USPS codes).

    ZCTA rows carry STUSAB "US" (or "PR"), so they are restricted to the warehouse ZCTA universe from
    census_geo when it is loaded, otherwise to every non-PR ZCTA (national) or none (sample).
    """
    g = pd.read_csv(
        path, sep="|", dtype=str, encoding="utf-8-sig", usecols=["STUSAB", "SUMLEVEL", "COMPONENT", "GEO_ID"]
    )
    g = g[g["SUMLEVEL"].isin(SUMLEVELS) & (g["COMPONENT"] == "00")]
    g = g.assign(geo_level=g["SUMLEVEL"].map(SUMLEVELS), geo_id=g["GEO_ID"].str.split("US").str[1])
    is_zcta = g["geo_level"] == "zcta"
    if zctas is not None:
        zcta_ok = g["geo_id"].isin(zctas)
    else:
        zcta_ok = (g["STUSAB"] == "US") & (len(states) > 2)
    g = g[(is_zcta & zcta_ok) | (~is_zcta & g["STUSAB"].isin(states))]
    return g.set_index("GEO_ID")[["geo_level", "geo_id"]]


def read_table(path: Path, columns: list[str], keep: pd.Index) -> pd.DataFrame:
    """Selected estimate columns for the kept GEO_IDs; sentinels / negatives -> NaN."""
    df = pd.read_csv(path, sep="|", dtype=str, encoding="utf-8-sig", usecols=["GEO_ID", *columns])
    df = df[df["GEO_ID"].isin(keep)].set_index("GEO_ID")
    out = df.apply(pd.to_numeric, errors="coerce")
    return out.where(out >= 0)


def _ratio(num: pd.Series, den: pd.Series, scale: float = 100.0) -> pd.Series:
    return num / den.where(den > 0) * scale


def _sum(w: pd.DataFrame, cols: list[str]) -> pd.Series:
    return w[cols].sum(axis=1, min_count=len(cols))  # any missing cell -> NULL, never a partial sum


def compute_metrics(w: pd.DataFrame) -> pd.DataFrame:
    """Wide ACS cells (index GEO_ID) -> wide metric frame following config/metrics.yaml derivations."""
    pop = w["B01001_E001"]
    pop65 = _sum(w, B01001_65)
    pov_below = _sum(w, B17001_BELOW)
    return pd.DataFrame(
        {
            "pop_total": pop,
            "pop_65_plus": pop65,
            "pct_65_plus": _ratio(pop65, pop),
            "pop_75_plus": _sum(w, B01001_75),
            "median_age": w["B01002_E001"],
            "pct_65_living_alone": _ratio(w["B11007_E003"], w["B11007_E002"]),
            "pct_65_plus_disability": _ratio(_sum(w, B18101_DISAB), _sum(w, B18101_UNIV)),
            "median_household_income": w["B19013_E001"],
            "per_capita_income": w["B19301_E001"],
            "poverty_rate_65_plus": _ratio(pov_below, pov_below + _sum(w, B17001_ABOVE)),
            "unemployment_rate": _ratio(w["B23025_E005"], w["B23025_E003"]),
            "median_home_value": w["B25077_E001"],
            "median_gross_rent": w["B25064_E001"],
            "pct_bachelors_plus": _ratio(_sum(w, B15003_BA), w["B15003_E001"]),
            "pct_hispanic": _ratio(w["B03002_E012"], w["B03002_E001"]),
            "pct_black": _ratio(w["B03002_E004"], w["B03002_E001"]),
        },
        index=w.index,
    )


class AcsSource(Source):
    source_id = "acs5"
    geo_levels = ("state", "county", "zcta", "place")

    zcta_universe: set[str] | None = None

    def run(self, con: duckdb.DuckDBPyConnection, rebuild_features: bool = True) -> int:
        ids = con.execute("SELECT geo_id FROM geo_units WHERE geo_level = 'zcta'").df()["geo_id"]
        self.zcta_universe = set(ids) if len(ids) else None
        if self.zcta_universe is None:
            log.warning("acs5: no ZCTAs in geo_units (run census_geo first); using all non-PR ZCTAs")
        return super().run(con, rebuild_features)

    def extract(self) -> dict[str, Path]:
        raw_dir = settings.raw_dir / self.source_id
        out = {"geos": download(ACS_DOC + "Geos20235YR.txt", raw_dir, "Geos20235YR.txt")}
        for table in TABLES:
            out[table] = download(table_url(table), raw_dir, f"acsdt5y2023-{table}.dat")
        return out

    def transform(self, raw: dict[str, Path]) -> Tidy:
        states = SAMPLE_STATE_ABBR if self.sample else frozenset(abbr for abbr, _ in STATES.values())
        geos = read_geos(raw["geos"], states, self.zcta_universe)
        wide = pd.concat([read_table(raw[t], cols, geos.index) for t, cols in TABLES.items()], axis=1)
        wide = wide.reindex(geos.index)
        metrics = compute_metrics(wide)
        expected = {m.id for m in self.registry.metrics if m.source == self.source_id}
        if set(metrics.columns) != expected:
            raise ValueError(f"acs5 metrics out of sync with registry: {set(metrics.columns) ^ expected}")
        long = metrics.join(geos).melt(
            id_vars=["geo_level", "geo_id"], var_name="metric_id", value_name="value"
        )
        long["value"] = long["value"].astype(float).replace([np.inf, -np.inf], np.nan)
        long["period"] = self.vintage
        log.info(
            "%s: %d rows for %s",
            self.source_id,
            len(long),
            long.groupby("geo_level")["geo_id"].nunique().to_dict(),
        )
        return Tidy(metric_values=long[METRIC_COLS].reset_index(drop=True))
