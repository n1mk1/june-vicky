import { expect, test, type Page } from "@playwright/test";

// The access gate's `?next=` return target (WEB-1): only paths on this site are followed. Only the
// URL the gate sends the browser to matters here, so the API is stubbed: the code check (no real
// code, none of the per-IP attempt budget) and everything the landing page loads (none of the
// suite's per-IP request budget either).

async function enterWithNext(page: Page, next: string) {
  const offSite: string[] = [];
  await page.route("**/api/v1/**", (route) => route.fulfill({ status: 503, contentType: "application/json", body: '{"detail":"stubbed"}' }));
  await page.route(
    (url) => url.hostname.endsWith("example.com"),
    (route) => {
      offSite.push(route.request().url());
      return route.abort();
    },
  );
  await page.route("**/api/v1/auth/access", (route) => route.fulfill({ status: 200, contentType: "application/json", body: '{"ok":true}' }));
  await page.goto(`/access?next=${next}`);
  await page.getByLabel("Access code").fill("any-code");
  await page.getByRole("button", { name: /enter/i }).click();
  await expect(page).not.toHaveURL(/\/access/);
  return offSite;
}

test.describe("access gate return target", () => {
  // Each is a way browsers turn a "path" into another host: \ and tab read as /, dot segments
  // collapse to //, and absolute or scheme URLs.
  for (const next of ["/%5Cexample.com", "/%09/example.com", "/.//example.com", "//example.com", "/%2F%2Fexample.com", "https://example.com", "javascript:alert(1)"]) {
    test(`stays on the site for next=${next}`, async ({ page, baseURL }) => {
      const offSite = await enterWithNext(page, next);
      expect(offSite).toEqual([]);
      const url = new URL(page.url());
      expect(url.origin).toBe(new URL(baseURL!).origin);
      expect(url.pathname).toBe("/knowledge");
    });
  }

  test("a same-site path keeps its query and hash", async ({ page }) => {
    const offSite = await enterWithNext(page, encodeURIComponent("/reports?x=1#top"));
    expect(offSite).toEqual([]);
    await expect(page).toHaveURL(/\/reports\?x=1#top$/);
  });
});
