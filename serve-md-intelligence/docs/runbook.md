# Runbook

## Prerequisites

- Python 3.10+ and Node 20+ (Node 22 recommended)
- ~3 GB free disk for raw downloads + warehouse when using real data

## Local development

```bash
make setup            # venv, pip install -e ".[dev]", npm install
make data-sample      # synthetic warehouse (seconds, offline)
make dev              # API :8000 + Vite :5173
```

- API docs: http://localhost:8000/docs
- Health: `curl localhost:8000/api/health` → geo/metric counts + sources loaded
- Frontend proxies `/api` to `VITE_API_URL` (default http://localhost:8000)

## Building the national warehouse

```bash
make data                                  # all sources, dependency order
python -m pipelines.build --list           # registered sources
python -m pipelines.build --source acs5    # one source (idempotent upsert)
```

Raw files are cached in `data/raw/<source>/`; delete a file to force re-download. Each run is
recorded in `pipeline_runs` (status, rows, vintage, error). Failed sources do not block the
others; `market_features` is rebuilt after every successful load.

Expected order of magnitude on a laptop: Census geography + ACS ≈ 5–10 min (large files), CMS
enrollment / geographic variation ≈ 2 min, clinician file ≈ 1 min after download (3.4 M rows),
HRSA / CDC < 1 min.

### `dac_clinicians` (CMS Doctors & Clinicians)

- Resolves the current CSV URL from the CMS metastore
  (`.../metastore/schemas/dataset/items/mj5m-pzi6`) and caches
  `data/raw/dac_clinicians/DAC_NationalDownloadableFile_<released>.csv` (≈ 840 MB, 3.39 M rows,
  Sept-2026 release) plus `metadata_<released>.json`. A new CMS release means a new file; delete
  old ones to reclaim disk. If the metastore is unreachable the newest cached metadata is reused.
- Streams the CSV with pyarrow in 32 MB blocks and keeps only the 5 needed columns of
  primary-care rows: ≈ 20 s transform + load, peak RSS ≈ 1.2 GB. `--sample` limits it to AZ + TX.
- Run it **after** `census_geo`: county rows need ZCTA→county weights in `geo_crosswalk`, and the
  ZCTA universe in `geo_units` is used to drop non-ZCTA ZIPs and to emit zero rows for ZCTAs /
  counties without PCPs. With an empty crosswalk it logs a warning and loads ZCTA rows only
  (≈ 53 k rows); with geography loaded it writes ≈ 110 k rows (33.6 k ZCTAs + 3.1 k counties × 3
  metrics).

Measured (Sept 2026, cold cache):

| source | download | raw size | rows loaded | wall time |
|---|---|---|---|---|
| `cms_enrollment` | data.cms.gov data API, paginated JSON (5,000 rows/page, projected columns, `filter[MONTH]=Year`), one file per year x geo level (2013–2025) | ≈ 9.3 MB, 26 files | 274,622 metric rows (51 states, 3,144 counties) | ≈ 30 s |
| `cms_geo_variation` | same API, `filter[BENE_AGE_LVL]=All`, one file per year x geo level (2014–2024) | ≈ 8.0 MB, 22 files | 140,452 metric rows (51 states, 3,141 counties) | ≈ 20 s |

The CMS data API is keyless; both loaders probe successive `YEAR`s until the API returns an empty
page, so a new CMS release is picked up by simply re-running (cached years are not re-fetched).

Measured per source (download once, then cached; transform time and peak memory on a laptop-class VM):

| source | raw file(s) | download | transform + load | peak RSS | rows loaded |
|---|---|---|---|---|---|
| `hrsa_hpsa` | `BCD_HPSA_FCT_DET_PC.csv` ≈ 48 MB (80 k component rows) | ~10 s | < 1 s | ~300 MB | 6,166 (3,083 counties × 2 metrics) |
| `cdc_places` | `places_county_swc5-untb.csv` ≈ 53 MB (230 k rows) | ~20 s | < 1 s | ~300 MB | 21,042 (2,957 counties + 49 states × 7 metrics) |

HRSA regenerates its extract frequently; delete `data/raw/hrsa_hpsa/BCD_HPSA_FCT_DET_PC.csv` to pick
up new designations (rows land under a new `YYYY-MM` period; `market_features` keeps the latest).

## Production-style single process

```bash
cd frontend && npm ci && npm run build && cd ..
SERVEMD_ACCESS_TOKEN=<secret> .venv/bin/uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

FastAPI serves `frontend/dist` with SPA fallback. When `SERVEMD_ACCESS_TOKEN` is set every `/api`
call must send `X-Access-Token: <secret>` (or `Authorization: Bearer <secret>`); the UI stores the
token in `localStorage["servemd.token"]`. Put the service behind TLS (reverse proxy) for private
deployment. Set `SERVEMD_READ_ONLY_WAREHOUSE=true` for replicas that should not accept config or
scenario writes.

## Tests and quality gates

```bash
make test      # pytest -q (backend + pipelines), vitest
make lint      # ruff check + format --check, eslint, tsc
```

CI runs the same on every pull request.

## Troubleshooting

| symptom | fix |
|---|---|
| `API offline` in header | backend not running / wrong `VITE_API_URL` |
| `/api/health` shows 0 geo units | run `make data-sample` or `make data` |
| Map shows dots instead of polygons | boundaries not loaded – run `python -m pipelines.build --source census_geo` |
| DuckDB "database is locked" | a second process holds the file; stop it or use `SERVEMD_READ_ONLY_WAREHOUSE=true` |
| Pipeline `unknown metric_id` | the loader emits an id that is not in `config/metrics.yaml` – add it (see extending.md) |
