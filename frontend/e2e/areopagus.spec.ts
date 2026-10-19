import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

// The Areopagus builder (FR-13) and the Simulation roster's "+" round trip. Expectations are generic
// so the suite passes whether Gemini drafts the persona or the keyword heuristic does.

const GENERATE_MS = 45_000;
let before = new Set<string>();

async function customIds(api: APIRequestContext): Promise<string[]> {
  const r = await api.get("/api/v1/areopagus");
  expect(r.ok()).toBeTruthy();
  return ((await r.json()) as { id: string; builtin: boolean }[]).filter((p) => !p.builtin).map((p) => p.id);
}

test.beforeAll(async ({ request }) => {
  before = new Set(await customIds(request));
});
test.afterAll(async ({ request }) => {
  for (const id of await customIds(request)) if (!before.has(id)) await request.delete(`/api/v1/areopagus/${id}`);
});
test.use({ viewport: { width: 1440, height: 900 } });

/** Describe an investor in the open builder and wait for the editable draft. */
async function draft(page: Page, description: string) {
  const dialog = page.getByRole("dialog", { name: "New investor" });
  await dialog.getByLabel("Describe the investor").fill(description);
  await dialog.getByRole("button", { name: "Generate" }).click();
  await expect(dialog.getByTestId("draft-source")).toBeVisible({ timeout: GENERATE_MS });
  return dialog;
}

function card(page: Page, name: string) {
  return page.getByRole("list", { name: "Investors" }).getByRole("listitem").filter({ has: page.getByRole("heading", { name }) });
}

test.describe("Areopagus builder", () => {
  test("the builder keeps keyboard focus inside and gives it back on close", async ({ page }) => {
    await page.goto("/areopagus");
    const opener = page.getByRole("button", { name: "New investor" });
    await opener.focus();
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("dialog", { name: "New investor" });
    await expect(dialog.getByLabel("Describe the investor")).toBeFocused();
    const inside = () => dialog.evaluate((d) => d.contains(document.activeElement));
    for (const key of ["Tab", "Tab", "Tab", "Shift+Tab", "Shift+Tab", "Shift+Tab", "Shift+Tab"]) {
      await page.keyboard.press(key);
      expect(await inside(), `focus left the dialog after ${key}`).toBe(true);
    }
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(opener).toBeFocused();
  });

  test("describe an investor, adjust the draft, save it", async ({ page }) => {
    await page.goto("/areopagus");
    await page.getByRole("button", { name: "New investor" }).click();
    const dialog = await draft(page, "A patient seed investor who cares most about the team and the size of the market.");
    // The draft fills the form; the founder edits before saving.
    await expect(dialog.getByLabel("Name")).not.toHaveValue("");
    await expect(dialog.getByRole("list", { name: "Lens weights" }).getByRole("slider")).toHaveCount(12);
    await dialog.getByLabel("Name").fill("Builder Test");
    await dialog.getByRole("button", { name: "Save investor" }).click();
    await expect(dialog).toHaveCount(0);
    await expect(card(page, "Builder Test")).toContainText("Custom");
  });

  test("edit a custom investor", async ({ page, request }) => {
    // Its own investor: a retry runs in a fresh worker, after afterAll has removed what earlier tests saved.
    const name = `Edit ${Date.now().toString(36)}`;
    const made = await request.post("/api/v1/areopagus", {
      data: { name, signature_move: "Asks about the market first", priorities: { team: 0.6, market: 0.8 } },
    });
    expect(made.ok()).toBeTruthy();
    await page.goto("/areopagus");
    const c = card(page, name);
    await c.hover();
    await c.getByRole("button", { name: "Edit" }).click();
    const dialog = page.getByRole("dialog", { name: "Edit investor" });
    // The form appears once the saved investor has loaded, filled with it.
    await expect(dialog.getByLabel("Name")).toHaveValue(name);
    await dialog.getByLabel("Signature move").fill("Team before traction");
    await dialog.getByRole("button", { name: "Save investor" }).click();
    await expect(dialog).toHaveCount(0);
    await expect(card(page, name)).toContainText("Team before traction");
  });

  test("the Simulation “+” builds an investor and seats them", async ({ page }) => {
    await page.goto("/simulation");
    const count = page.getByText(/^Panel · \d\/5$/);
    // A full panel has no seat for the new investor: free one first.
    if ((await count.textContent())?.includes("5/5")) {
      await page.getByRole("list", { name: "Investors on the panel" }).getByText("Socrates", { exact: true }).click();
      await expect(count).toHaveText("Panel · 4/5");
    }
    const seated = Number((await count.textContent())?.match(/(\d)\/5/)?.[1] ?? 0);
    await page.getByTestId("roster-add").click();
    await expect(page).toHaveURL(/\/areopagus\?build=1&return=simulation/);
    const dialog = await draft(page, "A blunt growth investor who grills founders on the forecast and the burn.");
    await dialog.getByLabel("Name").fill("Roster Test");
    await dialog.getByRole("button", { name: "Save investor" }).click();
    await expect(page).toHaveURL(/\/simulation$/);
    await expect(page.getByTestId("added-note")).toContainText("Built Roster Test and seated them");
    await expect(count).toHaveText(`Panel · ${seated + 1}/5`);
  });
});
