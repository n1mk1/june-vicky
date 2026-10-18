import { expect, test, type Locator, type Page } from "@playwright/test";
import { openDashboard } from "./helpers";

/**
 * WCAG AA (4.5:1 for small text), measured on the rendered page: the text colour, with every ancestor's
 * opacity applied, over the colour actually behind it (each ancestor's background composited from the page
 * down). Colours go through a canvas, so any CSS colour syntax the browser computes is handled.
 */
const AA = 4.5;

async function contrast(target: Locator): Promise<number> {
  return target.evaluate((el) => {
    const ctx = document.createElement("canvas").getContext("2d", { willReadFrequently: true })!;
    const rgba = (css: string): [number, number, number, number] => {
      ctx.clearRect(0, 0, 1, 1);
      ctx.fillStyle = "#000";
      ctx.fillStyle = css;
      ctx.fillRect(0, 0, 1, 1);
      const [r, g, b, a] = ctx.getImageData(0, 0, 1, 1).data;
      return [r, g, b, a / 255];
    };
    const over = (fg: number[], a: number, bg: number[]) => fg.slice(0, 3).map((c, i) => c * a + bg[i] * (1 - a));
    const chain: Element[] = [];
    for (let n: Element | null = el; n; n = n.parentElement) chain.push(n);
    let bg = [255, 255, 255];
    let opacity = 1;
    for (const n of chain.reverse()) {
      const s = getComputedStyle(n);
      const c = rgba(s.backgroundColor);
      bg = over(c, c[3], bg);
      opacity *= Number(s.opacity);
    }
    const fg = rgba(getComputedStyle(el).color);
    const text = over(fg, fg[3] * opacity, bg);
    const lum = (rgb: number[]) => {
      const [r, g, b] = rgb.map((v) => {
        const c = v / 255;
        return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    const [hi, lo] = [lum(text), lum(bg)].sort((a, b) => b - a);
    return (hi + 0.05) / (lo + 0.05);
  });
}

function asTheme(page: Page, theme: "dark" | "light") {
  return page.addInitScript((t) => localStorage.setItem("vicky-theme", t), theme);
}

for (const theme of ["light", "dark"] as const) {
  test.describe(`${theme} theme`, () => {
    test("unselected roster cards keep AA text", async ({ page }) => {
      await asTheme(page, theme);
      await page.goto("/preparation");
      const card = page.locator('aside button[aria-pressed="false"]').first();
      await expect(card).toBeVisible();
      for (const part of [card.locator(".font-display").first(), card.locator("span.truncate").first()]) {
        const ratio = await contrast(part);
        expect(ratio, `"${await part.textContent()}" is ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(AA);
      }
    });

    test("ember text keeps AA on glass, on the solid surface and on glass over it", async ({ page }) => {
      await asTheme(page, theme);
      await openDashboard(page);
      await page.evaluate(() => {
        const probe = (parent: Element, id: string) => {
          const s = document.createElement("span");
          s.className = "text-ember text-[11px]";
          s.dataset.probe = id;
          s.textContent = "ember";
          parent.appendChild(s);
        };
        probe(document.querySelector("main section.glass")!, "glass");
        const solid = document.createElement("div");
        solid.className = "bg-surface-solid";
        const glass = document.createElement("div");
        glass.className = "glass";
        solid.appendChild(glass);
        document.querySelector("main")!.appendChild(solid);
        probe(solid, "solid");
        probe(glass, "glass-on-solid");
      });
      for (const id of ["glass", "solid", "glass-on-solid"]) {
        const ratio = await contrast(page.locator(`[data-probe="${id}"]`));
        expect(ratio, `ember on ${id} is ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(AA);
      }
    });
  });
}
