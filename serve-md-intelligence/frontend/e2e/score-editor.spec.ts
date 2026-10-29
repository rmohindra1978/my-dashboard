import type { APIRequestContext } from "@playwright/test";
import { SAMPLE, expect, rankingMarkets, test } from "./fixtures";

type Pillars = Record<string, { label: string; weight: number }>;

async function rankNames(request: APIRequestContext, config: unknown | null): Promise<string[]> {
  const res = await request.post("/api/rank", {
    data: {
      geo_level: "county", config_id: config ? null : "default", config, filters: [], limit: 50, offset: 0,
      include_contributions: false, sort_by: "score", descending: true,
    },
  });
  const body = await res.json();
  return body.rows.map((r: { name: string; state_abbr: string }) => `${r.name}, ${r.state_abbr}`);
}

test("Medicare-only weights drive rankings + map; save new version; reset to default", async ({ page, request }) => {
  const def = await (await request.get("/api/score/configs/default")).json();
  const pillars = def.pillars as Pillars;
  const medicareOnly = {
    ...def,
    pillars: Object.fromEntries(Object.entries(pillars).map(([id, p]) => [id, { ...p, weight: id === "medicare_demand" ? 100 : 0 }])),
  };
  const defaultOrder = await rankNames(request, null);
  const medicareOrder = await rankNames(request, medicareOnly);
  expect(medicareOrder).not.toEqual(defaultOrder);

  await page.goto("/score");
  for (const [id, p] of Object.entries(pillars)) {
    await page.getByLabel(`${p.label} weight`, { exact: true }).fill(id === "medicare_demand" ? "100" : "0");
  }
  await expect(page.getByText("100% of score")).toBeVisible();
  await expect(page.getByRole("button", { name: "Discard edits" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Score Editor/ })).toContainText("•");

  // Client-side navigation keeps the unsaved config in context.
  await page.getByRole("link", { name: "Rankings", exact: true }).click();
  await expect(page.getByText("using unsaved score edits")).toBeVisible();
  await expect.poll(() => rankingMarkets(page)).toEqual(medicareOrder);

  const mapReq = page.waitForRequest((r) => r.url().endsWith("/api/map/county") && r.postDataJSON()?.config?.pillars?.medicare_demand?.weight === 100);
  await page.getByRole("link", { name: "Map", exact: true }).click();
  await mapReq;
  await expect(page.getByText("using unsaved score edits")).toBeVisible();
  await expect(page.getByText(`${SAMPLE.counties} features`)).toBeVisible();

  const id = `e2e-medicare-${Date.now()}`;
  await page.getByRole("link", { name: /Score Editor/ }).click();
  await page.getByPlaceholder("default").fill(id);
  await page.getByRole("button", { name: "Save new version" }).click();
  const picker = page.locator("select").first();
  await expect(picker.locator("option", { hasText: `${id} (v1)` })).toHaveCount(1);
  await expect(picker).toHaveValue(`${id}@1`);
  await expect(page.getByRole("button", { name: "Discard edits" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: /Score Editor/ })).not.toContainText("•");

  await page.getByRole("link", { name: "Rankings", exact: true }).click();
  await expect(page.getByText(`score config: ${id}`)).toBeVisible();
  await expect.poll(() => rankingMarkets(page)).toEqual(medicareOrder);

  // Reset: load the default config back.
  await page.getByRole("link", { name: /Score Editor/ }).click();
  await page.locator("select").first().selectOption(`default@${def.version}`);
  await expect(page.getByLabel("Medicare demand weight", { exact: true })).toHaveValue(String(pillars.medicare_demand.weight));
  await page.getByRole("link", { name: "Rankings", exact: true }).click();
  await expect(page.getByText(/score config:|unsaved score edits/)).toHaveCount(0);
  await expect.poll(() => rankingMarkets(page)).toEqual(defaultOrder);
});

test("Discard edits restores the saved weights", async ({ page }) => {
  await page.goto("/score");
  const slider = page.getByLabel("Medicare demand weight", { exact: true });
  const original = await slider.inputValue();
  await slider.fill("100");
  await expect(page.getByRole("button", { name: "Discard edits" })).toBeVisible();
  await page.getByRole("button", { name: "Discard edits" }).click();
  await expect(slider).toHaveValue(original);
  await expect(page.getByRole("button", { name: "Discard edits" })).toHaveCount(0);
});
