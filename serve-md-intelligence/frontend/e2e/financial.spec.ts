import type { Page } from "@playwright/test";
import { SAMPLE, expect, expectNoBadCurrency, test } from "./fixtures";

const KPIS = ["Year 5 revenue", "Year 5 EBITDA", "EBITDA margin (final yr)", "EBITDA break-even", "Peak cash requirement", "ROI", "IRR"];

const kpi = (page: Page, label: string) =>
  page.locator("div.rounded-md", { has: page.getByText(label, { exact: true }) }).locator("div.text-xl");

test.beforeEach(async ({ page }) => {
  await page.goto(`/financial?level=county&id=${SAMPLE.maricopa.id}`);
  await expect(page.getByText(/Modeling for/)).toContainText(`${SAMPLE.maricopa.name}, AZ`);
  await expect(kpi(page, "Year 5 revenue")).toHaveText(/\$/);
});

test("KPIs, charts and annual table render without NaN", async ({ page }) => {
  for (const label of KPIS) {
    const v = kpi(page, label);
    await expect(v).toBeVisible();
    await expect(v).not.toHaveText(/NaN|undefined|^$/);
  }
  await expect(kpi(page, "EBITDA break-even")).toHaveText(/Month \d+|Not reached/);

  for (const chart of ["Monthly revenue vs. EBITDA", "Cumulative cash (J-curve)", "Active patients & provider FTE", "Annual revenue by stream"]) {
    const card = page.locator(".card", { has: page.getByRole("heading", { name: chart }) });
    await expect(card.locator(".recharts-surface").first()).toBeVisible();
  }
  for (let y = 1; y <= 5; y++) await expect(page.getByRole("columnheader", { name: `Year ${y}`, exact: true })).toBeVisible();
  await expect(page.getByRole("row", { name: /^EBITDA -?\$/ })).toBeVisible();

  const body = await page.locator("main").innerText();
  expectNoBadCurrency(body);
  // Expenses are shown as negatives: "-$…", never "$-…".
  expect(body).toMatch(/-\$\d/);
});

test("changing new patients/month 65 → 90 changes KPIs", async ({ page }) => {
  const input = page.getByLabel("New Patients Per Month");
  await expect(input).toHaveValue("65");
  const before = await kpi(page, "Year 5 revenue").innerText();
  const ebitdaBefore = await kpi(page, "Year 5 EBITDA").innerText();
  await input.fill("90");
  await expect(kpi(page, "Year 5 revenue")).not.toHaveText(before);
  await expect(kpi(page, "Year 5 EBITDA")).not.toHaveText(ebitdaBefore);
  expectNoBadCurrency(await page.locator("main").innerText());
});

test("save scenario then delete it", async ({ page }) => {
  const name = `E2E scenario ${Date.now()}`;
  const scenarios = page.locator(".card", { has: page.getByRole("heading", { name: "Scenarios" }) });
  await scenarios.getByPlaceholder("Scenario name").fill(name);
  await scenarios.getByRole("button", { name: "Save", exact: true }).click();
  const item = scenarios.locator("li", { hasText: name });
  await expect(item).toContainText(`(county ${SAMPLE.maricopa.id})`);
  await item.getByRole("button", { name: "delete" }).click();
  await expect(item).toHaveCount(0);
});
