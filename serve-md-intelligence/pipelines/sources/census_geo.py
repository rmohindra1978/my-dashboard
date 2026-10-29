"""Census geography backbone: geo_units, geo_crosswalk and geo_boundaries for state, county, ZCTA and place.

Inputs (all public, keyless, cached under data/raw/):
    2023 Gazetteer files            counties / ZCTAs / places: names, internal points, land area
    2020 ZCTA->county relationship  tab20_zcta520_county20_natl.txt (land-area parts)
    OMB July-2023 delineation       list1_2023.xlsx: county -> CBSA code / title
    ACS 2019-2023 5-year            Geos20235YR.txt + B01001 (summary level 155 = place x county parts,
                                    used for population-weighted place->county allocation; the Census
                                    Bureau publishes no 2020 place->county relationship file)
    Cartographic boundaries 1:500k  2023 state / county / place, 2020 ZCTA (the latest ZCTA vintage)

The derived metric `pop_density` (registered under this source) is computed by pipelines/derived.py once
ACS `pop_total` is loaded; this loader emits geography only.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd
import shapefile
import shapely
from shapely.geometry import shape

from backend.app.settings import settings
from pipelines.base import CROSSWALK_COLS, GEO_UNIT_COLS, Source, Tidy, download
from pipelines.fips import SAMPLE_STATE_FIPS, STATE_FIPS

log = logging.getLogger("pipelines.census_geo")

GAZ = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer/"
REL = "https://www2.census.gov/geo/docs/maps-data/data/rel2020/"
CB23 = "https://www2.census.gov/geo/tiger/GENZ2023/shp/"
CB20 = "https://www2.census.gov/geo/tiger/GENZ2020/shp/"
ACS_DOC = "https://www2.census.gov/programs-surveys/acs/summary_file/2023/table-based-SF/documentation/"
ACS_DATA = "https://www2.census.gov/programs-surveys/acs/summary_file/2023/table-based-SF/data/5YRData/"
CBSA_URL = (
    "https://www2.census.gov/programs-surveys/metro-micro/geographies/reference-files/2023/"
    "delineation-files/list1_2023.xlsx"
)

# key -> (url, cache sub-directory). ACS files share the acs5 cache so they are downloaded once.
URLS: dict[str, tuple[str, str]] = {
    "gaz_counties": (GAZ + "2023_Gaz_counties_national.zip", "census_geo"),
    "gaz_zcta": (GAZ + "2023_Gaz_zcta_national.zip", "census_geo"),
    "gaz_place": (GAZ + "2023_Gaz_place_national.zip", "census_geo"),
    "rel_zcta_county": (REL + "zcta520/tab20_zcta520_county20_natl.txt", "census_geo"),
    "cbsa": (CBSA_URL, "census_geo"),
    "acs_geos": (ACS_DOC + "Geos20235YR.txt", "acs5"),
    "acs_b01001": (ACS_DATA + "acsdt5y2023-b01001.dat", "acs5"),
    "cb_state": (CB23 + "cb_2023_us_state_500k.zip", "census_geo"),
    "cb_county": (CB23 + "cb_2023_us_county_500k.zip", "census_geo"),
    "cb_place": (CB23 + "cb_2023_us_place_500k.zip", "census_geo"),
    "cb_zcta": (CB20 + "cb_2020_us_zcta520_500k.zip", "census_geo"),
}

# 50 states + DC: FIPS -> (USPS abbreviation, name)
STATES: dict[str, tuple[str, str]] = {
    "01": ("AL", "Alabama"), "02": ("AK", "Alaska"), "04": ("AZ", "Arizona"), "05": ("AR", "Arkansas"),
    "06": ("CA", "California"), "08": ("CO", "Colorado"), "09": ("CT", "Connecticut"),
    "10": ("DE", "Delaware"), "11": ("DC", "District of Columbia"), "12": ("FL", "Florida"),
    "13": ("GA", "Georgia"), "15": ("HI", "Hawaii"), "16": ("ID", "Idaho"), "17": ("IL", "Illinois"),
    "18": ("IN", "Indiana"), "19": ("IA", "Iowa"), "20": ("KS", "Kansas"), "21": ("KY", "Kentucky"),
    "22": ("LA", "Louisiana"), "23": ("ME", "Maine"), "24": ("MD", "Maryland"),
    "25": ("MA", "Massachusetts"), "26": ("MI", "Michigan"), "27": ("MN", "Minnesota"),
    "28": ("MS", "Mississippi"), "29": ("MO", "Missouri"), "30": ("MT", "Montana"),
    "31": ("NE", "Nebraska"), "32": ("NV", "Nevada"), "33": ("NH", "New Hampshire"),
    "34": ("NJ", "New Jersey"), "35": ("NM", "New Mexico"), "36": ("NY", "New York"),
    "37": ("NC", "North Carolina"), "38": ("ND", "North Dakota"), "39": ("OH", "Ohio"),
    "40": ("OK", "Oklahoma"), "41": ("OR", "Oregon"), "42": ("PA", "Pennsylvania"),
    "44": ("RI", "Rhode Island"), "45": ("SC", "South Carolina"), "46": ("SD", "South Dakota"),
    "47": ("TN", "Tennessee"), "48": ("TX", "Texas"), "49": ("UT", "Utah"), "50": ("VT", "Vermont"),
    "51": ("VA", "Virginia"), "53": ("WA", "Washington"), "54": ("WV", "West Virginia"),
    "55": ("WI", "Wisconsin"), "56": ("WY", "Wyoming"),
}  # fmt: skip
assert set(STATES) == STATE_FIPS

# Douglas-Peucker tolerance and output coordinate grid (degrees) per layer. Counties at 0.005 deg
# (~500 m) keep the national county layer around 10 MB of GeoJSON; ZCTAs / places are coarser.
SIMPLIFY: dict[str, tuple[float, float]] = {
    "state": (0.01, 1e-4),
    "county": (0.005, 1e-4),
    "place": (0.002, 1e-4),
    "zcta": (0.003, 1e-4),
}

_TRAILING_LSAD = re.compile(r"^(CDP|[a-z][a-z/'-]*)$")


def clean_place_name(name: str) -> str:
    """'Phoenix city' -> 'Phoenix', 'Indianapolis city (balance)' -> 'Indianapolis', 'Abanda CDP' -> 'Abanda'.

    Gazetteer place names end with their legal/statistical area description, which is always lower case
    (city, town, village, borough, municipality, urban county, ...) or 'CDP'; strip those trailing words
    but never the whole name ('Boise City city' -> 'Boise City', 'Carson City' unchanged).
    """
    words = re.sub(r"\s*\(balance\)$", "", str(name).strip()).split()
    while len(words) > 1 and _TRAILING_LSAD.match(words[-1]):
        words.pop()
    return " ".join(words)


def _read_gazetteer(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep="\t", dtype=str, encoding="latin-1", compression="infer")
    df.columns = [c.strip() for c in df.columns]
    return df.apply(lambda s: s.str.strip())


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def read_cbsa(path: Path) -> pd.DataFrame:
    """OMB delineation workbook -> county_fips, cbsa_code, cbsa_name (header is on the third row)."""
    df = pd.read_excel(path, header=2, dtype=str)
    df = df.dropna(subset=["CBSA Code", "FIPS State Code", "FIPS County Code"])
    df = df[df["CBSA Code"].str.fullmatch(r"\d{5}")]
    return pd.DataFrame(
        {
            "county_fips": df["FIPS State Code"].str.zfill(2) + df["FIPS County Code"].str.zfill(3),
            "cbsa_code": df["CBSA Code"],
            "cbsa_name": df["CBSA Title"].str.strip(),
        }
    ).drop_duplicates("county_fips")


def zcta_county_crosswalk(path: Path, states: frozenset[str] | tuple[str, ...]) -> pd.DataFrame:
    """2020 ZCTA x county parts -> weights = land-area share of the ZCTA (water share for all-water ZCTAs)."""
    df = pd.read_csv(
        path,
        sep="|",
        dtype=str,
        encoding="utf-8-sig",
        usecols=["GEOID_ZCTA5_20", "GEOID_COUNTY_20", "AREALAND_PART", "AREAWATER_PART"],
    )
    df = df[df["GEOID_ZCTA5_20"].fillna("").str.fullmatch(r"\d{5}")]
    df = df[df["GEOID_COUNTY_20"].str[:2].isin(states)]
    land, water = _num(df["AREALAND_PART"]).fillna(0), _num(df["AREAWATER_PART"]).fillna(0)
    zl = land.groupby(df["GEOID_ZCTA5_20"]).transform("sum")
    zw = water.groupby(df["GEOID_ZCTA5_20"]).transform("sum")
    weight = np.where(zl > 0, land / zl.where(zl > 0), water / zw.where(zw > 0))
    out = pd.DataFrame(
        {
            "from_level": "zcta",
            "from_id": df["GEOID_ZCTA5_20"].values,
            "to_level": "county",
            "to_id": df["GEOID_COUNTY_20"].values,
            "weight": weight,
        }
    )
    out["weight"] = out["weight"].fillna(0.0)
    return out[out["weight"] > 0].reset_index(drop=True)


def place_county_crosswalk(
    geos: Path, b01001: Path, states: frozenset[str] | tuple[str, ...]
) -> pd.DataFrame:
    """ACS summary level 155 (state-place-county parts) -> population share of each place in each county."""
    g = pd.read_csv(
        geos, sep="|", dtype=str, encoding="utf-8-sig", usecols=["SUMLEVEL", "COMPONENT", "GEO_ID"]
    )
    g = g[(g["SUMLEVEL"] == "155") & (g["COMPONENT"] == "00")]
    ids = g["GEO_ID"].str.split("US").str[1]
    parts = pd.DataFrame({"GEO_ID": g["GEO_ID"].values, "place": ids.str[:7].values, "county": None})
    parts["county"] = ids.str[:2].values + ids.str[7:10].values
    parts = parts[parts["place"].str[:2].isin(states)]
    pop = pd.read_csv(b01001, sep="|", dtype=str, encoding="utf-8-sig", usecols=["GEO_ID", "B01001_E001"])
    pop = pop[pop["GEO_ID"].str.startswith("1550000US")]
    parts = parts.merge(pop, on="GEO_ID", how="left")
    p = _num(parts["B01001_E001"]).clip(lower=0).fillna(0)
    tot = p.groupby(parts["place"]).transform("sum")
    n = parts.groupby("place")["county"].transform("size")
    weight = np.where(tot > 0, p / tot.where(tot > 0), 1.0 / n)
    out = pd.DataFrame(
        {
            "from_level": "place",
            "from_id": parts["place"].values,
            "to_level": "county",
            "to_id": parts["county"].values,
            "weight": weight,
        }
    )
    return out[out["weight"] > 0].reset_index(drop=True)


def _majority(xw: pd.DataFrame) -> pd.Series:
    """from_id -> to_id with the largest weight."""
    top = xw.sort_values(["from_id", "weight", "to_id"], ascending=[True, False, True])
    return top.drop_duplicates("from_id").set_index("from_id")["to_id"]


def read_boundaries(
    path: Path, level: str, id_field: str, keep: set[str]
) -> tuple[pd.DataFrame, dict[str, tuple[float, float]]]:
    """Shapefile zip -> (geo_level, geo_id, geojson) with simplified geometry + representative points."""
    tol, grid = SIMPLIFY[level]
    reader = shapefile.Reader(str(path))
    fields = [f[0] for f in reader.fields[1:]]
    idx = fields.index(id_field)
    rows, points = [], {}
    for sr in reader.iterShapeRecords():
        geo_id = str(sr.record[idx]).strip()
        if geo_id not in keep or sr.shape.shapeType == shapefile.NULL:
            continue
        geom = shape(sr.shape.__geo_interface__)
        if not geom.is_valid:
            geom = shapely.make_valid(geom)
        simple = shapely.set_precision(geom.simplify(tol, preserve_topology=True), grid)
        if simple.is_empty:  # tiny islands / slivers: keep the unsimplified shape on the grid
            simple = shapely.set_precision(geom, grid)
        if simple.is_empty:
            continue
        pt = geom.representative_point()
        points[geo_id] = (round(pt.y, 6), round(pt.x, 6))
        rows.append((level, geo_id, shapely.to_geojson(simple)))
    reader.close()
    return pd.DataFrame(rows, columns=["geo_level", "geo_id", "geojson"]), points


class CensusGeoSource(Source):
    source_id = "census_geo"
    geo_levels = ("state", "county", "zcta", "place")

    def extract(self) -> dict[str, Path]:
        return {
            key: download(url, settings.raw_dir / sub, url.rsplit("/", 1)[-1])
            for key, (url, sub) in URLS.items()
        }

    def transform(self, raw: dict[str, Path]) -> Tidy:
        states = frozenset(SAMPLE_STATE_FIPS) if self.sample else STATE_FIPS
        cbsa = read_cbsa(raw["cbsa"]).set_index("county_fips")

        # ---- counties
        gc = _read_gazetteer(raw["gaz_counties"])
        gc = gc[gc["GEOID"].str[:2].isin(states)]
        counties = pd.DataFrame(
            {
                "geo_level": "county",
                "geo_id": gc["GEOID"].values,
                "name": gc["NAME"].values,
                "state_fips": gc["GEOID"].str[:2].values,
                "state_abbr": gc["USPS"].values,
                "lat": _num(gc["INTPTLAT"]).values,
                "lon": _num(gc["INTPTLONG"]).values,
                "land_area_sqmi": _num(gc["ALAND_SQMI"]).values,
            }
        )
        counties["cbsa_code"] = counties["geo_id"].map(cbsa["cbsa_code"])
        counties["cbsa_name"] = counties["geo_id"].map(cbsa["cbsa_name"])
        county_ids = set(counties["geo_id"])

        # ---- crosswalks
        xw_zc = zcta_county_crosswalk(raw["rel_zcta_county"], states)
        xw_zc = xw_zc[xw_zc["to_id"].isin(county_ids)]
        xw_pc = place_county_crosswalk(raw["acs_geos"], raw["acs_b01001"], states)
        xw_pc = xw_pc[xw_pc["to_id"].isin(county_ids)]
        county_meta = counties.set_index("geo_id")

        # ---- ZCTAs: state / CBSA of the majority (largest land share) county
        gz = _read_gazetteer(raw["gaz_zcta"])
        zmaj = _majority(xw_zc)
        gz = gz[gz["GEOID"].isin(zmaj.index)]
        maj = gz["GEOID"].map(zmaj)
        zctas = pd.DataFrame(
            {
                "geo_level": "zcta",
                "geo_id": gz["GEOID"].values,
                "name": gz["GEOID"].values,
                "state_fips": maj.str[:2].values,
                "state_abbr": maj.map(county_meta["state_abbr"]).values,
                "lat": _num(gz["INTPTLAT"]).values,
                "lon": _num(gz["INTPTLONG"]).values,
                "land_area_sqmi": _num(gz["ALAND_SQMI"]).values,
                "cbsa_code": maj.map(county_meta["cbsa_code"]).values,
                "cbsa_name": maj.map(county_meta["cbsa_name"]).values,
            }
        )
        xw_zc = xw_zc[xw_zc["from_id"].isin(set(zctas["geo_id"]))]

        # ---- places: CBSA of the majority-population county
        gp = _read_gazetteer(raw["gaz_place"])
        gp = gp[gp["GEOID"].str[:2].isin(states)]
        pmaj = gp["GEOID"].map(_majority(xw_pc))
        places = pd.DataFrame(
            {
                "geo_level": "place",
                "geo_id": gp["GEOID"].values,
                "name": gp["NAME"].map(clean_place_name).values,
                "state_fips": gp["GEOID"].str[:2].values,
                "state_abbr": gp["USPS"].values,
                "lat": _num(gp["INTPTLAT"]).values,
                "lon": _num(gp["INTPTLONG"]).values,
                "land_area_sqmi": _num(gp["ALAND_SQMI"]).values,
                "cbsa_code": pmaj.map(county_meta["cbsa_code"]).values,
                "cbsa_name": pmaj.map(county_meta["cbsa_name"]).values,
            }
        )
        xw_pc = xw_pc[xw_pc["from_id"].isin(set(places["geo_id"]))]

        # ---- boundaries (+ state representative points for lat/lon)
        layers = [
            ("state", raw["cb_state"], "GEOID", set(states)),
            ("county", raw["cb_county"], "GEOID", county_ids),
            ("zcta", raw["cb_zcta"], "GEOID20", set(zctas["geo_id"])),
            ("place", raw["cb_place"], "GEOID", set(places["geo_id"])),
        ]
        frames, state_points = [], {}
        for level, path, field, keep in layers:
            df, points = read_boundaries(path, level, field, keep)
            log.info("%s: %d %s boundaries, %.1f MB GeoJSON", self.source_id, len(df), level,
                     df["geojson"].str.len().sum() / 1e6 if len(df) else 0)  # fmt: skip
            frames.append(df)
            if level == "state":
                state_points = points
        boundaries = pd.concat(frames, ignore_index=True)

        # ---- states
        sids = sorted(set(counties["state_fips"]))
        land = counties.groupby("state_fips")["land_area_sqmi"].sum()
        state_units = pd.DataFrame(
            {
                "geo_level": "state",
                "geo_id": sids,
                "name": [STATES[s][1] for s in sids],
                "state_fips": sids,
                "state_abbr": [STATES[s][0] for s in sids],
                "lat": [state_points.get(s, (None, None))[0] for s in sids],
                "lon": [state_points.get(s, (None, None))[1] for s in sids],
                "land_area_sqmi": [round(float(land.get(s, np.nan)), 3) for s in sids],
                "cbsa_code": None,
                "cbsa_name": None,
            }
        )

        geo_units = pd.concat([state_units, counties, zctas, places], ignore_index=True)[GEO_UNIT_COLS]
        cs = counties[["geo_id", "state_fips"]]
        county_state = pd.DataFrame(
            {"from_level": "county", "from_id": cs["geo_id"], "to_level": "state", "to_id": cs["state_fips"],
             "weight": 1.0}
        )  # fmt: skip
        state_county = pd.DataFrame(
            {"from_level": "state", "from_id": cs["state_fips"], "to_level": "county", "to_id": cs["geo_id"],
             "weight": 1.0}
        )  # fmt: skip
        crosswalk = pd.concat([xw_zc, xw_pc, county_state, state_county], ignore_index=True)[CROSSWALK_COLS]
        log.info(
            "%s: geo_units %s; crosswalk %d rows",
            self.source_id,
            geo_units["geo_level"].value_counts().to_dict(),
            len(crosswalk),
        )
        return Tidy(geo_units=geo_units, crosswalk=crosswalk, boundaries=boundaries)
