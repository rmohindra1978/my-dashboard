import type { Page } from "@playwright/test";
import { SAMPLE, expect, project, test } from "./fixtures";

const CENTER: [number, number] = [-98, 38.5];
const ZOOM = 3.6;

type Feature = { properties: { geo_id: string; name: string; state_abbr: string; score: number }; geometry: { coordinates: [number, number] } };

async function openMap(page: Page): Promise<Feature[]> {
  const res = page.waitForResponse((r) => r.url().endsWith("/api/map/county") && r.request().method() === "POST");
  await page.goto("/map");
  const features = (await (await res).json()).features as Feature[];
  await expect(page.getByText(`${SAMPLE.counties} features`)).toBeVisible();
  await expect(page.getByTestId("map").locator("canvas")).toBeVisible();
  return features;
}

async function pointOf(page: Page, f: Feature) {
  const box = await page.getByTestId("map").boundingBox();
  if (!box) throw new Error("map not laid out");
  return project(f.geometry.coordinates, CENTER, ZOOM, box);
}

const tooltip = (page: Page) => page.getByText("Click to open profile");

test("map renders points, legend, hover tooltip and click-through", async ({ page }) => {
  const features = await openMap(page);
  expect(features).toHaveLength(SAMPLE.counties);
  await expect(page.getByText("SERVE MD Score", { exact: true })).toBeVisible();

  const maricopa = features.find((f) => f.properties.geo_id === SAMPLE.maricopa.id)!;
  const pt = await pointOf(page, maricopa);
  await expect(async () => {
    await page.mouse.move(pt.x - 30, pt.y - 30);
    await page.mouse.move(pt.x, pt.y);
    await expect(tooltip(page)).toBeVisible({ timeout: 1_000 });
  }).toPass({ timeout: 15_000 });
  const tip = page.locator("div.absolute", { has: tooltip(page) });
  await expect(tip).toContainText(`${SAMPLE.maricopa.name}, AZ`);
  await expect(tip).toContainText(/Score \d+\.\d · Rank \d+/);

  await page.mouse.click(pt.x, pt.y);
  await expect(page).toHaveURL(`/market/county/${SAMPLE.maricopa.id}`);
});

test("state multiselect filters the feature collection", async ({ page }) => {
  await openMap(page);
  const res = page.waitForResponse((r) => r.url().endsWith("/api/map/county") && r.request().postDataJSON()?.states?.[0] === "AZ");
  await page.locator("select[multiple]").selectOption(["AZ"]);
  const body = await (await res).json();
  expect(body.features).toHaveLength(SAMPLE.azCounties);
  for (const f of body.features as Feature[]) expect(f.properties.state_abbr).toBe("AZ");
  await expect(page.getByText(`${SAMPLE.azCounties} features`)).toBeVisible();
});

test("min-score slider hides markets below the threshold", async ({ page }) => {
  const features = await openMap(page);
  const maricopa = features.find((f) => f.properties.geo_id === SAMPLE.maricopa.id)!;
  const lowest = [...features].sort((a, b) => a.properties.score - b.properties.score)[0];
  const threshold = Math.floor(maricopa.properties.score) - 1;
  expect(lowest.properties.score).toBeLessThan(threshold);

  // Wait until the point layer is interactive before filtering.
  const hi = await pointOf(page, maricopa);
  await expect(async () => {
    await page.mouse.move(hi.x - 30, hi.y - 30);
    await page.mouse.move(hi.x, hi.y);
    await expect(tooltip(page)).toBeVisible({ timeout: 1_000 });
  }).toPass({ timeout: 15_000 });
  await page.mouse.move(5, 5);
  await expect(tooltip(page)).toHaveCount(0);

  await page.locator('input[type="range"]').fill(String(threshold));
  await expect(page.getByText(`Min score: ${threshold}`)).toBeVisible();

  const lo = await pointOf(page, lowest);
  await page.mouse.move(lo.x - 30, lo.y - 30);
  await page.mouse.move(lo.x, lo.y);
  await page.waitForTimeout(500);
  await expect(tooltip(page)).toHaveCount(0);

  await page.mouse.move(hi.x - 30, hi.y - 30);
  await page.mouse.move(hi.x, hi.y);
  await expect(tooltip(page)).toBeVisible();
});
