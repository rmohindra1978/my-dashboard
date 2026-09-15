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
