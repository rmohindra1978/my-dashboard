# Testing

Three layers, fastest first. All of them run offline against synthetic fixtures — no network,
no real data, no PHI.

| layer | tool | location | what it covers | run |
|---|---|---|---|---|
| Unit / engine | pytest | `backend/tests/test_scoring.py`, `test_financial.py`, `test_registry.py`, `pipelines/tests/` | scoring + ranking engines, financial model, metric registry, every ETL loader's `transform()` against small checked-in fixtures | `.venv/bin/pytest -q` |
| API | pytest + FastAPI `TestClient` | `backend/tests/test_api.py` | every `/api/*` route against the sample warehouse | `.venv/bin/pytest -q backend/tests/test_api.py` |
| Frontend unit | Vitest + Testing Library | `frontend/src/**/*.test.ts(x)` | formatting helpers, search box behaviour | `cd frontend && npm test` |
| End-to-end | Playwright (Chromium) | `frontend/e2e/*.spec.ts` | the golden path in a real browser (below) | `cd frontend && npm run e2e` (or `make e2e`) |

`make test` runs pytest + Vitest; `make lint` runs ruff, ESLint and `tsc` (which also type-checks
`e2e/` and `playwright.config.ts`).

## End-to-end tests

### How it runs

`frontend/playwright.config.ts` has a `webServer` block that, from `serve-md-intelligence/`:

1. builds the SPA (`npm --prefix frontend run build`),
2. rebuilds a **throwaway** sample warehouse at `data/warehouse/e2e.duckdb`
   (`python -m pipelines.build --sample --warehouse …`), so tests that save score configs or
   scenarios never touch your dev warehouse and every run starts from the same state,
3. starts FastAPI on `127.0.0.1:8765` (`SERVEMD_WAREHOUSE_PATH=…`), which serves both `/api` and
   the built `frontend/dist`.

A single production-style server was chosen over `vite dev` + API because it has no proxy, no
on-demand module transforms and no dependency re-optimisation reloads, so it is faster and less
flaky. The trade-off is ~15 s for the build at startup.

Other choices:

- The public MapLibre basemap (`basemaps.cartocdn.com`) is intercepted and replaced with an empty
  style, so map tests do not depend on a CDN. Our own score points still render.
- Chromium is launched with SwiftShader (`--use-angle=swiftshader --enable-unsafe-swiftshader`) so
  MapLibre gets WebGL headless on CI machines with no GPU.
- Map hover/click tests compute a feature's pixel position from its coordinates and the page's
  initial view (centre `[-98, 38.5]`, zoom 3.6, Web Mercator). If you change the initial view in
  `MapPage.tsx`, update `CENTER`/`ZOOM` in `e2e/map.spec.ts`.
- One worker, tests run serially: the suite shares one server and takes ~30 s.
- Every test fails if the browser logs a console error or throws an uncaught exception (an auto
  fixture in `e2e/fixtures.ts`).

### Environment variables

| var | default | purpose |
|---|---|---|
| `E2E_PYTHON` | `.venv/bin/python` if present, else `python` | interpreter for the pipeline + uvicorn |
| `E2E_PORT` | `8765` | port for the e2e server |
| `E2E_SKIP_BUILD` | unset | set to skip `vite build` when `frontend/dist` is already current |
| `CI` | unset | on CI: no server reuse, `test.only` forbidden, one retry |

Locally an already-running server on `E2E_PORT` is reused. Stop it if you changed code.

### First run

```bash
cd serve-md-intelligence/frontend
npm install
npx playwright install --with-deps chromium   # once per machine
npm run e2e
npm run e2e:report                            # open the HTML report
```

Failures keep a trace, screenshot and the HTML report in `frontend/test-results/` and
`frontend/playwright-report/` (both git-ignored). On CI the `e2e` job in
`.github/workflows/serve-md-ci.yml` uploads them as the `playwright-report` artifact.

### Golden path covered

Sample warehouse: 5 states (AZ, FL, NC, NV, TX), 12 counties, 6 ZCTAs, 4 places.

| spec | checks |
|---|---|
| `home.spec.ts` | header health shows `N markets · M observations` from `/api/health`; top-10 list; typeahead for "Phoenix", "85004" and "Maricopa" opens `/market/{level}/{id}`; "No matches" |
| `market.spec.ts` | `county/04013`: score badge 0–100, "Rank N of 12", data coverage %, five pillar cards, contribution chart, five metric panels, related ZIPs (85004 → ZCTA profile), "Model a clinic here" opens the financial model with the market preselected |
| `rankings.spec.ts` | 12 counties sorted by score desc; AZ filter → 5 rows; ZCTA → 6 rows; sorting by a pillar reorders and sorts that column desc; CSV export = header + 12 rows; row link → profile |
| `score-editor.spec.ts` | Medicare demand 100 / other pillars 0 → unsaved indicator; Rankings order equals `/api/rank` with that config and differs from default; Map posts the unsaved config; "Save new version" adds it to the dropdown; loading `default` restores the default weights and order; "Discard edits" |
| `map.spec.ts` | canvas, 12 features, legend; hover tooltip on Maricopa; click → profile; state multiselect → 5 AZ features (`/api/map/county` response + on-page count); min-score slider hides markets below the threshold (checked by hovering, since the slider is a client-side layer filter and does not change the on-page feature count) |
| `financial.spec.ts` | `/financial?level=county&id=04013`: 7 KPIs (Year-5 revenue, EBITDA, margin, break-even, peak cash, ROI, IRR) have no NaN; four charts; annual table Year 1–5; negative currency shows as `-$…`, never `$-…`; new patients/month 65 → 90 changes the KPIs; save scenario → listed → delete removes it |

### Adding a test

Import `test`/`expect` from `./fixtures` (not `@playwright/test`) so the console-error check and
basemap stub apply. Use the ids in `SAMPLE`. Prefer role/label locators, and derive expected
values from the API (`request` fixture) instead of hard-coding sample numbers.
