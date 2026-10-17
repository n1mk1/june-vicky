import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

// The Areopagus builder (FR-13) and the Preparation roster's "+" round trip. Expectations are generic
// so the suite passes whether Claude drafts the persona or the keyword heuristic does.

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

  test("edit a custom investor", async ({ page }) => {
    await page.goto("/areopagus");
    const c = card(page, "Builder Test");
    await c.hover();
    await c.getByRole("button", { name: "Edit" }).click();
    const dialog = page.getByRole("dialog", { name: "Edit investor" });
    await dialog.getByLabel("Signature move").fill("Team before traction");
    await dialog.getByRole("button", { name: "Save investor" }).click();
    await expect(dialog).toHaveCount(0);
    await expect(card(page, "Builder Test")).toContainText("Team before traction");
  });

  test("the Preparation “+” builds an investor and seats them", async ({ page }) => {
    await page.goto("/preparation");
    const count = page.getByText(/^Panel · \d\/5$/);
    const seated = Number((await count.textContent())?.match(/(\d)\/5/)?.[1] ?? 0);
    test.skip(seated >= 5, "the panel is already full");
    await page.getByTestId("roster-add").click();
    await expect(page).toHaveURL(/\/areopagus\?build=1&return=preparation/);
    const dialog = await draft(page, "A blunt growth investor who grills founders on the forecast and the burn.");
    await dialog.getByLabel("Name").fill("Roster Test");
    await dialog.getByRole("button", { name: "Save investor" }).click();
    await expect(page).toHaveURL(/\/preparation$/);
    await expect(page.getByTestId("added-note")).toContainText("Built Roster Test and seated them");
    await expect(count).toHaveText(`Panel · ${seated + 1}/5`);
  });
});
