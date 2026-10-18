import { ACCESS_CODE, expect, signIn, skipIntro, test } from "./helpers";

// Dashboard: the confirmed numbers, each with its source, and a question asked of the data.
interface Dash {
  id: string;
  widgets: { id: string }[];
}

let before = new Set<string>();

test.beforeEach(async ({ context, baseURL }) => {
  await signIn(context, baseURL!);
  await skipIntro(context);
  const d = (await (await context.request.get(new URL("/api/v1/dashboards/active", baseURL).toString())).json()) as Dash;
  before = new Set(d.widgets.map((w) => w.id));
});

// Anything the chat added to the dashboard comes off again.
test.afterEach(async ({ request }) => {
  await request.post("/api/v1/auth/access", { data: { code: ACCESS_CODE } });
  const d = (await (await request.get("/api/v1/dashboards/active")).json()) as Dash;
  for (const w of d.widgets) if (!before.has(w.id)) await request.delete(`/api/v1/dashboards/${d.id}/widgets/${w.id}`);
});

test("02-dashboard", async ({ page, demo }) => {
  await page.goto("/dashboard");
  await expect(page.getByTestId("dashboard-chat")).toBeVisible();
  await expect(page.locator("[data-module]").first()).toBeVisible();
  await expect(page.locator("main canvas").first()).toBeVisible({ timeout: 30_000 });
  demo.captionAt = "top";
  demo.begin();
  await demo.pause(1500);
  await demo.caption("Dashboard", "Filled from the knowledge base and confirmed. Every number comes from the metrics engine.");
  await demo.pause(2200);

  // Walk the widgets; charts show their values on hover.
  const canvases = page.locator("main canvas");
  const n = Math.min(await canvases.count(), 4);
  for (let i = 0; i < n; i++) {
    const box = await canvases.nth(i).boundingBox();
    if (!box || box.width < 80) continue;
    await demo.moveTo(box.x + box.width * 0.35, box.y + box.height * 0.55, 700);
    await demo.moveTo(box.x + box.width * 0.7, box.y + box.height * 0.5, 900);
    await demo.pause(500);
  }
  await demo.caption("Sources", "Each widget explains its figure: the formula and the file it came from.");
  await demo.pause(2000);

  // Ask the data a question.
  await demo.caption("Ask Vicky", "Answers are computed, footnoted, and can be pinned to the dashboard as a widget.");
  const input = page.getByTestId("dashboard-chat").getByRole("textbox", { name: /ask vicky/i });
  await demo.type(input, "Which month had the highest burn, and how much runway is left?");
  await input.press("Enter");
  const reply = page.getByTestId("chat-reply");
  await expect(reply).toBeVisible();
  await demo.fastForward(() => expect(reply).not.toContainText("Working it out", { timeout: 90_000 }), 4);
  await demo.pause(1200);
  await demo.hover(reply);
  await demo.pause(3500);

  // Pin the answer to the dashboard as a chart.
  const chartIt = reply.getByRole("button", { name: /chart it/i });
  if (await chartIt.count()) {
    await demo.caption("Chart it", "The answer becomes a widget on the dashboard, with the same source.");
    await demo.click(chartIt.first());
    await demo.fastForward(() => expect(page.getByTestId("chat-reply")).not.toContainText("Working it out", { timeout: 90_000 }), 4);
    await demo.pause(4500);
  }

  const close = page.getByRole("button", { name: "Close the conversation" });
  if (await close.isVisible()) await demo.click(close);
  await demo.pause(1200);
  await demo.caption();
  await demo.pause(300);
});
