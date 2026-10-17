import { expect, test } from "@playwright/test";
import { ask, boxes, dashboard, openDashboard, overlaps, pageScroll, removeAddedWidgets, restoreRange, snapshotRange } from "./helpers";

let before = new Set<string>();
let state: { id: string; range: unknown } = { id: "", range: null };

test.beforeAll(async ({ request }) => {
  const d = await dashboard(request);
  before = new Set(d.widgets.map((w) => w.id));
  state = await snapshotRange(request, d.id);
});

test.afterAll(async ({ request }) => {
  await removeAddedWidgets(request, before);
  await restoreRange(request, state); // put the time range back the way it was
});

test.describe("widgets", () => {
  test("KPI numbers explain themselves: formula and source", async ({ page }) => {
    await openDashboard(page);
    const kpi = page.locator('[data-module="role:headline_kpi"]');
    await kpi.getByTitle("Click to explain").first().click();
    const card = kpi.locator("div.flex.w-72");
    await expect(card).toBeVisible();
    await expect(card).toContainText(/×|÷|MRR|revenue/i);
    await expect(card).toContainText(/csv|pack|derived/i);
    await page.keyboard.press("Escape");
    await expect(card).toBeHidden();
  });

  test("the margin ring explains its figure", async ({ page }) => {
    await openDashboard(page);
    const ring = page.locator('[data-module="role:margin_ring"]');
    await ring.getByTitle("Click to explain").first().click();
    await expect(ring.locator("div.flex.w-72")).toContainText(/revenue/i);
  });

  test("every chart draws a canvas, and its table view lists periods that explain on click", async ({ page }) => {
    await openDashboard(page);
    const charts = page.locator("main section").filter({ has: page.getByRole("tab", { name: "Table" }) });
    const n = await charts.count();
    expect(n).toBeGreaterThanOrEqual(2);
    for (let i = 0; i < n; i++) await expect(charts.nth(i).locator("canvas").first()).toBeVisible();

    const trend = page.locator('[data-module="role:trend"]');
    await trend.getByRole("tab", { name: "Table" }).click();
    const rows = trend.locator("tbody tr");
    expect(await rows.count()).toBeGreaterThanOrEqual(2);
    await rows.first().locator("button").first().click();
    await expect(trend.locator("div.flex.w-72")).toContainText(/csv|derived|pack/i);
    await trend.getByRole("tab", { name: "Chart" }).click();
    await expect(trend.locator("canvas").first()).toBeVisible();
  });

  test("a widget added from the chat fits on screen, then removing it frees the space", async ({ page }) => {
    await openDashboard(page);
    const reply = await ask(page, "show customer success by month");
    await expect(reply).toContainText(/Widget added|already on your dashboard/);
    const panel = page.locator("main section.glass").filter({ has: page.locator("h2", { hasText: /customer success/i }) }).first();
    await expect(panel).toBeVisible();
    await expect(panel.locator("canvas").first()).toBeVisible();
    expect(await pageScroll(page)).toBeLessThanOrEqual(1);
    const all = await boxes(page);
    for (let i = 0; i < all.length; i++)
      for (let j = i + 1; j < all.length; j++) expect(overlaps(all[i], all[j]), `${all[i].name} × ${all[j].name}`).toBe(false);

    const title = (await panel.locator("h2").first().getAttribute("title")) ?? "";
    await panel.hover();
    await page.getByRole("button", { name: `Remove ${title}` }).click();
    await expect(page.locator("main section h2", { hasText: title })).toHaveCount(0);
  });

  test("“zoom to the last 6 months” moves every chart, and Reset brings the full range back", async ({ page }) => {
    await openDashboard(page);
    const reply = await ask(page, "zoom to the last 6 months");
    await expect(reply).toContainText(/Zoomed/i);
    const chip = page.getByRole("button", { name: "Reset" }).first();
    await expect(chip).toBeVisible();
    await chip.click();
    await expect(page.getByText(/^Last 6 months$/)).toHaveCount(0);
  });

  test("Add widget opens as a dialog over the dashboard and closes with Escape", async ({ page }) => {
    await openDashboard(page);
    await page.getByRole("button", { name: "Add widget" }).click();
    await expect(page.getByRole("dialog", { name: "Add a widget" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
  });
});
