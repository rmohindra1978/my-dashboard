import { readFile } from "node:fs/promises";
import { SAMPLE, expect, rankingMarkets, rankingScores, test } from "./fixtures";

test.describe("rankings", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/rankings");
    await expect(page.locator("table tbody tr")).toHaveCount(SAMPLE.counties);
  });

  test("counties sorted by score desc; state + level filters", async ({ page }) => {
    const scores = await rankingScores(page);
    expect(scores).toEqual([...scores].sort((a, b) => b - a));
    await expect(page.getByText(`${SAMPLE.counties} markets ·`)).toBeVisible();

    await page.locator("select[multiple]").selectOption(["AZ"]);
    await expect(page.locator("table tbody tr")).toHaveCount(SAMPLE.azCounties);
    for (const m of await rankingMarkets(page)) expect(m).toMatch(/, AZ$/);

    await page.locator("select[multiple]").selectOption([]);
    await page.locator("select").first().selectOption("zcta");
    await expect(page.locator("table tbody tr")).toHaveCount(SAMPLE.zctas);
    for (const m of await rankingMarkets(page)) expect(m).toMatch(/^ZIP \d{5}/);
  });

  test("sorting by a pillar changes order", async ({ page }) => {
    const before = await rankingMarkets(page);
    await page.locator("thead th", { hasText: "Health need" }).click();
    await expect(page.locator("thead th", { hasText: "Health need" })).toContainText("▼");
    await expect.poll(() => rankingMarkets(page)).not.toEqual(before);
    const col = await page.locator("thead th").allInnerTexts();
    const idx = col.findIndex((c) => c.startsWith("Health need")) + 1;
    const vals = (await page.locator(`table tbody tr td:nth-child(${idx})`).allInnerTexts()).map(Number);
    expect(vals).toEqual([...vals].sort((a, b) => b - a));
  });

  test("CSV export has a header and one row per market", async ({ page }) => {
    const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Export CSV" }).click()]);
    expect(download.suggestedFilename()).toBe("servemd_rankings_county.csv");
    const lines = (await readFile(await download.path(), "utf8")).trim().split(/\r?\n/);
    expect(lines[0]).toMatch(/geo_id/);
    expect(lines).toHaveLength(1 + SAMPLE.counties);
  });

  test("row link opens the market profile", async ({ page }) => {
    await page.locator("table tbody tr").first().getByRole("link").click();
    await expect(page).toHaveURL(/\/market\/county\/\d{5}$/);
  });
});
