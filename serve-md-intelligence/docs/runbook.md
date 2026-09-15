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
enrollment / geographic variation ≈ 2 min, clinician file ≈ 3 min (2.5 M rows), HRSA / CDC < 1 min.

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
