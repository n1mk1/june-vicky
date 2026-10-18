import { expect, test } from "@playwright/test";

// The Preparation page's roster, setup and prompt bar. The court and sessions API are stubbed where a
// test needs them, so no session is opened and nothing is written.

test.use({ viewport: { width: 1440, height: 900 } });

test.describe("Preparation", () => {
  test("persona ids the Areopagus no longer has don't lock the roster", async ({ page }) => {
    // An old bookmark from before the persona rename: five ids that no longer exist.
    await page.goto("/preparation?panel=james,claire,mark,alex,kenji");
    const count = page.getByText(/^Panel · \d\/5$/);
    await expect(count).toHaveText("Panel · 0/5");
    const seats = page.getByRole("list", { name: "Investors on the panel" }).getByRole("button", { pressed: false });
    await expect(seats.first()).toBeEnabled();
    await seats.first().click();
    await expect(count).toHaveText("Panel · 1/5");
  });

  test("before a session the composer is off; Start session is the way in", async ({ page }) => {
    await page.goto("/preparation");
    await expect(page.getByRole("heading", { name: "Prepare." })).toBeVisible();
    await expect(page.getByLabel("Focus")).toHaveCount(0);
    await expect(page.getByLabel("Your answer")).toBeDisabled();
  });

  test("recent sessions sit behind a button", async ({ page }) => {
    const at = "2026-01-01T09:00:00Z";
    await page.route("**/api/v1/sessions", (route) =>
      route.fulfill({
        json: [
          { id: "e2e-live", mode: "prepare", status: "live", started_at: at, question_count: 2, report_id: null },
          { id: "e2e-done", mode: "prepare", status: "ended", started_at: at, question_count: 3, report_id: "e2e-report" },
        ],
      }),
    );
    await page.goto("/preparation");
    await expect(page.getByTestId("recent-sessions")).toHaveCount(0);
    await page.getByRole("button", { name: /recent sessions/i }).click();
    const list = page.getByTestId("recent-sessions");
    await expect(list.getByRole("button", { name: "Resume" })).toBeVisible();
    await expect(list.getByRole("link", { name: "Report" })).toHaveAttribute("href", "/reports/e2e-report");
    await page.getByRole("button", { name: "Back", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Prepare." })).toBeVisible();
  });

  test("an answer that fails gives the typed text back", async ({ page }) => {
    const session = {
      id: "e2e-stub",
      status: "live",
      mode: "prepare",
      panel: [],
      settings: { question_cap: 8, coaching: "coached", knowledge: false },
      turns: [],
      scores: [],
      claims: [],
      question_count: 0,
      awaiting: "founder",
      next_speaker: null,
      report_id: null,
    };
    await page.route("**/api/v1/court/e2e-stub", (route) => route.fulfill({ json: session }));
    await page.route("**/api/v1/court/e2e-stub/answer", (route) =>
      route.fulfill({ status: 502, contentType: "application/json", body: '{"detail":"The panel is unavailable."}' }),
    );
    await page.goto("/preparation?s=e2e-stub");
    const input = page.getByLabel("Your answer");
    await expect(input).toBeEnabled();
    await input.fill("Retention is 92% from the cohort table");
    await input.press("Enter");
    await expect(page.getByText("The panel is unavailable.")).toBeVisible();
    await expect(input).toHaveValue("Retention is 92% from the cohort table");
  });
});
