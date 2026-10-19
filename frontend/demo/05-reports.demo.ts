import { expect, signIn, skipIntro, test } from "./helpers";

// Reports: every session written up, with its score trend, and one report end to end.
test.beforeEach(async ({ context, baseURL }) => {
  await signIn(context, baseURL!);
  await skipIntro(context);
});

test("05-reports", async ({ page, demo }) => {
  await page.goto("/reports");
  await expect(page.getByRole("heading", { name: "Every session, written up." })).toBeVisible();
  const reports = page.getByRole("link", { name: /Open$/ });
  await expect(reports.first()).toBeVisible();
  demo.begin();
  await demo.pause(800);
  await demo.caption("Reports", "Every Simulation session, written up, with the score trend per company.");
  await demo.pause(1600);
  await demo.hover(page.getByRole("img", { name: /score trend/i }).first());
  await demo.pause(1200);
  const n = Math.min(await reports.count(), 3);
  for (let i = 0; i < n; i++) await demo.hover(reports.nth(i), 500);

  await demo.caption("A report", "Readiness, scores per dimension, every claim checked, and what to fix next.");
  await demo.click(reports.first());
  await expect(page.getByRole("navigation", { name: "Report sections" })).toBeVisible();
  await demo.pause(2500);
  await demo.moveTo(820, 560, 700);
  for (let i = 0; i < 4; i++) {
    await demo.scroll(650, 1400);
    await demo.pause(1100);
  }

  const sections = page.getByRole("navigation", { name: "Report sections" }).getByRole("link");
  if ((await sections.count()) > 1) {
    await demo.caption("Sections", "Jump to any section; the whole report downloads as Markdown.");
    await demo.click(sections.nth(1));
    await demo.pause(2000);
    await demo.click(sections.last());
    await demo.pause(2000);
  }
  await demo.hover(page.getByRole("link", { name: /Download Markdown/i }));
  await demo.pause(1500);
  await demo.caption();
  await demo.pause(300);
});
