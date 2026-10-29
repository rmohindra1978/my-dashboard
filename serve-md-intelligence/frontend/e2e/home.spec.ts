import { SAMPLE, expect, test } from "./fixtures";

test.describe("home & search", () => {
  test("header shows API online with warehouse counts", async ({ page, request }) => {
    const health = await (await request.get("/api/health")).json();
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Where should SERVE MD open next?" })).toBeVisible();
    const badge = page.getByTestId("health");
    await expect(badge).toHaveText(`${health.geo_units.toLocaleString()} markets · ${health.metric_rows.toLocaleString()} observations`);
    await expect(badge).not.toContainText("offline");
    await expect(page.locator("main ol li a")).toHaveCount(10);
  });

  for (const { q, display, href } of [
    { q: "Phoenix", display: "Phoenix, AZ", href: `/market/${SAMPLE.phoenix.level}/${SAMPLE.phoenix.id}` },
    { q: SAMPLE.zip, display: `ZIP ${SAMPLE.zip}`, href: `/market/zcta/${SAMPLE.zip}` },
    { q: "Maricopa", display: "Maricopa County, AZ", href: `/market/county/${SAMPLE.maricopa.id}` },
  ]) {
    test(`typeahead "${q}" opens ${href}`, async ({ page }) => {
      await page.goto("/");
      await page.locator("main").getByLabel("Search markets").fill(q);
      const option = page.getByRole("option", { name: new RegExp(display) }).first();
      await expect(option).toBeVisible();
      await option.click();
      await expect(page).toHaveURL(href);
      await expect(page.locator("h1")).toBeVisible();
    });
  }

  test("unknown query shows no matches", async ({ page }) => {
    await page.goto("/");
    await page.locator("main").getByLabel("Search markets").fill("zzzzqq");
    await expect(page.getByText("No matches")).toBeVisible();
  });
});
