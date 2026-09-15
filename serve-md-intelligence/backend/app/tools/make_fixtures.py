"""Generate the SYNTHETIC development/test fixture set under data/fixtures.

These values are NOT real statistics. They are seeded pseudo-random numbers in plausible ranges so the
engines, API and UI can be exercised (and tested deterministically) without downloading public data.
Run `python -m backend.app.tools.make_fixtures` to regenerate.
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

from backend.app.registry import load_metric_registry
from backend.app.settings import settings

COUNTIES = [
    ("04013", "Maricopa County", "04", "AZ", 33.35, -112.49, 9200.0, "38060", "Phoenix-Mesa-Chandler, AZ"),
    ("04019", "Pima County", "04", "AZ", 32.10, -111.79, 9187.0, "46060", "Tucson, AZ"),
    ("04021", "Pinal County", "04", "AZ", 32.90, -111.35, 5366.0, "38060", "Phoenix-Mesa-Chandler, AZ"),
    ("04015", "Mohave County", "04", "AZ", 35.70, -113.76, 13311.0, "29420", "Lake Havasu City-Kingman, AZ"),
    ("04025", "Yavapai County", "04", "AZ", 34.60, -112.55, 8123.0, "39150", "Prescott Valley-Prescott, AZ"),
    (
        "12057",
        "Hillsborough County",
        "12",
        "FL",
        27.91,
        -82.35,
        1020.0,
        "45300",
        "Tampa-St. Petersburg-Clearwater, FL",
    ),
    (
        "12103",
        "Pinellas County",
        "12",
        "FL",
        27.90,
        -82.74,
        274.0,
        "45300",
        "Tampa-St. Petersburg-Clearwater, FL",
    ),
    ("12071", "Lee County", "12", "FL", 26.57, -81.84, 785.0, "15980", "Cape Coral-Fort Myers, FL"),
    ("48453", "Travis County", "48", "TX", 30.33, -97.78, 990.0, "12420", "Austin-Round Rock-San Marcos, TX"),
    ("48029", "Bexar County", "48", "TX", 29.45, -98.52, 1240.0, "41700", "San Antonio-New Braunfels, TX"),
    ("37183", "Wake County", "37", "NC", 35.79, -78.65, 835.0, "39580", "Raleigh-Cary, NC"),
    (
        "32003",
        "Clark County",
        "32",
        "NV",
        36.21,
        -115.01,
        7891.0,
        "29820",
        "Las Vegas-Henderson-North Las Vegas, NV",
    ),
]
STATES = [
    ("04", "Arizona", "AZ"),
    ("12", "Florida", "FL"),
    ("48", "Texas", "TX"),
    ("37", "North Carolina", "NC"),
    ("32", "Nevada", "NV"),
]
ZCTAS = [
    ("85004", "04013", 33.45, -112.07),
    ("85008", "04013", 33.47, -111.98),
    ("85281", "04013", 33.43, -111.93),
    ("85701", "04019", 32.22, -110.97),
    ("33602", "12057", 27.95, -82.46),
    ("78701", "48453", 30.27, -97.74),
]
PLACES = [
    ("0455000", "Phoenix", "04", "AZ", "04013", 33.57, -112.09),
    ("0477000", "Tucson", "04", "AZ", "04019", 32.15, -110.87),
    ("1271000", "Tampa", "12", "FL", "12057", 27.97, -82.47),
    ("4805000", "Austin", "48", "TX", "48453", 30.30, -97.75),
]

# plausible synthetic ranges per metric unit / id
RANGES: dict[str, tuple[float, float]] = {
    "pop_total": (150_000, 4_500_000),
    "pop_65_plus": (25_000, 800_000),
    "pct_65_plus": (11, 32),
    "pop_75_plus": (10_000, 350_000),
    "median_age": (33, 52),
    "pop_65_plus_growth_5yr": (5, 30),
    "pop_growth_5yr": (-1, 14),
    "pop_density": (40, 3500),
    "pct_65_living_alone": (22, 34),
    "medicare_benes_total": (30_000, 800_000),
    "medicare_benes_aged": (25_000, 700_000),
    "original_medicare_benes": (12_000, 400_000),
    "medicare_ma_benes": (10_000, 450_000),
    "ma_penetration_pct": (30, 62),
    "dual_eligible_pct": (9, 26),
    "medicare_benes_growth_5yr": (4, 24),
    "avg_hcc_risk_score": (0.88, 1.25),
    "medicare_spend_per_capita_std": (9_500, 14_500),
    "ed_visits_per_1000": (480, 820),
    "readmission_rate": (14, 20),
    "ip_stays_per_1000": (210, 330),
    "pcp_count": (120, 3800),
    "pcp_physician_count": (80, 2600),
    "pcp_per_1000_65plus": (2.5, 7.5),
    "pcp_per_10k_pop": (4, 12),
    "large_group_pcp_share": (25, 70),
    "hpsa_primary_care_flag": (0, 1),
    "hpsa_score_max": (0, 22),
    "diabetes_prevalence": (8, 15),
    "obesity_prevalence": (26, 40),
    "hypertension_prevalence": (26, 40),
    "chd_prevalence": (4.5, 8.5),
    "copd_prevalence": (4.5, 9.5),
    "fair_poor_health_pct": (13, 24),
    "no_checkup_pct": (18, 32),
    "pct_65_plus_disability": (28, 42),
    "median_household_income": (52_000, 105_000),
    "per_capita_income": (28_000, 58_000),
    "poverty_rate_65_plus": (6, 16),
    "unemployment_rate": (3, 8),
    "median_home_value": (180_000, 520_000),
    "median_gross_rent": (950, 1_900),
    "pct_bachelors_plus": (22, 52),
    "pct_hispanic": (8, 62),
    "pct_black": (2, 30),
}


def _value(rng: random.Random, metric_id: str, unit: str) -> float:
    lo, hi = RANGES.get(metric_id, (0, 100))
    v = rng.uniform(lo, hi)
    if unit in ("count",) or metric_id in ("hpsa_primary_care_flag",):
        return float(round(v))
    return round(v, 3)


def main(out_dir: Path | None = None) -> None:
    out = out_dir or settings.fixtures_dir
    out.mkdir(parents=True, exist_ok=True)
    registry = load_metric_registry()
    rng = random.Random(20260915)

    with open(out / "geo_units.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "geo_level",
                "geo_id",
                "name",
                "state_fips",
                "state_abbr",
                "lat",
                "lon",
                "land_area_sqmi",
                "cbsa_code",
                "cbsa_name",
            ]
        )
        for fips, name, abbr in STATES:
            w.writerow(["state", fips, name, fips, abbr, "", "", "", "", ""])
        for c in COUNTIES:
            w.writerow(["county", *c])
        for z, county, lat, lon in ZCTAS:
            c = next(x for x in COUNTIES if x[0] == county)
            w.writerow(["zcta", z, z, c[2], c[3], lat, lon, rng.uniform(2, 40), c[7], c[8]])
        for pid, name, sf, abbr, county, lat, lon in PLACES:
            c = next(x for x in COUNTIES if x[0] == county)
            w.writerow(["place", pid, name, sf, abbr, lat, lon, rng.uniform(150, 600), c[7], c[8]])

    with open(out / "geo_crosswalk.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["from_level", "from_id", "to_level", "to_id", "weight"])
        for z, county, *_ in ZCTAS:
            w.writerow(["zcta", z, "county", county, 1.0])
        for pid, _name, _sf, _abbr, county, *_ in PLACES:
            w.writerow(["place", pid, "county", county, 1.0])
        for c in COUNTIES:
            w.writerow(["county", c[0], "state", c[2], 1.0])

    with open(out / "metric_values.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["geo_level", "geo_id", "metric_id", "period", "value", "source_id"])
        units = (
            [("state", s[0]) for s in STATES]
            + [("county", c[0]) for c in COUNTIES]
            + [("zcta", z[0]) for z in ZCTAS]
            + [("place", p[0]) for p in PLACES]
        )
        for level, gid in units:
            for m in registry.metrics:
                if level not in [g.value for g in m.geo_levels]:
                    continue
                # leave a few cells null to exercise missing-data handling
                value = "" if rng.random() < 0.03 else _value(rng, m.id, m.unit)
                w.writerow([level, gid, m.id, registry.sources[m.source].vintage, value, m.source])

    (out / "README.md").write_text(
        "# Fixtures (SYNTHETIC)\n\nGenerated by `python -m backend.app.tools.make_fixtures`. "
        "Values are seeded "
        "pseudo-random numbers in plausible ranges - they are **not** real statistics and exist only so the "
        "engines, API and UI can run and be tested without downloading public data. "
        "Run `make data` for real data.\n"
    )
    print(f"fixtures written to {out}")


if __name__ == "__main__":
    main()
