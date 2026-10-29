import { SAMPLE, expect, test } from "./fixtures";

test("market profile county/04013", async ({ page }) => {
  await page.goto(`/market/county/${SAMPLE.maricopa.id}`);
  await expect(page.locator("h1")).toHaveText(`${SAMPLE.maricopa.name}, AZ`);

  const badge = page.getByTitle("SERVE MD Score (0-100)");
  await expect(badge).toHaveText(/^\d{1,3}\.\d$/);
  const score = Number(await badge.innerText());
  expect(score).toBeGreaterThanOrEqual(0);
  expect(score).toBeLessThanOrEqual(100);

  await expect(page.getByText(new RegExp(`Rank \\d+ of ${SAMPLE.counties}`))).toBeVisible();
  await expect(page.getByText(/Data coverage \d+%/)).toBeVisible();

  const pillars = page.locator(".card", { has: page.getByRole("heading", { name: "Pillar scores" }) });
  await expect(pillars.locator(".grid > div")).toHaveCount(5);
  await expect(pillars.locator(".recharts-surface").first()).toBeVisible();
  await expect(pillars.locator(".recharts-bar-rectangle").first()).toBeVisible();

  for (const panel of ["Medicare demand", "Demographics & growth", "Competition & provider supply", "Health need", "Economics & cost"]) {
    await expect(page.getByRole("heading", { name: panel, exact: true })).toBeVisible();
  }

  const zips = page.locator(".card", { has: page.getByRole("heading", { name: "ZIP codes in this county" }) });
  await expect(zips.getByRole("link", { name: SAMPLE.zip })).toBeVisible();

  const model = page.getByRole("link", { name: "Model a clinic here" });
  await expect(model).toHaveAttribute("href", `/financial?level=county&id=${SAMPLE.maricopa.id}`);
  await model.click();
  await expect(page.getByText(/Modeling for/)).toContainText(`${SAMPLE.maricopa.name}, AZ`);
});

test("related ZIP link opens the ZCTA profile", async ({ page }) => {
  await page.goto(`/market/county/${SAMPLE.maricopa.id}`);
  await page.getByRole("link", { name: SAMPLE.zip, exact: true }).click();
  await expect(page).toHaveURL(`/market/zcta/${SAMPLE.zip}`);
  await expect(page.locator("h1")).toHaveText(`ZIP ${SAMPLE.zip}, AZ`);
});
