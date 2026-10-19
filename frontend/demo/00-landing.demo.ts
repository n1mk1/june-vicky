import { ACCESS_CODE, expect, test } from "./helpers";

// The way in: the intro, the landing, the access code, and the first look at the app.
test("00-landing", async ({ page, demo }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  demo.begin();
  // The intro counts up, then lifts to show the landing and its 3D mark.
  await expect(page.getByRole("heading", { name: "VIK" })).toBeVisible();
  await demo.pause(4200);
  await demo.caption("Vik", "An AI venture capitalist that knows your numbers before the investors do.");
  await demo.moveTo(520, 380, 1200);
  await demo.moveTo(900, 420, 1400);
  await demo.pause(1500);

  await demo.caption("Get started", "One shared access code opens the app; it becomes a signed, HTTP-only cookie.");
  await demo.click(page.getByRole("link", { name: "Get started" }));
  const code = page.getByPlaceholder("Access code");
  await expect(code).toBeVisible();
  await demo.pause(600);
  await demo.type(code, ACCESS_CODE, 70);
  await code.press("Enter");

  await expect(page).toHaveURL(/\/knowledge/);
  await expect(page.getByRole("heading", { name: "Everything Vik knows." })).toBeVisible();
  await demo.caption("Five tabs", "Knowledge base · Dashboard · Simulation · Areopagus · Reports");
  const nav = page.getByRole("navigation", { name: "Sections" });
  for (const name of ["Knowledge base", "Dashboard", "Simulation", "Areopagus", "Reports"]) {
    await demo.hover(nav.getByRole("link", { name }), 420);
    await demo.pause(250);
  }
  await demo.caption("Light or dark", "Both themes share one set of tokens.");
  await demo.click(page.getByRole("radio", { name: "Light" }));
  await demo.pause(1600);
  await demo.click(page.getByRole("radio", { name: "Dark" }));
  await demo.pause(1400);
  await demo.caption();
  await demo.pause(300);
});
