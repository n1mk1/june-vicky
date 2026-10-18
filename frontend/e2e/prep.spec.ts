import { expect, test } from "@playwright/test";

// The Preparation page's roster and prompt bar. The court API is stubbed where a test needs it to
// fail, so no session is opened and nothing is written.

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

  test("a send that fails gives the typed text back", async ({ page }) => {
    await page.route("**/api/v1/court/start", (route) =>
      route.fulfill({ status: 502, contentType: "application/json", body: '{"detail":"The panel is unavailable."}' }),
    );
    await page.goto("/preparation");
    const input = page.getByLabel("Your answer");
    await expect(input).toBeEnabled();
    await input.fill("Grill me on retention");
    await input.press("Enter");
    await expect(page.getByText("The panel is unavailable.")).toBeVisible();
    await expect(input).toHaveValue("Grill me on retention");
  });
});
