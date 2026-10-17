import { expect, type APIRequestContext, type Locator, type Page } from "@playwright/test";

export interface Box {
  name: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

export const DESKTOP_SIZES = [
  { width: 1366, height: 768 },
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
];

/** Open the dashboard and wait until its widgets and charts have rendered. */
export async function openDashboard(page: Page) {
  await page.goto("/dashboard");
  await expect(page.getByTestId("dashboard-chat")).toBeVisible();
  await expect(page.locator("[data-module]").first()).toBeVisible();
  // Charts draw into canvases once ECharts has loaded.
  await expect(page.locator("main canvas").first()).toBeVisible({ timeout: 20_000 });
  await page.waitForTimeout(400);
}

/** Every panel on the dashboard (widgets, modules) except the chat's own reply. */
export function panels(page: Page): Locator {
  return page.locator("main section.glass, main section.border-dashed").filter({ hasNot: page.getByTestId("chat-answer") });
}

export async function boxes(page: Page): Promise<Box[]> {
  return page.evaluate(() =>
    [...document.querySelectorAll("main section.glass, main section.border-dashed")]
      .filter((e) => e.getAttribute("data-testid") !== "chat-reply")
      .map((e) => {
        const r = e.getBoundingClientRect();
        return { name: e.querySelector("h2")?.textContent ?? "(panel)", x: r.x, y: r.y, width: r.width, height: r.height };
      }),
  );
}

export function overlaps(a: Box, b: Box, tolerance = 1): boolean {
  return a.x + a.width > b.x + tolerance && b.x + b.width > a.x + tolerance && a.y + a.height > b.y + tolerance && b.y + b.height > a.y + tolerance;
}

export async function pageScroll(page: Page): Promise<number> {
  return page.evaluate(() => {
    const doc = document.scrollingElement!;
    const main = document.querySelector("main > div") as HTMLElement | null;
    return Math.max(doc.scrollHeight - doc.clientHeight, main ? main.scrollHeight - main.clientHeight : 0);
  });
}

export function chatInput(page: Page): Locator {
  return page.getByTestId("dashboard-chat").getByRole("textbox", { name: /ask vicky/i });
}

/** Send a message in the dashboard chat and wait for Vicky's reply to settle. */
export async function ask(page: Page, text: string): Promise<Locator> {
  const input = chatInput(page);
  await input.fill(text);
  await input.press("Enter");
  const reply = page.getByTestId("chat-reply");
  await expect(reply).toBeVisible();
  await expect(reply).not.toContainText("Working it out", { timeout: 15_000 });
  return reply;
}

export async function dashboard(api: APIRequestContext) {
  const r = await api.get("/api/v1/dashboards/active");
  expect(r.ok()).toBeTruthy();
  return (await r.json()) as { id: string; widgets: { id: string; role: string; created_by: string; spec: { title: string } }[] };
}

/** Remove every widget that wasn't on the dashboard when `before` was taken. */
export async function removeAddedWidgets(api: APIRequestContext, before: Set<string>) {
  const d = await dashboard(api);
  for (const w of d.widgets) {
    if (!before.has(w.id)) await api.delete(`/api/v1/dashboards/${d.id}/widgets/${w.id}`);
  }
}

/** The dashboard's time range, to put back after tests that zoom. */
export async function snapshotRange(api: APIRequestContext, dashboardId: string) {
  const d = (await (await api.get(`/api/v1/dashboards/${dashboardId}`)).json()) as { time_range: unknown };
  return { id: dashboardId, range: d.time_range };
}

export async function restoreRange(api: APIRequestContext, s: { id: string; range: unknown }) {
  const r = s.range as { from?: string; to?: string; last_months?: number } | null;
  const body = r ? (r.last_months ? { last_months: r.last_months } : { from: r.from, to: r.to }) : null;
  await api.patch(`/api/v1/dashboards/${s.id}/time-range`, { data: { time_range: body } });
}
