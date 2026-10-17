import { expect, test } from "@playwright/test";
import { boxes, dashboard, DESKTOP_SIZES, openDashboard, overlaps, pageScroll } from "./helpers";

test.describe("dashboard layout: every widget on one screen", () => {
  for (const size of DESKTOP_SIZES) {
    test(`no scrolling, no overlaps, nothing behind the chat at ${size.width}x${size.height}`, async ({ page }) => {
      await page.setViewportSize(size);
      await openDashboard(page);

      expect(await pageScroll(page), "the dashboard must not scroll").toBeLessThanOrEqual(1);

      const chat = (await page.getByTestId("dashboard-chat").boundingBox())!;
      const all = await boxes(page);
      expect(all.length).toBeGreaterThanOrEqual(5);
      for (const b of all) {
        expect(b.y, `${b.name} starts above the viewport`).toBeGreaterThanOrEqual(0);
        expect(b.x, `${b.name} starts left of the viewport`).toBeGreaterThanOrEqual(0);
        expect(b.x + b.width, `${b.name} runs off the right edge`).toBeLessThanOrEqual(size.width + 1);
        expect(b.y + b.height, `${b.name} sits behind the chat`).toBeLessThanOrEqual(chat.y + 1);
        expect(b.height, `${b.name} is collapsed`).toBeGreaterThan(60);
      }
      for (let i = 0; i < all.length; i++)
        for (let j = i + 1; j < all.length; j++)
          expect(overlaps(all[i], all[j]), `${all[i].name} overlaps ${all[j].name}`).toBe(false);
    });
  }

  test("the top row is built from the declared modules", async ({ page }) => {
    await openDashboard(page);
    for (const m of ["readiness", "role:margin_ring", "role:headline_kpi", "role:trend", "attack_list"]) {
      await expect(page.locator(`[data-module="${m}"]`)).toHaveCount(1);
    }
    await expect(page.locator('[data-module="readiness"]')).toContainText("Pitch readiness");
    await expect(page.locator('[data-module="attack_list"]')).toContainText("What they'll ask first");
  });

  test("every stored widget is on screen", async ({ page, request }) => {
    await openDashboard(page);
    const d = await dashboard(request);
    const titles = await page.locator("main section h2").evaluateAll((hs) => hs.map((h) => h.getAttribute("title") ?? h.textContent ?? ""));
    for (const w of d.widgets) expect(titles, `widget “${w.spec.title}” is missing`).toContain(w.spec.title);
  });

  test("panels show their content without inner scrolling (the attack list may scroll)", async ({ page }) => {
    await openDashboard(page);
    const overflowing = await page.evaluate(() =>
      [...document.querySelectorAll("main section.glass")]
        .filter((s) => s.getAttribute("data-testid") !== "chat-reply")
        .map((s) => {
          const body = s.querySelector(":scope > div:last-child") as HTMLElement | null;
          return { name: s.querySelector("h2")?.textContent ?? "", over: body ? body.scrollHeight - body.clientHeight : 0 };
        })
        .filter((x) => x.over > 4 && x.name !== "What they'll ask first"),
    );
    expect(overflowing).toEqual([]);
  });

  test("phones stack the widgets and keep them all", async ({ page, request }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await openDashboard(page);
    const d = await dashboard(request);
    const all = await boxes(page);
    expect(all.length).toBeGreaterThanOrEqual(d.widgets.length);
    for (const b of all) expect(b.x + b.width).toBeLessThanOrEqual(391);
  });
});
