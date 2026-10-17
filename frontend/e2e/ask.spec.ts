import { expect, test } from "@playwright/test";
import { ask, boxes, chatInput, dashboard, openDashboard, pageScroll, removeAddedWidgets, restoreRange, snapshotRange } from "./helpers";

let before = new Set<string>();
let state: { id: string; range: unknown } = { id: "", range: null };

test.beforeAll(async ({ request }) => {
  const d = await dashboard(request);
  before = new Set(d.widgets.map((w) => w.id));
  state = await snapshotRange(request, d.id);
});
test.afterAll(async ({ request }) => {
  await removeAddedWidgets(request, before);
  await restoreRange(request, state);
});

// Questions any founder might ask about the data they just loaded. Expectations are generic so the
// suite works on any confirmed data set; numeric answers must carry footnotes.
const QUESTIONS: { q: string; expect: RegExp; numbers?: boolean }[] = [
  { q: "What is my ARR?", expect: /ARR is \$/, numbers: true },
  { q: "what was revenue last month?", expect: /revenue/i, numbers: true },
  { q: "which month had the highest burn?", expect: /highest/i, numbers: true },
  { q: "which month had the lowest revenue?", expect: /lowest/i, numbers: true },
  { q: "total revenue over the last 12 months", expect: /in total/i, numbers: true },
  { q: "average monthly burn over the last 6 months", expect: /averaged|average/i, numbers: true },
  { q: "how is ARR calculated?", expect: /calculated as/i, numbers: true },
  { q: "how did revenue change over the last 12 months?", expect: /went from/i, numbers: true },
  { q: "list revenue by month", expect: /by period/i, numbers: true },
  { q: "which quarter had the highest revenue?", expect: /Q[1-4] 20\d\d/, numbers: true },
  { q: "what's my gross margin?", expect: /gross margin/i, numbers: true },
  { q: "how fast are we growing?", expect: /growth/i, numbers: true },
  { q: "what's my runway?", expect: /runway/i },
  { q: "what does NRR mean?", expect: /retention/i },
  { q: "what are my weak spots?", expect: /investors will push on/i },
  { q: "what data is missing?", expect: /computed|every metric/i },
  { q: "what data do you have?", expect: /your data covers/i },
  { q: "summarise my key metrics", expect: /at a glance/i, numbers: true },
  { q: "why is burn falling?", expect: /burn/i, numbers: true },
  { q: "What valuation should we raise at?", expect: /won't put a number/i },
  { q: "tell me about unicorns on mars", expect: /couldn't find that in your data/i },
];

test.describe("Ask Vicky about the data", () => {
  for (const { q, expect: want, numbers } of QUESTIONS) {
    test(`answers “${q}”`, async ({ page }) => {
      await openDashboard(page);
      const before = await boxes(page);
      const reply = await ask(page, q);
      await expect(chatInput(page), "the prompt clears itself after sending").toHaveValue("");
      await expect(reply.getByTestId("chat-answer")).toHaveText(want);
      if (numbers) {
        // Every number comes with a footnote that names its source.
        const marks = reply.getByRole("button", { name: /^Source \d+:/ });
        expect(await marks.count()).toBeGreaterThanOrEqual(1);
      }
      // The reply opens in an overlay: the widgets keep their size and place, and the page doesn't scroll.
      await expect(page.getByTestId("chat-thread")).toBeVisible();
      expect(await boxes(page)).toEqual(before);
      expect(await pageScroll(page)).toBeLessThanOrEqual(1);
    });
  }

  test("a footnote opens its source card", async ({ page }) => {
    await openDashboard(page);
    const reply = await ask(page, "what was revenue last month?");
    const mark = reply.getByRole("button", { name: /^Source 1:/ });
    await mark.hover();
    await expect(page.getByRole("tooltip")).toContainText(/csv|derived|pack/i);
  });

  test("the overlay keeps the conversation; closing it keeps the thread", async ({ page }) => {
    await openDashboard(page);
    await ask(page, "What is my ARR?");
    const reply = await ask(page, "what's my runway?");
    await expect(reply).toContainText(/runway/i);
    await expect(page.getByTestId("chat-exchange")).toHaveCount(1);
    await page.getByRole("button", { name: "Close the conversation" }).click();
    await expect(page.getByTestId("chat-thread")).toHaveCount(0);
    await page.getByRole("button", { name: /Show conversation \(2\)/ }).click();
    await expect(page.getByTestId("chat-thread")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("chat-thread")).toHaveCount(0);
  });

  test("a click on the dimmed dashboard closes the overlay", async ({ page }) => {
    await openDashboard(page);
    await ask(page, "What is my ARR?");
    await page.getByTestId("chat-backdrop").click({ position: { x: 8, y: 8 } });
    await expect(page.getByTestId("chat-thread")).toHaveCount(0);
  });

  test("the overlay steps aside after a dashboard change", async ({ page }) => {
    await openDashboard(page);
    await ask(page, "zoom to the last 3 months");
    await expect(page.getByTestId("chat-thread")).toHaveCount(0, { timeout: 9_000 });
    await ask(page, "reset zoom");
  });

  test("a suggested follow-up asks it for you", async ({ page }) => {
    await openDashboard(page);
    const reply = await ask(page, "What is my ARR?");
    await reply.getByRole("button", { name: /calculated\?/i }).first().click();
    await expect(page.getByTestId("chat-reply").getByTestId("chat-answer")).toHaveText(/calculated as/i, { timeout: 15_000 });
  });

  test("“Chart it” turns an answer into a widget that still fits", async ({ page }) => {
    await openDashboard(page);
    const reply = await ask(page, "which month had the highest burn?");
    await reply.getByRole("button", { name: "Chart it" }).click();
    await expect(page.getByTestId("chat-reply")).toContainText(/Widget added|already on your dashboard/, { timeout: 15_000 });
    // The pointer is still on the overlay (it holds it open for Undo); once it leaves, the overlay steps aside.
    await page.mouse.move(8, 8);
    await expect(page.getByTestId("chat-thread")).toHaveCount(0, { timeout: 9_000 });
    expect(await pageScroll(page)).toBeLessThanOrEqual(1);
  });
});
