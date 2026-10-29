import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig, devices } from "@playwright/test";

/*
 * E2E runs against a production-style single server: the frontend is built (`vite build`) and
 * FastAPI serves `frontend/dist` plus `/api` on one port, backed by a throwaway synthetic sample
 * warehouse (data/warehouse/e2e.duckdb) so test writes never touch your dev warehouse.
 */
const appRoot = resolve(import.meta.dirname, "..");
const port = Number(process.env.E2E_PORT ?? 8765);
const python = process.env.E2E_PYTHON ?? (existsSync(resolve(appRoot, ".venv/bin/python")) ? ".venv/bin/python" : "python");
const warehouse = "data/warehouse/e2e.duckdb";
const build = process.env.E2E_SKIP_BUILD ? "" : "npm --prefix frontend run build && ";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
        // MapLibre needs WebGL; headless Chromium gets it from SwiftShader.
        launchOptions: { args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] },
      },
    },
  ],
  webServer: {
    cwd: appRoot,
    command:
      `${build}rm -f ${warehouse} ${warehouse}.wal && ${python} -m pipelines.build --sample --warehouse ${warehouse} && ` +
      `SERVEMD_WAREHOUSE_PATH=${warehouse} SERVEMD_ACCESS_TOKEN= ${python} -m uvicorn backend.app.main:app --host 127.0.0.1 --port ${port} --log-level warning`,
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
    stdout: "ignore",
    stderr: "pipe",
  },
});
