# Architecture

```
 public sources ──► pipelines/ (extract → tidy → validate → load) ──► DuckDB warehouse ──► FastAPI ──► React SPA
 Census, CMS,        one module per source            metric_values (long)     engines:        search, profile,
 HRSA, CDC           raw cache in data/raw            market_features (wide)   scoring         rankings, map,
                     provenance in pipeline_runs      geo_units / crosswalk    ranking         score editor,
                                                      geo_boundaries           financial       financial model
```

## Design principles

1. **Registry-driven.** `config/metrics.yaml` declares every source and metric (id, pillar, unit,
   direction, default weight, geography levels, derivation). The API, score editor, market
   profile, data dictionary and pipeline validation all read from it – adding a variable never
   requires a schema migration or front-end change.
2. **Long-format warehouse, wide compute.** Observations are stored once in
   `metric_values(geo_level, geo_id, metric_id, period, value, source_id, loaded_at)`.
   `market_features` is a pivot of the latest observation per metric that engines read as a
   single pandas frame; scoring 3,200 counties × 45 metrics is a vectorized operation.
3. **Pure engines.** `backend/app/engines/*` are side-effect-free functions over pandas frames /
   Pydantic models so they are trivially unit-testable and reusable from the API, batch jobs or
   notebooks.
4. **Editable, versioned configuration.** Score configs and financial scenarios are stored in
   DuckDB app tables. Saving a score config creates a new immutable version so any ranking can be
   reproduced later. Ad-hoc (unsaved) configs can be posted to `/api/rank`, `/api/map/{level}`
   and `/api/score/explain` for live what-if editing.
5. **Offline-first development.** `data/fixtures/` holds a tiny synthetic dataset; `make
   data-sample` builds a warehouse in seconds so tests and the UI run with no network access.
   Real data is a `make data` away.
6. **Public data only.** No PHI. Suppressed cells in CMS files become `NULL` and are handled by the
   missing-data policy rather than imputed.

## Components

### Warehouse (`backend/app/data/warehouse.py`)

| table | purpose |
|---|---|
| `geo_units` | one row per state / county / ZCTA / place: name, state, centroid, land area, CBSA |
| `geo_crosswalk` | parent–child relationships (county→ZCTA, county→place, state→county) with allocation weights |
| `geo_boundaries` | simplified GeoJSON geometry per unit for the map |
| `metric_values` | long-format observations with period + source provenance |
| `market_features` | wide pivot of the latest observation for each (geo, metric) – rebuilt after every load |
| `pipeline_runs` | provenance: source, vintage, row counts, status, error, timestamps |
| `app_score_configs` | versioned SERVE MD Score configurations |
| `app_financial_scenarios` | saved financial-model scenarios (optionally tied to a market) |
| `app_saved_markets` | user watch-list |

Geography ids: state = 2-digit FIPS, county = 5-digit FIPS, ZCTA = 5-digit ZCTA, place = 7-digit
state+place FIPS.

### Pipelines (`pipelines/`)

`pipelines/base.py` defines `Source` with `extract()` (download with caching under `data/raw`)
and `transform()` (return a `Tidy` bundle of metric rows and optional geo rows). `Source.run()`
validates every `metric_id` against the registry, upserts, rebuilds `market_features`, and records
the run. `python -m pipelines.build` orchestrates sources in dependency order (`census_geo` first).

### Engines

- **Scoring** (`engines/scoring`): normalize each metric within the peer group (percentile /
  winsorized min-max / clipped z-score), orient by direction, weight within pillar, weight pillars,
  apply the missing-data policy and coverage threshold → 0–100 score + rank + per-metric
  contributions. See [methodology.md](methodology.md).
- **Ranking** (`engines/ranking`): score the whole geography level once, then filter (state,
  metric thresholds), sort by score / pillar / metric, paginate, export CSV.
- **Financial** (`engines/financial`): monthly simulation for `model_years` of a de novo clinic
  (patient ramp, churn, panel capacity, auto-added providers, FFS / MA / capitated revenue,
  staffing ratios, rent, diagnostics, marketing, overhead, capex, working capital) → annual
  P&L, break-even months, peak cash requirement, ROI, IRR, NPV, terminal value; plus a
  sensitivity grid. See [assumptions.md](assumptions.md).

### API (`backend/app/api`)

FastAPI with Pydantic v2 models. Optional shared-secret auth via `SERVEMD_ACCESS_TOKEN`. When
`frontend/dist` exists the same process serves the SPA with history-API fallback, so a single
container is enough for a private deployment. Interactive docs at `/docs`.

### Frontend (`frontend/`)

React 18 + TypeScript + Vite + Tailwind. TanStack Query for data fetching, React Router for
navigation, Recharts for charts, MapLibre GL for the map (CARTO Positron basemap). A shared
`ScoreConfigProvider` holds the active (possibly unsaved) score configuration so edits in the
Score Editor immediately drive Rankings, Map and market profiles.

## Scaling to every viable US market

- ~3,200 counties, ~33,000 ZCTAs and ~19,000 places fit comfortably in a single DuckDB file
  (< 1 GB with boundaries). Scoring all counties takes tens of milliseconds; all ZCTAs well under a
  second, so rankings recompute live as weights change.
- Boundaries are simplified (Census 1:500k cartographic files) and served per geography level;
  ZCTA / place maps are filtered by state to keep payloads small.
- The warehouse is rebuilt by `make data`; incremental refresh is per source and idempotent
  (upsert on `(geo_level, geo_id, metric_id, period)`).
