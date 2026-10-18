import { expect, test, type Page } from "@playwright/test";
import { openDashboard, pageScroll } from "./helpers";

/**
 * MET-26: what building the model left out (a short quarter, a currency with no published rate) is shown
 * on the dashboard and in step 04 of the confirm flow. The notes come from the metrics engine; here they are
 * added to the real responses so the test doesn't depend on which sample the dev database holds.
 */
const NOTES = [
  "Q4 2024 has 1 of 3 months in pl: its amounts are left out rather than summed short (balances still count)",
  "No USD→CAD rate for 2025-03 (Bank of Canada): amounts in USD for that period are left out rather than shown in the wrong currency",
];

async function withNotes(page: Page, pattern: RegExp) {
  await page.route(pattern, async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    const res = await route.fetch();
    const body = await res.json();
    await route.fulfill({ response: res, json: { ...body, model_notes: NOTES } });
  });
}

test("the dashboard shows the data notes behind a chip and still fits one screen", async ({ page }) => {
  await withNotes(page, /\/api\/v1\/dashboards\/active(\?|$)/);
  await openDashboard(page);
  const notes = page.getByTestId("model-notes");
  await expect(notes).toContainText("2 data notes");
  await expect(notes.getByText(NOTES[1])).toBeHidden();
  await notes.locator("summary").click();
  for (const n of NOTES) await expect(notes.getByText(n)).toBeVisible();
  expect(await pageScroll(page), "the dashboard must not scroll").toBeLessThanOrEqual(1);
});

test("no notes, no chip", async ({ page }) => {
  await page.route(/\/api\/v1\/dashboards\/active(\?|$)/, async (route) => {
    const res = await route.fetch();
    await route.fulfill({ response: res, json: { ...(await res.json()), model_notes: [] } });
  });
  await openDashboard(page);
  await expect(page.getByTestId("model-notes")).toHaveCount(0);
});

test("step 04 lists the data notes under the coverage", async ({ page, request }) => {
  const active = await request.get("/api/v1/engagements/active");
  expect(active.ok()).toBeTruthy();
  const { id } = (await active.json()) as { id: string };
  await withNotes(page, new RegExp(`/api/v1/engagements/${id}(\\?|$)`));
  await page.goto(`/knowledge/confirm?e=${id}&step=4`);
  const notes = page.getByTestId("model-notes");
  await expect(notes).toContainText("Left out of the figures");
  for (const n of NOTES) await expect(notes.getByText(n)).toBeVisible();
});
