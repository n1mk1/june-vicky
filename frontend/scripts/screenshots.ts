/**
 * Captures every page in both themes into docs/screenshots/pages.
 * Usage: start the app (`npm run build && npm start`), then `npm run screenshots`.
 * Uses the installed Microsoft Edge or Chrome, so no browser download is needed.
 */
import { chromium, type Browser } from "playwright";
import { mkdirSync } from "node:fs";
import path from "node:path";

const BASE = process.env.BASE_URL ?? "http://localhost:3000";
const OUT = path.join(process.cwd(), "docs", "screenshots", "pages");
const PAGES = [
  { slug: "landing", path: "/" },
  { slug: "dashboard", path: "/dashboard" },
  { slug: "simulation", path: "/simulation" },
];
const THEMES = ["dark", "light"] as const;
const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900, isMobile: false },
  { name: "mobile", width: 390, height: 844, isMobile: true },
];

async function launch(): Promise<Browser> {
  const args = ["--enable-unsafe-swiftshader", "--use-angle=swiftshader", "--ignore-gpu-blocklist"];
  for (const channel of ["msedge", "chrome"]) {
    try {
      return await chromium.launch({ channel, args });
    } catch {
      // Try the next installed browser.
    }
  }
  return chromium.launch({ args });
}

async function main() {
  mkdirSync(OUT, { recursive: true });
  const browser = await launch();
  for (const vp of VIEWPORTS) {
    for (const theme of THEMES) {
      const context = await browser.newContext({
        viewport: { width: vp.width, height: vp.height },
        deviceScaleFactor: vp.isMobile ? 2 : 1,
        isMobile: vp.isMobile,
        hasTouch: vp.isMobile,
      });
      // Pick the theme and skip the intro before any page script runs.
      await context.addInitScript((t) => {
        localStorage.setItem("vik-theme", t);
        sessionStorage.setItem("vik-preloaded", "1");
      }, theme);
      const page = await context.newPage();
      for (const p of PAGES) {
        await page.goto(BASE + p.path, { waitUntil: "networkidle" });
        await page.waitForTimeout(2500); // let WebGL scenes and entrance animations settle
        const file = path.join(OUT, `${p.slug}-${theme}-${vp.name}.png`);
        await page.screenshot({ path: file, fullPage: true });
        console.log("saved", path.relative(process.cwd(), file));
      }
      await context.close();
    }
  }

  // The intro itself, mid-count.
  const intro = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await intro.newPage();
  await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(900);
  await page.screenshot({ path: path.join(OUT, "preloader.png") });
  console.log("saved preloader.png");
  await browser.close();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
