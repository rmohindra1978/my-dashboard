"""Census geography backbone: geo_units, geo_crosswalk and simplified boundaries.

Inputs (all public, keyless, cached under data/raw/census_geo/):
    2023 Gazetteer files          counties / ZCTAs / places: names, internal points, land area
    2020 ZCTA-county relationship ZCTA -> county land-area shares
    2023 CBSA delineation list 1  county -> CBSA code/title
    Cartographic boundary 1:500k  state / county / place (2023) and ZCTA (2020; no 2023 ZCTA CB file)

Outputs
    geo_units      state, county, ZCTA, place for the 50 states + DC (territories dropped)
    geo_crosswalk  zcta->county (land-area share), place->county (polygon-area share), county->state (1.0)
    geo_boundaries one simplified GeoJSON geometry per unit

Connecticut replaced its 8 counties with 9 planning regions in 2022. The 2023 gazetteer and boundaries use
the planning regions while the 2020 relationship file still uses the old counties, so CT ZCTA->county
shares are computed from polygon overlap against the 2023 county layer instead.

`pop_density` (registered under this source) needs ACS population and is computed by pipelines.derived.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import shapefile
import shapely

from backend.app.settings import settings
from pipelines.base import CROSSWALK_COLS, GEO_UNIT_COLS, Source, Tidy, download
from pipelines.fips import SAMPLE_STATE_FIPS, STATE_FIPS, is_sample_zcta, is_us_zcta

log = logging.getLogger("pipelines.census_geo")

GAZ = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer"
CB = "https://www2.census.gov/geo/tiger"
URLS = {
    "gaz_counties": f"{GAZ}/2023_Gaz_counties_national.zip",
    "gaz_zcta": f"{GAZ}/2023_Gaz_zcta_national.zip",
    "gaz_place": f"{GAZ}/2023_Gaz_place_national.zip",
    "rel_zcta_county": "https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/tab20_zcta520_county20_natl.txt",
    "cbsa": "https://www2.census.gov/programs-surveys/metro-micro/geographies/reference-files/2023/delineation-files/list1_2023.xlsx",
    "shp_state": f"{CB}/GENZ2023/shp/cb_2023_us_state_500k.zip",
    "shp_county": f"{CB}/GENZ2023/shp/cb_2023_us_county_500k.zip",
    "shp_place": f"{CB}/GENZ2023/shp/cb_2023_us_place_500k.zip",
    "shp_zcta": f"{CB}/GENZ2020/shp/cb_2020_us_zcta520_500k.zip",
}

SQ_M_PER_SQ_MI = 2_589_988.110336
# Douglas-Peucker tolerance in degrees (~1 km at 0.01) and output precision per level.
SIMPLIFY_TOLERANCE = {"state": 0.01, "county": 0.005, "place": 0.002, "zcta": 0.003}
COORD_GRID = 1e-4
MIN_PLACE_SHARE = 0.001  # place->county slivers below 0.1% of the place area are boundary noise

_PLACE_SUFFIX = re.compile(
    r"\s+(city and borough|metropolitan government|metro government|consolidated government|"
    r"unified government|urban county|zona urbana|comunidad|municipality|corporation|plantation|"
    r"township|borough|village|town|city|CDP)$"
)
_BALANCE = re.compile(r"\s+\(balance\)$")


def place_display_name(name: str) -> str:
    """Strip the legal suffix: 'Phoenix city' -> 'Phoenix', 'X (balance)' -> 'X'."""
    out = _BALANCE.sub("", str(name).strip())
    out = _PLACE_SUFFIX.sub("", out)
    return out or str(name).strip()


def read_gazetteer(path: Path) -> pd.DataFrame:
    """Gazetteer .txt (tab-delimited, padded header) directly or inside its .zip."""
    if Path(path).suffix == ".zip":
        with zipfile.ZipFile(path) as zf:
            data = zf.read(next(n for n in zf.namelist() if n.endswith(".txt")))
    else:
        data = Path(path).read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    df = pd.read_csv(io.StringIO(text), sep="\t", dtype=str)
    df.columns = [c.strip() for c in df.columns]
    return df.apply(lambda s: s.str.strip())


def read_shapes(path: Path, id_field: str, keep: set[str] | None = None) -> tuple[pd.DataFrame, np.ndarray]:
    """Shapefile (zip or .shp) -> (attribute frame, shapely geometry array) aligned by row."""
    with shapefile.Reader(str(path)) as r:
        fields = [f[0] for f in r.fields[1:]]
        recs, geoms = [], []
        for sr in r.iterShapeRecords():
            rec = dict(zip(fields, sr.record, strict=True))
            if keep is not None and str(rec[id_field]) not in keep:
                continue
            recs.append(rec)
            geoms.append(shapely.geometry.shape(sr.shape.__geo_interface__))
    attrs = pd.DataFrame(recs, columns=fields)
    attrs[id_field] = attrs[id_field].astype(str)
    return attrs, np.array(geoms, dtype=object)


def read_cbsa(path: Path) -> pd.DataFrame:
    """Delineation list 1 -> county_fips, cbsa_code, cbsa_name (header on the 3rd row, footnotes dropped)."""
    df = pd.read_excel(path, header=2, dtype=str)
    df = df.dropna(subset=["FIPS State Code", "FIPS County Code", "CBSA Code"])
    df = df[df["FIPS State Code"].str.fullmatch(r"\d+")]
    county = df["FIPS State Code"].str.zfill(2) + df["FIPS County Code"].str.zfill(3)
    return pd.DataFrame(
        {
            "county_fips": county,
            "cbsa_code": df["CBSA Code"].str.strip(),
            "cbsa_name": df["CBSA Title"].str.strip(),
        }
    ).drop_duplicates("county_fips")


def overlap_shares(
    src_ids: np.ndarray, src_geoms: np.ndarray, dst_ids: np.ndarray, dst_geoms: np.ndarray, min_share: float
) -> pd.DataFrame:
    """Area share of each source polygon in each destination polygon (planar degrees; fine for shares)."""
    if len(src_geoms) == 0 or len(dst_geoms) == 0:
        return pd.DataFrame(columns=["from_id", "to_id", "weight"])
    src_geoms = shapely.make_valid(src_geoms)
    dst_geoms = shapely.make_valid(dst_geoms)
    tree = shapely.STRtree(dst_geoms)
    si, di = tree.query(src_geoms, predicate="intersects")
    area = shapely.area(shapely.intersection(src_geoms[si], dst_geoms[di]))
    df = pd.DataFrame({"from_id": src_ids[si], "to_id": dst_ids[di], "area": area})
    df = df[df["area"] > 0]
    df["weight"] = df["area"] / df.groupby("from_id")["area"].transform("sum")
    df = df[df["weight"] >= min_share]
    df["weight"] = df["weight"] / df.groupby("from_id")["weight"].transform("sum")
    return df[["from_id", "to_id", "weight"]].reset_index(drop=True)


def to_geojson(geoms: np.ndarray, tolerance: float) -> np.ndarray:
    """Simplify + snap to a 1e-4 degree grid; falls back to unsnapped geometry if snapping collapses it."""
    simple = shapely.simplify(geoms, tolerance, preserve_topology=True)
    snapped = shapely.set_precision(simple, COORD_GRID)
    out = np.where(shapely.is_empty(snapped), simple, snapped)
    return shapely.to_geojson(out)


class CensusGeoSource(Source):
    source_id = "census_geo"
    geo_levels = ("state", "county", "zcta", "place")

    # ------------------------------------------------------------------ extract
    def extract(self) -> dict[str, Path]:
        dest = settings.raw_dir / self.source_id
        return {key: download(url, dest, url.rsplit("/", 1)[-1]) for key, url in URLS.items()}

    # ------------------------------------------------------------------ transform
    def transform(self, raw: dict[str, Path]) -> Tidy:
        states_keep = set(SAMPLE_STATE_FIPS) if self.sample else set(STATE_FIPS)
        cbsa = read_cbsa(raw["cbsa"]).set_index("county_fips")

        # ---- states
        st_attrs, st_geoms = read_shapes(raw["shp_state"], "GEOID", states_keep)
        rep = shapely.point_on_surface(st_geoms) if len(st_geoms) else np.array([])
        states = pd.DataFrame(
            {
                "geo_level": "state",
                "geo_id": st_attrs["GEOID"],
                "name": st_attrs["NAME"],
                "state_fips": st_attrs["GEOID"],
                "state_abbr": st_attrs["STUSPS"],
                "lat": shapely.get_y(rep) if len(rep) else [],
                "lon": shapely.get_x(rep) if len(rep) else [],
                "land_area_sqmi": st_attrs["ALAND"].astype(float) / SQ_M_PER_SQ_MI,
            }
        )
        abbr = dict(zip(states["geo_id"], states["state_abbr"], strict=True))

        # ---- counties
        gc = read_gazetteer(raw["gaz_counties"])
        gc = gc[gc["GEOID"].str[:2].isin(states_keep)]
        counties = pd.DataFrame(
            {
                "geo_level": "county",
                "geo_id": gc["GEOID"],
                "name": gc["NAME"],
                "state_fips": gc["GEOID"].str[:2],
                "state_abbr": gc["USPS"],
                "lat": pd.to_numeric(gc["INTPTLAT"]),
                "lon": pd.to_numeric(gc["INTPTLONG"]),
                "land_area_sqmi": pd.to_numeric(gc["ALAND_SQMI"]),
            }
        )
        counties["cbsa_code"] = counties["geo_id"].map(cbsa["cbsa_code"])
        counties["cbsa_name"] = counties["geo_id"].map(cbsa["cbsa_name"])
        county_ids = set(counties["geo_id"])
        co_attrs, co_geoms = read_shapes(raw["shp_county"], "GEOID", county_ids)
        co_ids = co_attrs["GEOID"].to_numpy()

        # ---- ZCTA -> county
        gz = read_gazetteer(raw["gaz_zcta"])
        zcta_ok = is_sample_zcta if self.sample else is_us_zcta
        zcta_universe = {z for z in gz["GEOID"] if zcta_ok(z)}
        rel = pd.read_csv(raw["rel_zcta_county"], sep="|", dtype=str, encoding="utf-8-sig")
        rel = rel.dropna(subset=["GEOID_ZCTA5_20"])
        rel = rel[rel["GEOID_ZCTA5_20"].isin(zcta_universe)]
        rel["land"] = pd.to_numeric(rel["AREALAND_PART"]).fillna(0)
        rel["water"] = pd.to_numeric(rel["AREAWATER_PART"]).fillna(0)
        ct_zctas = set(rel.loc[rel["GEOID_COUNTY_20"].str[:2] == "09", "GEOID_ZCTA5_20"])
        rel = rel[~rel["GEOID_ZCTA5_20"].isin(ct_zctas)]
        land_tot = rel.groupby("GEOID_ZCTA5_20")["land"].transform("sum")
        water_tot = rel.groupby("GEOID_ZCTA5_20")["water"].transform("sum")
        n_parts = rel.groupby("GEOID_ZCTA5_20")["land"].transform("size")
        rel["weight"] = np.where(
            land_tot > 0,
            rel["land"] / land_tot.where(land_tot > 0, 1),
            np.where(water_tot > 0, rel["water"] / water_tot.where(water_tot > 0, 1), 1.0 / n_parts),
        )
        zx = rel.rename(columns={"GEOID_ZCTA5_20": "from_id", "GEOID_COUNTY_20": "to_id"})[
            ["from_id", "to_id", "weight"]
        ]
        zx = zx[zx["weight"] > 0]

        zcta_shape_keep = zcta_universe if not self.sample else None
        zc_attrs, zc_geoms = read_shapes(raw["shp_zcta"], "GEOID20", zcta_shape_keep)
        if ct_zctas and "09" in states_keep:
            ct_mask = zc_attrs["GEOID20"].isin(ct_zctas).to_numpy()
            ct_co = np.array([c.startswith("09") for c in co_ids], dtype=bool)
            ct_x = overlap_shares(
                zc_attrs["GEOID20"].to_numpy()[ct_mask],
                zc_geoms[ct_mask],
                co_ids[ct_co],
                co_geoms[ct_co],
                0.001,
            )
            zx = pd.concat([zx, ct_x], ignore_index=True)
            log.info(
                "census_geo: %d CT ZCTAs mapped to planning regions by polygon overlap",
                ct_x["from_id"].nunique(),
            )
        zx = zx[zx["to_id"].isin(county_ids)]

        primary = zx.sort_values(["from_id", "weight"], ascending=[True, False]).drop_duplicates("from_id")
        primary = primary.set_index("from_id")["to_id"]
        gz = gz[gz["GEOID"].isin(primary.index)]
        z_county = gz["GEOID"].map(primary)
        zctas = pd.DataFrame(
            {
                "geo_level": "zcta",
                "geo_id": gz["GEOID"],
                "name": gz["GEOID"],
                "state_fips": z_county.str[:2],
                "state_abbr": z_county.str[:2].map(abbr),
                "lat": pd.to_numeric(gz["INTPTLAT"]),
                "lon": pd.to_numeric(gz["INTPTLONG"]),
                "land_area_sqmi": pd.to_numeric(gz["ALAND_SQMI"]),
                "cbsa_code": z_county.map(cbsa["cbsa_code"]),
                "cbsa_name": z_county.map(cbsa["cbsa_name"]),
            }
        )
        zx = zx[zx["from_id"].isin(set(zctas["geo_id"]))]

        # ---- places -> county by polygon overlap
        gp = read_gazetteer(raw["gaz_place"])
        gp = gp[gp["GEOID"].str[:2].isin(states_keep)]
        pl_attrs, pl_geoms = read_shapes(raw["shp_place"], "GEOID", set(gp["GEOID"]))
        px = overlap_shares(pl_attrs["GEOID"].to_numpy(), pl_geoms, co_ids, co_geoms, MIN_PLACE_SHARE)
        p_primary = px.sort_values(["from_id", "weight"], ascending=[True, False]).drop_duplicates("from_id")
        p_county = gp["GEOID"].map(p_primary.set_index("from_id")["to_id"])
        places = pd.DataFrame(
            {
                "geo_level": "place",
                "geo_id": gp["GEOID"],
                "name": gp["NAME"].map(place_display_name),
                "state_fips": gp["GEOID"].str[:2],
                "state_abbr": gp["USPS"],
                "lat": pd.to_numeric(gp["INTPTLAT"]),
                "lon": pd.to_numeric(gp["INTPTLONG"]),
                "land_area_sqmi": pd.to_numeric(gp["ALAND_SQMI"]),
                "cbsa_code": p_county.map(cbsa["cbsa_code"]),
                "cbsa_name": p_county.map(cbsa["cbsa_name"]),
            }
        )

        geo_units = pd.concat([states, counties, zctas, places], ignore_index=True).reindex(
            columns=GEO_UNIT_COLS
        )

        crosswalk = pd.concat(
            [
                zx.assign(from_level="zcta", to_level="county"),
                px.assign(from_level="place", to_level="county"),
                pd.DataFrame(
                    {
                        "from_level": "county",
                        "from_id": counties["geo_id"],
                        "to_level": "state",
                        "to_id": counties["state_fips"],
                        "weight": 1.0,
                    }
                ),
            ],
            ignore_index=True,
        ).reindex(columns=CROSSWALK_COLS)

        zc_keep = zc_attrs["GEOID20"].isin(set(zctas["geo_id"])).to_numpy()
        boundaries = pd.concat(
            [
                self._boundaries("state", st_attrs["GEOID"], st_geoms),
                self._boundaries("county", co_attrs["GEOID"], co_geoms),
                self._boundaries("zcta", zc_attrs["GEOID20"][zc_keep], zc_geoms[zc_keep]),
                self._boundaries("place", pl_attrs["GEOID"], pl_geoms),
            ],
            ignore_index=True,
        )
        log.info(
            "census_geo: geo_units %s; crosswalk %d rows; boundaries %d (%.1f MB GeoJSON)",
            geo_units["geo_level"].value_counts().to_dict(),
            len(crosswalk),
            len(boundaries),
            boundaries["geojson"].str.len().sum() / 1e6,
        )
        return Tidy(geo_units=geo_units, crosswalk=crosswalk, boundaries=boundaries)

    @staticmethod
    def _boundaries(level: str, ids: pd.Series, geoms: np.ndarray) -> pd.DataFrame:
        if len(geoms) == 0:
            return pd.DataFrame(columns=["geo_level", "geo_id", "geojson"])
        return pd.DataFrame(
            {
                "geo_level": level,
                "geo_id": ids.to_numpy(),
                "geojson": to_geojson(geoms, SIMPLIFY_TOLERANCE[level]),
            }
        )
