import { expect, test } from "@playwright/test";
import { ask, chatInput, dashboard, openDashboard, removeAddedWidgets, restoreRange, snapshotRange } from "./helpers";

// QA regressions for the dashboard chat, from the 2026-10-18 QA pass (each defect found then is fixed).

let before = new Set<string>();
let state: { id: string; range: unknown } = { id: "", range: null };

test.beforeAll(async ({ request }) => {
  const d = await dashboard(request);
  before = new Set(d.widgets.map((w) => w.id));
  state = await snapshotRange(request, d.id);
});
test.afterEach(async ({ request }) => {
  await removeAddedWidgets(request, before);
  await restoreRange(request, state);
});

test.describe("Dashboard chat QA", () => {
  test("an over-long message gets a readable error, not raw JSON", async ({ page }) => {
    await openDashboard(page);
    await chatInput(page).fill("revenue ".repeat(70));
    expect((await chatInput(page).inputValue()).length).toBeLessThanOrEqual(500); // the box stops at the API's limit
    const reply = await ask(page, "revenue ".repeat(70));
    await expect(reply).not.toContainText(/string_too_long|"loc"|\[\{/);
  });

  test("“Chart it” on a burn answer charts burn alone", async ({ page }) => {
    await openDashboard(page);
    const reply = await ask(page, "which month had the highest burn?");
    await reply.getByRole("button", { name: "Chart it" }).click();
    const added = page.getByTestId("chat-reply");
    await expect(added).toContainText(/Widget added|already on your dashboard/, { timeout: 15_000 });
    await expect(added).not.toContainText(/net income|non-dilutive/i);
  });

  test("“Chart it” on a growth answer never zooms the dashboard", async ({ page }) => {
    await openDashboard(page);
    const reply = await ask(page, "how fast are we growing?");
    const chartIt = reply.getByRole("button", { name: "Chart it" });
    if (!(await chartIt.count())) return; // only offered when the answer can be drawn as one chart
    await chartIt.click();
    await expect(page.getByTestId("chat-reply")).not.toContainText("Working it out", { timeout: 15_000 });
    await expect(page.getByTestId("chat-reply")).not.toContainText(/Zoomed/);
  });

  test("closing with Esc while hovering doesn't stop the next change from stepping aside", async ({ page }) => {
    await openDashboard(page);
    await ask(page, "What is my ARR?");
    const box = (await page.getByTestId("chat-thread").boundingBox())!;
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("chat-thread")).toHaveCount(0);
    await page.mouse.move(8, 8);
    await ask(page, "zoom to the last 3 months");
    await expect(page.getByTestId("chat-thread")).toHaveCount(0, { timeout: 9_000 });
  });

  test("sending the same chart request twice quickly adds one widget", async ({ page, request }) => {
    await openDashboard(page);
    const input = chatInput(page);
    // Opex is mapped in every sample company (depreciation isn't in the harbor-labs one CI seeds).
    for (let i = 0; i < 2; i++) {
      await input.fill("show opex by quarter");
      await input.press("Enter");
    }
    await expect(page.getByTestId("chat-reply")).not.toContainText("Working it out", { timeout: 15_000 });
    await expect(page.getByTestId("chat-exchange").first()).not.toContainText("Working it out", { timeout: 15_000 });
    const d = await dashboard(request);
    expect(d.widgets.filter((w) => w.spec.title === "Operating expenses by quarter")).toHaveLength(1);
  });
});
