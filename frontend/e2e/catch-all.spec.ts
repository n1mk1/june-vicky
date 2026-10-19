import { expect, test, type Page, type Route } from "@playwright/test";
import { ask, openDashboard } from "./helpers";

// The catch-all offer (docs/08-RAG.md §Asking permission): when retrieval can't find the answer in the
// notes, Vik offers to read every note with AI. Nothing is sent until the user presses a button.
// The chat API is stubbed here so the test doesn't depend on a model or on what the vault holds.

const OFFER = {
  kind: "catch_all",
  id: "0123456789abcdef0123456789abcdef",
  prompt: "Search all 12 notes with AI? This reads your whole knowledge base and takes a few seconds.",
  notes: 12,
  expires_at: "2099-01-01T00:00:00Z",
};
const ANSWERED = "“We will hire two engineers before the next round.” [kb:team/Hiring plan.md]";

async function stubChat(page: Page, catchAll: (route: Route, body: { offer_id: string; accept: boolean }) => Promise<void>) {
  const sent: { offer_id: string; accept: boolean }[] = [];
  await page.route(/\/api\/v1\/dashboards\/[^/]+\/chat(\?.*)?$/, (route) =>
    route.fulfill({
      json: {
        kind: "answer", reply: "I couldn't find that in your data.", spec: null, widget_id: null, missing: null,
        time_range: null, dashboard: null, citations: [], suggestions: [], chart: null, offer: OFFER,
      },
    }),
  );
  await page.route(/\/api\/v1\/dashboards\/[^/]+\/chat\/catch-all(\?.*)?$/, async (route) => {
    const body = route.request().postDataJSON() as { offer_id: string; accept: boolean };
    sent.push(body);
    await catchAll(route, body);
  });
  return sent;
}

test.describe("Catch-all offer", () => {
  test("is offered with two buttons and nothing runs until one is pressed", async ({ page }) => {
    const sent = await stubChat(page, (route) =>
      route.fulfill({
        json: {
          kind: "answer", reply: ANSWERED, spec: null, widget_id: null, missing: null, time_range: null, dashboard: null,
          citations: [{ marker: 1, start: 0, end: ANSWERED.length, text: ANSWERED, kind: "note", label: "Hiring plan",
                        display: "team/Hiring plan.md", formula: "", source: { kind: "note", ref: "team/Hiring plan.md" } }],
          suggestions: [], chart: null,
        },
      }),
    );
    await openDashboard(page);
    const reply = await ask(page, "What does the plan say about hiring?");
    const offer = reply.getByTestId("catch-all-offer");
    await expect(offer).toContainText("Search all 12 notes");
    await expect(offer.getByRole("button", { name: "Search all notes" })).toBeVisible();
    await expect(offer.getByRole("button", { name: "No thanks" })).toBeVisible();
    await page.waitForTimeout(500);
    expect(sent).toHaveLength(0);

    await offer.getByRole("button", { name: "Search all notes" }).click();
    await expect(reply.getByTestId("catch-all-answer")).toContainText("two engineers");
    await expect(reply.getByTestId("catch-all-offer")).toHaveCount(0);
    expect(sent).toEqual([{ offer_id: OFFER.id, accept: true }]);
  });

  test("“No thanks” removes the prompt and runs nothing", async ({ page }) => {
    const sent = await stubChat(page, (route) => route.fulfill({ status: 204, body: "" }));
    await openDashboard(page);
    const reply = await ask(page, "What does the plan say about hiring?");
    await reply.getByTestId("catch-all-offer").getByRole("button", { name: "No thanks" }).click();
    await expect(reply.getByTestId("catch-all-offer")).toHaveCount(0);
    await expect(reply.getByTestId("catch-all-answer")).toHaveCount(0);
    expect(sent).toEqual([{ offer_id: OFFER.id, accept: false }]);
  });

  test("an expired offer says so", async ({ page }) => {
    await stubChat(page, (route) => route.fulfill({ status: 410, json: { detail: "This offer expired or was already used." } }));
    await openDashboard(page);
    const reply = await ask(page, "What does the plan say about hiring?");
    await reply.getByTestId("catch-all-offer").getByRole("button", { name: "Search all notes" }).click();
    await expect(reply).toContainText("That offer expired. Ask the question again.");
  });
});

test.describe("Catch-all offer under stress", () => {
  test("a double-click on “Search all notes” sends one request", async ({ page }) => {
    const sent = await stubChat(page, async (route) => {
      await new Promise((r) => setTimeout(r, 400));
      await route.fulfill({
        json: { kind: "answer", reply: ANSWERED, spec: null, widget_id: null, missing: null, time_range: null,
                dashboard: null, citations: [], suggestions: [], chart: null },
      });
    });
    await openDashboard(page);
    const reply = await ask(page, "What does the plan say about hiring?");
    await reply.getByTestId("catch-all-offer").getByRole("button", { name: "Search all notes" }).dblclick();
    await expect(reply.getByTestId("catch-all-answer")).toContainText("two engineers");
    expect(sent).toHaveLength(1);
    await expect(reply).not.toContainText("expired");
  });
});

test.describe("Search index status", () => {
  async function stubStatus(page: Page, index: Record<string, unknown>) {
    await page.route(/\/api\/v1\/kb\/status(\?.*)?$/, async (route) => {
      const real = await route.fetch();
      const body = (await real.json()) as Record<string, unknown>;
      await route.fulfill({ json: { ...body, index: { build_id: "b", built_at: null, notes: 3, chunks: 9, vectors: false,
                                                      changed_since: 0, latest: null, ...index } } });
    });
  }

  test("building, then ready with the changed-notes banner", async ({ page }) => {
    await stubStatus(page, { status: "building" });
    await page.goto("/knowledge");
    await expect(page.getByTestId("search-index-status").first()).toContainText("Building search");
    await page.unroute(/\/api\/v1\/kb\/status(\?.*)?$/);
    await stubStatus(page, { status: "ready", changed_since: 2 });
    await expect(page.getByTestId("search-index-status").first()).toContainText("Search ready · 3 notes", { timeout: 6_000 });
    await expect(page.getByTestId("search-index-stale")).toContainText("2 notes changed since the last Fill");
  });

  test("failed offers Retry, which rebuilds", async ({ page }) => {
    await stubStatus(page, { status: "failed" });
    const rebuilt: string[] = [];
    await page.route(/\/api\/v1\/kb\/index$/, (route) => {
      rebuilt.push(route.request().method());
      return route.fulfill({ json: { build_id: "b2", status: "queued" } });
    });
    await page.goto("/knowledge");
    const status = page.getByTestId("search-index-status").first();
    await expect(status).toContainText("Search failed");
    await status.getByRole("button", { name: "Retry" }).click();
    await expect.poll(() => rebuilt).toEqual(["POST"]);
  });
});
