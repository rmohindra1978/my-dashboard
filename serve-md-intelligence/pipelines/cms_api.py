"""Keyless access to data.cms.gov datasets through the public Data API.

`https://data.cms.gov/data-api/v1/dataset/<id>/data` accepts `size`/`offset` pagination, `filter[COL]=value`
equality filters and a `column=A,B,C` projection. It needs no API key and its URL is stable across dataset
releases (the CSV `downloadURL`s under /sites/default/files change with every monthly refresh), so the loaders
use it as their download route. Every page is cached under data/raw/<source_id>/ by `pipelines.base.download`;
re-running a loader is therefore offline once the files exist, and a new data year is picked up automatically
because its files do not exist yet.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd

from pipelines.base import download

API_ROOT = "https://data.cms.gov/data-api/v1/dataset"
PAGE_SIZE = 5000

# 50 states + DC. Territories (60 AS, 66 GU, 69 MP, 72 PR, 78 VI) and "Unknown"/"ZZ" rows are dropped.
STATE_FIPS: frozenset[str] = frozenset(f"{i:02d}" for i in range(1, 57) if i not in {3, 7, 14, 43, 52})


def api_url(
    dataset_id: str,
    filters: dict[str, str],
    columns: list[str] | None = None,
    size: int = PAGE_SIZE,
    offset: int = 0,
) -> str:
    params: list[tuple[str, str]] = [("size", str(size)), ("offset", str(offset))]
    params += [(f"filter[{k}]", v) for k, v in filters.items()]
    if columns:
        params.append(("column", ",".join(columns)))
    return f"{API_ROOT}/{dataset_id}/data?{urlencode(params)}"


def download_pages(
    dataset_id: str,
    dest_dir: Path,
    stem: str,
    filters: dict[str, str],
    columns: list[str] | None = None,
) -> list[Path]:
    """Download every page of one filtered query as `<stem>_p<n>.json` (cached).

    Returns [] when the query matches no rows; an empty result is never cached so that a year that is not
    published yet is re-checked on the next run.
    """
    pages: list[Path] = []
    page = 0
    while True:
        path = download(
            api_url(dataset_id, filters, columns, PAGE_SIZE, page * PAGE_SIZE),
            dest_dir,
            f"{stem}_p{page}.json",
        )
        rows = json.loads(path.read_text())
        if not rows:
            path.unlink(missing_ok=True)
            return pages
        pages.append(path)
        if len(rows) < PAGE_SIZE:
            return pages
        page += 1


def download_years(
    dataset_id: str,
    dest_dir: Path,
    stem: str,
    filters: dict[str, str],
    columns: list[str] | None,
    first_year: int,
    year_column: str = "YEAR",
    last_year: int | None = None,
) -> dict[str, Path]:
    """Download one filtered query per data year from `first_year` until the first year with no rows.

    Cached years cost no network call; the first missing year costs exactly one small request. Keys are
    `<stem>_<year>_p<n>` -> page path.
    """
    out: dict[str, Path] = {}
    for year in range(first_year, (last_year or date.today().year) + 1):
        year_filters = {**filters, year_column: str(year)}
        pages = download_pages(dataset_id, dest_dir, f"{stem}_{year}", year_filters, columns)
        if not pages:
            break
        for i, p in enumerate(pages):
            out[f"{stem}_{year}_p{i}"] = p
    return out


def read_pages(paths: list[Path] | dict[str, Path]) -> pd.DataFrame:
    """Concatenate API JSON pages into one all-string DataFrame (ids keep their leading zeros)."""
    files = list(paths.values()) if isinstance(paths, dict) else list(paths)
    frames = [pd.DataFrame(json.loads(p.read_text()), dtype=str) for p in files]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def keep_states_and_dc(df: pd.DataFrame, fips_col: str) -> pd.DataFrame:
    """Rows whose (state prefix of) FIPS is one of the 50 states or DC."""
    return df[df[fips_col].str[:2].isin(STATE_FIPS)]
