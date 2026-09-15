"""CDC PLACES county estimates (Socrata swc5-untb) -> Health Need prevalence metrics.

One CSV export (all years/measures/value types) is read in chunks; only the registered measures are
kept. For each measure the latest `Year` in the file is used, age-adjusted prevalence (`AgeAdjPrv`)
is preferred and crude prevalence (`CrdPrv`) fills in when the age-adjusted cell is suppressed.
`CHECKUP` is published as the share WITH a routine checkup, so `no_checkup_pct = 100 - CHECKUP`.

State values are an adult-population-weighted mean of the county estimates (PLACES publishes no
state rows in this dataset); they are approximate and flagged as such in docs/methodology.md.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from backend.app.settings import settings
from pipelines.base import METRIC_COLS, Source, Tidy, download, suppressed_to_null
from pipelines.fips import in_states, pad_fips

log = logging.getLogger("pipelines.cdc_places")

URL = "https://data.cdc.gov/api/views/swc5-untb/rows.csv?accessType=DOWNLOAD"
FILENAME = "places_county_swc5-untb.csv"

MEASURES: dict[str, str] = {
    "DIABETES": "diabetes_prevalence",
    "OBESITY": "obesity_prevalence",
    "BPHIGH": "hypertension_prevalence",
    "CHD": "chd_prevalence",
    "COPD": "copd_prevalence",
    "GHLTH": "fair_poor_health_pct",
    "CHECKUP": "no_checkup_pct",
}
COMPLEMENT_MEASURES = frozenset({"CHECKUP"})  # published as "% with", metric is "% without"
VALUE_TYPES = ("AgeAdjPrv", "CrdPrv")

USECOLS = [
    "Year",
    "LocationID",
    "MeasureId",
    "DataValueTypeID",
    "Data_Value",
    "TotalPopulation",
    "TotalPop18plus",
]
CHUNK_ROWS = 200_000


def read_places_csv(path: Path, sample: bool = False) -> pd.DataFrame:
    """Stream the export and keep only registered measures, 5-digit county ids and the two value types."""
    parts: list[pd.DataFrame] = []
    for chunk in pd.read_csv(
        path, dtype=str, usecols=lambda c: c in USECOLS, chunksize=CHUNK_ROWS, low_memory=False
    ):
        keep = chunk["MeasureId"].isin(MEASURES) & chunk["DataValueTypeID"].isin(VALUE_TYPES)
        chunk = chunk[keep]
        if chunk.empty:
            continue
        chunk = chunk[chunk["LocationID"].notna()].copy()
        chunk["geo_id"] = pad_fips(chunk["LocationID"], 5)
        chunk = chunk[chunk["geo_id"].str.fullmatch(r"\d{5}") & in_states(chunk["geo_id"], sample)]
        parts.append(chunk)
    if not parts:
        raise ValueError(f"cdc_places: no rows for registered measures found in {path.name}")
    df = pd.concat(parts, ignore_index=True)
    df["year"] = pd.to_numeric(df["Year"], errors="coerce").astype("Int64")
    df["value"] = suppressed_to_null(df["Data_Value"])
    for col in ("TotalPopulation", "TotalPop18plus"):
        df[col] = suppressed_to_null(df[col]) if col in df.columns else float("nan")
    return df


def latest_year_per_measure(df: pd.DataFrame) -> pd.DataFrame:
    latest = df.groupby("MeasureId")["year"].transform("max")
    return df[df["year"] == latest]


def pick_value_type(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (geo_id, MeasureId): age-adjusted when available, else crude."""
    key = ["geo_id", "MeasureId", "year"]
    sub = df.drop_duplicates(key + ["DataValueTypeID"])
    wide = sub.set_index(key + ["DataValueTypeID"])["value"].unstack("DataValueTypeID").reset_index()
    for col in ("AgeAdjPrv", "CrdPrv"):
        if col not in wide.columns:
            wide[col] = float("nan")
    wide["value"] = wide["AgeAdjPrv"].where(wide["AgeAdjPrv"].notna(), wide["CrdPrv"])
    wide["value_type"] = "AgeAdjPrv"
    wide.loc[wide["AgeAdjPrv"].isna() & wide["CrdPrv"].notna(), "value_type"] = "CrdPrv"
    return wide[["geo_id", "MeasureId", "year", "value", "value_type"]]


def state_weighted(county: pd.DataFrame, weights: pd.DataFrame) -> pd.DataFrame:
    """Adult-population-weighted state mean of county values; TotalPopulation if TotalPop18plus is absent."""
    w = weights.copy()
    w["weight"] = w["TotalPop18plus"].where(w["TotalPop18plus"].notna(), w["TotalPopulation"])
    merged = county.merge(w[["geo_id", "weight"]], on="geo_id", how="left")
    merged = merged[merged["value"].notna() & merged["weight"].notna() & (merged["weight"] > 0)].copy()
    if merged.empty:
        return merged.iloc[0:0][["geo_id", "MeasureId", "year", "value"]]
    merged["state"] = merged["geo_id"].str[:2]
    merged["wv"] = merged["value"] * merged["weight"]
    g = merged.groupby(["state", "MeasureId", "year"], as_index=False)[["wv", "weight"]].sum()
    g["value"] = g["wv"] / g["weight"]
    return g.rename(columns={"state": "geo_id"})[["geo_id", "MeasureId", "year", "value"]]


class PlacesSource(Source):
    source_id = "cdc_places"
    geo_levels = ("state", "county")

    def extract(self) -> dict[str, Path]:
        return {"county": download(URL, settings.raw_dir / self.source_id, FILENAME)}

    def transform(self, raw: dict[str, Path]) -> Tidy:
        df = latest_year_per_measure(read_places_csv(raw["county"], self.sample))
        county = pick_value_type(df)
        n_crude = int((county["value_type"] == "CrdPrv").sum())
        if n_crude:
            log.warning("cdc_places: %d county cells fell back to crude prevalence", n_crude)

        weights = df.sort_values("year").drop_duplicates("geo_id", keep="last")[
            ["geo_id", "TotalPopulation", "TotalPop18plus"]
        ]
        state = state_weighted(county, weights)

        county = county.assign(geo_level="county")
        state = state.assign(geo_level="state")
        out = pd.concat([county[state.columns], state], ignore_index=True)
        out["metric_id"] = out["MeasureId"].map(MEASURES)
        comp = out["MeasureId"].isin(COMPLEMENT_MEASURES)
        out.loc[comp, "value"] = 100.0 - out.loc[comp, "value"]
        out["period"] = out["year"].astype(str)
        log.info(
            "cdc_places: %d county rows (%d counties), %d state rows; years %s",
            int((out["geo_level"] == "county").sum()),
            county["geo_id"].nunique(),
            int((out["geo_level"] == "state").sum()),
            sorted(out["period"].unique()),
        )
        return Tidy(metric_values=out[METRIC_COLS].reset_index(drop=True))
