"""CMS Doctors and Clinicians National Downloadable File -> primary-care supply by ZCTA and county.

Source: https://data.cms.gov/provider-data/dataset/mj5m-pzi6 (monthly refresh, ~3.4 M rows / ~840 MB CSV).
Each row is one clinician x enrollment x group x practice address; a clinician therefore appears once
per practice location. We keep only primary-care specialties, reduce to distinct (NPI, ZCTA) pairs and
count clinicians per ZCTA (ZIP treated as ZCTA) and, when the warehouse holds a ZCTA->county crosswalk,
per county (crosswalk-weighted distinct clinicians).

Emitted metrics (config/metrics.yaml, source `dac_clinicians`):
    pcp_count               distinct primary-care clinicians (IM, FM/FP, GP, geriatrics, NP, PA)
    pcp_physician_count     distinct primary-care physicians (IM, FM/FP, GP, geriatrics)
    large_group_pcp_share   share of pcp_count whose group (num_org_mem) has >= 50 members

`pcp_per_1000_65plus` / `pcp_per_10k_pop` are ratios against ACS population and are produced by the
derived-metrics step, not here.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import duckdb
import httpx
import pandas as pd
import pyarrow as pa
import pyarrow.csv as pacsv

from backend.app.settings import settings
from pipelines.base import METRIC_COLS, Source, Tidy, download, suppressed_to_null

log = logging.getLogger("pipelines.dac_clinicians")

METASTORE_URL = "https://data.cms.gov/provider-data/api/1/metastore/schemas/dataset/items/mj5m-pzi6"

PCP_PHYSICIAN_SPECIALTIES = frozenset(
    {"INTERNAL MEDICINE", "FAMILY PRACTICE", "FAMILY MEDICINE", "GENERAL PRACTICE", "GERIATRIC MEDICINE"}
)
PCP_APP_SPECIALTIES = frozenset({"NURSE PRACTITIONER", "PHYSICIAN ASSISTANT"})
PCP_SPECIALTIES = PCP_PHYSICIAN_SPECIALTIES | PCP_APP_SPECIALTIES
LARGE_GROUP_MIN_MEMBERS = 50
# geo_units is only trusted as the geography universe (to drop PO-box ZIPs and to emit explicit zeros for
# areas without any PCP) when it looks national; a fixture-only warehouse must not shrink a real load.
MIN_UNIVERSE = {"zcta": 10_000, "county": 3_000}

SAMPLE_STATES = ("AZ", "TX")
# 50 states + DC; territories (PR, VI, GU, AS, MP, PW ...) are dropped.
US_STATES = frozenset(
    """AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY
    NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY""".split()
)

RAW_COLUMNS = {
    "NPI": "npi",
    "pri_spec": "pri_spec",
    "num_org_mem": "num_org_mem",
    "State": "state",
    "ZIP Code": "zip",
}


def read_clinician_rows(path: Path, states: tuple[str, ...] | None = None) -> pd.DataFrame:
    """Stream the national CSV and return primary-care rows as (npi, pri_spec, num_org_mem, state, zcta).

    Only the five needed columns are decoded and every batch is filtered before it is kept, so peak
    memory stays around 1 GB for the full national file.
    """
    reader = pacsv.open_csv(
        path,
        read_options=pacsv.ReadOptions(block_size=32 << 20),
        convert_options=pacsv.ConvertOptions(
            include_columns=list(RAW_COLUMNS),
            column_types={c: pa.string() for c in RAW_COLUMNS},
            strings_can_be_null=True,
        ),
    )
    parts: list[pd.DataFrame] = []
    for batch in reader:
        df = batch.to_pandas().rename(columns=RAW_COLUMNS)
        df["pri_spec"] = df["pri_spec"].fillna("").str.strip().str.upper()
        df = df[df["pri_spec"].isin(PCP_SPECIALTIES)]
        if states:
            df = df[df["state"].isin(states)]
        if df.empty:
            continue
        parts.append(_normalise(df))
    if not parts:
        return pd.DataFrame(columns=["npi", "pri_spec", "num_org_mem", "state", "zcta"])
    return pd.concat(parts, ignore_index=True)


def _normalise(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(
        {
            "npi": df["npi"].fillna("").str.strip(),
            "pri_spec": df["pri_spec"],
            "num_org_mem": suppressed_to_null(df["num_org_mem"]),
            "state": df["state"].fillna("").str.strip().str.upper(),
            "zcta": df["zip"].fillna("").str.strip().str.replace(r"\D", "", regex=True).str[:5],
        }
    )
    out = out[(out["npi"].str.len() == 10) & (out["zcta"].str.len() == 5)]
    return out


def aggregate_zcta(rows: pd.DataFrame) -> pd.DataFrame:
    """Distinct-NPI counts per ZCTA -> geo_id, pcp_count, pcp_physician_count, large_group_pcp."""
    per = (
        rows.assign(
            physician=rows["pri_spec"].isin(PCP_PHYSICIAN_SPECIALTIES),
            large=rows["num_org_mem"].fillna(0) >= LARGE_GROUP_MIN_MEMBERS,
        )
        .groupby(["zcta", "npi"], as_index=False)
        .agg(physician=("physician", "max"), large=("large", "max"))
    )
    agg = per.groupby("zcta").agg(
        pcp_count=("npi", "size"),
        pcp_physician_count=("physician", "sum"),
        large_group_pcp=("large", "sum"),
    )
    return agg.reset_index().rename(columns={"zcta": "geo_id"})


def aggregate_county(rows: pd.DataFrame, crosswalk: pd.DataFrame) -> pd.DataFrame:
    """Crosswalk-weighted distinct-NPI counts per county.

    A clinician practising in several ZCTAs of the same county is counted once for that county (the
    largest ZCTA->county weight among its locations is used). ZCTAs that straddle counties contribute
    fractionally according to the crosswalk weight; counts are rounded to whole clinicians at the end.
    """
    xw = crosswalk.loc[
        (crosswalk["from_level"] == "zcta") & (crosswalk["to_level"] == "county"),
        ["from_id", "to_id", "weight"],
    ].rename(columns={"from_id": "zcta", "to_id": "county"})
    xw = xw[xw["weight"] > 0]
    per_loc = rows.assign(
        physician=rows["pri_spec"].isin(PCP_PHYSICIAN_SPECIALTIES),
        large=rows["num_org_mem"].fillna(0) >= LARGE_GROUP_MIN_MEMBERS,
    )[["npi", "zcta", "physician", "large"]].drop_duplicates()
    joined = per_loc.merge(xw, on="zcta", how="inner")
    per = joined.groupby(["county", "npi"], as_index=False).agg(
        weight=("weight", "max"), physician=("physician", "max"), large=("large", "max")
    )
    per["phys_w"] = per["weight"] * per["physician"]
    per["large_w"] = per["weight"] * per["large"]
    agg = per.groupby("county").agg(
        pcp_count=("weight", "sum"),
        pcp_physician_count=("phys_w", "sum"),
        large_group_pcp=("large_w", "sum"),
    )
    return agg.reset_index().rename(columns={"county": "geo_id"})


def to_metric_values(
    agg: pd.DataFrame, geo_level: str, period: str, universe: set[str] | None = None
) -> pd.DataFrame:
    """Wide counts -> long metric rows.

    With a `universe`, every unit in it is emitted (0 PCPs is a real observation, not missing data) and
    units outside it are dropped; without one only units that have at least one PCP appear.
    `large_group_pcp_share` is NULL where there is no PCP to take a share of.
    """
    if universe is not None:
        agg = agg.set_index("geo_id").reindex(sorted(universe), fill_value=0.0).reset_index()
    else:
        agg = agg[agg["pcp_count"] > 0].copy()
    if agg.empty:
        return pd.DataFrame(columns=METRIC_COLS)
    share = (agg["large_group_pcp"] / agg["pcp_count"].where(agg["pcp_count"] > 0)).clip(upper=1.0)
    frames = [
        pd.DataFrame(
            {
                "geo_level": geo_level,
                "geo_id": agg["geo_id"],
                "metric_id": metric,
                "period": period,
                "value": values.astype(float),
            }
        )
        for metric, values in (
            ("pcp_count", agg["pcp_count"].round()),
            ("pcp_physician_count", agg["pcp_physician_count"].round()),
            ("large_group_pcp_share", share),
        )
    ]
    return pd.concat(frames, ignore_index=True)[METRIC_COLS]


class CliniciansSource(Source):
    source_id = "dac_clinicians"
    geo_levels = ("zcta", "county")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filled from the warehouse in run(); tests may set them directly.
        self.crosswalk: pd.DataFrame | None = None
        self.universe: dict[str, set[str]] = {}

    # ------------------------------------------------------------------ extract
    def extract(self) -> dict[str, Path]:
        raw_dir = settings.raw_dir / self.source_id
        meta = self._dataset_metadata(raw_dir)
        released = meta["released"]
        meta_path = raw_dir / f"metadata_{released}.json"
        if not meta_path.exists():
            raw_dir.mkdir(parents=True, exist_ok=True)
            meta_path.write_text(json.dumps(meta, indent=2))
        csv_path = download(meta["downloadURL"], raw_dir, f"DAC_NationalDownloadableFile_{released}.csv")
        return {"clinicians": csv_path, "metadata": meta_path}

    @staticmethod
    def _dataset_metadata(raw_dir: Path) -> dict[str, str]:
        """Resolve the current distribution URL + release date from the CMS metastore.

        Falls back to the newest cached metadata file when the metastore is unreachable, so an
        already-downloaded file can still be (re)loaded offline.
        """
        try:
            resp = httpx.get(METASTORE_URL, timeout=60.0, follow_redirects=True)
            resp.raise_for_status()
            doc = resp.json()
            dist = doc["distribution"][0]
            return {
                "identifier": doc.get("identifier", "mj5m-pzi6"),
                "released": doc.get("released") or doc.get("modified"),
                "modified": doc.get("modified", ""),
                "downloadURL": dist["downloadURL"],
            }
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            cached = sorted(raw_dir.glob("metadata_*.json"))
            if not cached:
                raise RuntimeError(f"cannot reach CMS metastore and no cached metadata in {raw_dir}") from exc
            log.warning("metastore unavailable (%s); using cached %s", exc, cached[-1].name)
            return json.loads(cached[-1].read_text())

    # ------------------------------------------------------------------ transform
    def transform(self, raw: dict[str, Path]) -> Tidy:
        period = self.period_from_metadata(raw["metadata"])
        states = SAMPLE_STATES if self.sample else None
        rows = read_clinician_rows(raw["clinicians"], states)
        rows = rows[rows["state"].isin(US_STATES)]
        log.info(
            "%s: %d primary-care location rows, %d distinct NPIs",
            self.source_id,
            len(rows),
            rows["npi"].nunique(),
        )

        zctas = self.universe.get("zcta")
        if zctas:
            before = rows["zcta"].nunique()
            rows = rows[rows["zcta"].isin(zctas)]
            log.info("%s: kept %d of %d ZIPs that are ZCTAs", self.source_id, rows["zcta"].nunique(), before)

        frames = [to_metric_values(aggregate_zcta(rows), "zcta", period, zctas)]
        if self.crosswalk is not None and not self.crosswalk.empty:
            county = aggregate_county(rows, self.crosswalk)
            frames.append(to_metric_values(county, "county", period, self.universe.get("county")))
        else:
            log.warning(
                "%s: geo_crosswalk has no zcta->county rows; emitting ZCTA level only "
                "(run census_geo first for county aggregates)",
                self.source_id,
            )
        return Tidy(metric_values=pd.concat(frames, ignore_index=True))

    @staticmethod
    def period_from_metadata(path: Path) -> str:
        meta = json.loads(Path(path).read_text())
        released = meta.get("released") or meta.get("modified")
        return str(released)[:7]  # YYYY-MM of the monthly refresh

    # ------------------------------------------------------------------ run
    def run(self, con: duckdb.DuckDBPyConnection, rebuild_features: bool = True) -> int:
        self.crosswalk = con.execute(
            "SELECT from_level, from_id, to_level, to_id, weight FROM geo_crosswalk "
            "WHERE from_level = 'zcta' AND to_level = 'county'"
        ).df()
        units = con.execute(
            "SELECT geo_level, geo_id FROM geo_units WHERE geo_level IN ('zcta', 'county')"
        ).df()
        self.universe = {
            level: set(ids)
            for level, ids in units.groupby("geo_level")["geo_id"]
            if len(ids) >= MIN_UNIVERSE[level]
        }
        return super().run(con, rebuild_features)
