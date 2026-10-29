"""FIPS helpers shared by loaders: the 50 states + DC universe and zero-padding of id columns."""

from __future__ import annotations

import pandas as pd

# 2-digit state FIPS for the 50 states + DC (excludes 03, 07, 14, 43, 52 gaps and territories 60+).
STATE_FIPS: frozenset[str] = frozenset(f"{i:02d}" for i in range(1, 57) if i not in {3, 7, 14, 43, 52})

SAMPLE_STATE_FIPS: tuple[str, ...] = ("04", "48")  # AZ + TX, used when Source.sample is True


def pad_fips(s: pd.Series, width: int) -> pd.Series:
    """Normalize an id column: strip, drop a trailing '.0' from float-parsed codes, zero-pad to `width`."""
    return s.astype(str).str.strip().str.replace(r"\.0$", "", regex=True).str.zfill(width)


def in_states(county_fips: pd.Series, sample: bool = False) -> pd.Series:
    """Boolean mask: 5-digit county FIPS belongs to the 50 states + DC (or to the sample states)."""
    state = county_fips.str[:2]
    if sample:
        return state.isin(SAMPLE_STATE_FIPS)
    return state.isin(STATE_FIPS)


# ZCTAs in PR/VI (006-009xx), Guam/N. Mariana Is. (969xx) and American Samoa (96799) are territories.
_TERRITORY_ZCTA_PREFIXES = ("006", "007", "008", "009", "969")
# AZ (850-865) and TX (750-799, 885) ZIP prefixes, mirroring SAMPLE_STATE_FIPS.
_SAMPLE_ZCTA_PREFIXES = ("85", "860", "863", "864", "865", "75", "76", "77", "78", "79", "885")


def is_us_zcta(zcta: str) -> bool:
    """5-digit ZCTA in the 50 states + DC (territory ranges excluded)."""
    return (
        len(zcta) == 5
        and zcta.isdigit()
        and not zcta.startswith(_TERRITORY_ZCTA_PREFIXES)
        and zcta != "96799"
    )


def is_sample_zcta(zcta: str) -> bool:
    return is_us_zcta(zcta) and zcta.startswith(_SAMPLE_ZCTA_PREFIXES)
