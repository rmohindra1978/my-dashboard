import { test as base, expect, type Page } from "@playwright/test";

/** Ids in the synthetic sample warehouse (`python -m pipelines.build --sample`). */
export const SAMPLE = {
  counties: 12,
  zctas: 6,
  azCounties: 5,
  maricopa: { level: "county", id: "04013", name: "Maricopa County" },
  zip: "85004",
  phoenix: { level: "place", id: "0455000" },
} as const;

/** Minimal offline MapLibre style so tests never depend on the public basemap CDN. */
const EMPTY_STYLE = { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": "#f8fafc" } }] };

type Fixtures = { consoleErrors: string[] };

export const test = base.extend<Fixtures>({
  consoleErrors: [
    async ({ page }, use) => {
      const errors: string[] = [];
      page.on("console", (msg) => {
        if (msg.type() === "error") errors.push(msg.text());
      });
      page.on("pageerror", (err) => errors.push(`pageerror: ${err.message}`));
      await page.route(/basemaps\.cartocdn\.com/, (route) => route.fulfill({ json: EMPTY_STYLE }));
      await use(errors);
      expect(errors, "browser console errors").toEqual([]);
    },
    { auto: true },
  ],
});
export { expect };

/** Score cells of the rankings table (3rd column), parsed as numbers. */
export async function rankingScores(page: Page): Promise<number[]> {
  const cells = await page.locator("table tbody tr td:nth-child(3)").allInnerTexts();
  return cells.map((c) => Number(c.trim()));
}

export async function rankingMarkets(page: Page): Promise<string[]> {
  return (await page.locator("table tbody tr td:nth-child(2)").allInnerTexts()).map((t) => t.replace("!", "").trim());
}

export function expectNoBadCurrency(text: string) {
  expect(text).not.toMatch(/\$-/);
  expect(text).not.toMatch(/NaN/);
}

/** Pixel position of [lng, lat] inside a MapLibre container at the given centre/zoom (Web Mercator, 512px tiles). */
export function project(lngLat: [number, number], center: [number, number], zoom: number, box: { x: number; y: number; width: number; height: number }) {
  const world = 512 * 2 ** zoom;
  const toPx = ([lng, lat]: [number, number]) => {
    const s = Math.sin((lat * Math.PI) / 180);
    return [((lng + 180) / 360) * world, (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * world];
  };
  const [px, py] = toPx(lngLat);
  const [cx, cy] = toPx(center);
  return { x: box.x + box.width / 2 + (px - cx), y: box.y + box.height / 2 + (py - cy) };
}
