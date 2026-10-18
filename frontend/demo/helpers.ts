import { test as base, type BrowserContext, type Locator, type Page } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

/** Where each recording lands, with a sidecar JSON of the cuts `scripts/demo-videos.mjs` applies. */
export const RAW = join(process.cwd(), "..", "docs", "demo", "raw");
export const ACCESS_CODE = process.env.DEMO_ACCESS_CODE ?? process.env.ACCESS_CODE ?? "vicky-demo";

/** A stretch of the recording to play faster (waiting on the panel, a fill, a draft). */
interface Fast {
  from: number;
  to: number;
  speed: number;
}

/** A cursor the video can see: Playwright moves the real pointer, this dot follows it. */
function cursorScript() {
  const install = () => {
    if (document.getElementById("__demo_cursor")) return;
    const c = document.createElement("div");
    c.id = "__demo_cursor";
    Object.assign(c.style, {
      position: "fixed",
      left: "0",
      top: "0",
      width: "18px",
      height: "18px",
      margin: "-9px 0 0 -9px",
      borderRadius: "50%",
      background: "rgba(255,255,255,0.92)",
      border: "2px solid #ff6a13",
      boxShadow: "0 0 0 5px rgba(255,106,19,0.18), 0 2px 8px rgba(0,0,0,0.45)",
      zIndex: "2147483647",
      pointerEvents: "none",
      transition: "transform 60ms linear",
    });
    document.documentElement.appendChild(c);
    const saved = (() => {
      try {
        return JSON.parse(sessionStorage.getItem("__demo_xy") ?? "null") as [number, number] | null;
      } catch {
        return null;
      }
    })();
    let [x, y] = saved ?? [-60, -60];
    let down = false;
    const place = () => {
      c.style.transform = `translate(${x}px, ${y}px) scale(${down ? 0.72 : 1})`;
    };
    place();
    addEventListener(
      "mousemove",
      (e) => {
        x = e.clientX;
        y = e.clientY;
        place();
        try {
          sessionStorage.setItem("__demo_xy", JSON.stringify([x, y]));
        } catch {}
      },
      true,
    );
    addEventListener("mousedown", () => ((down = true), place()), true);
    addEventListener("mouseup", () => ((down = false), place()), true);
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", install);
  else install();
}

export class Demo {
  private t0 = Date.now();
  private start = 0;
  private fast: Fast[] = [];
  private x = 720;
  private y = 450;
  /** Where captions sit: the bottom edge, or just under the header when the page's own bar is at the bottom. */
  captionAt: "top" | "bottom" = "bottom";

  constructor(
    readonly page: Page,
    readonly name: string,
  ) {}

  /** Seconds into the recording. */
  private now() {
    return (Date.now() - this.t0) / 1000;
  }

  /** Everything before this is cut: the blank page before the first paint. */
  begin() {
    this.start = this.now();
  }

  async pause(ms = 1000) {
    await this.page.waitForTimeout(ms);
  }

  /** A caption pinned to the bottom of the frame. Pass nothing to clear it. */
  async caption(title?: string, body?: string) {
    await this.page.evaluate(
      ([t, b, at]) => {
        document.getElementById("__demo_caption")?.remove();
        if (!t) return;
        const el = document.createElement("div");
        el.id = "__demo_caption";
        Object.assign(el.style, {
          position: "fixed",
          left: "50%",
          ...(at === "top" ? { top: "58px" } : { bottom: "28px" }),
          transform: "translateX(-50%)",
          zIndex: "2147483646",
          pointerEvents: "none",
          display: "flex",
          alignItems: "center",
          gap: "12px",
          maxWidth: "min(880px, 92vw)",
          padding: "10px 16px",
          borderRadius: "4px",
          background: "rgba(10,10,12,0.86)",
          border: "1px solid rgba(255,255,255,0.18)",
          backdropFilter: "blur(10px)",
          color: "#fff",
          boxShadow: "0 10px 30px rgba(0,0,0,0.45)",
          animation: "__demo_in 320ms ease-out",
        });
        const style = document.createElement("style");
        style.textContent = "@keyframes __demo_in{from{opacity:0;transform:translate(-50%,8px)}to{opacity:1;transform:translate(-50%,0)}}";
        el.appendChild(style);
        const tag = document.createElement("span");
        tag.textContent = t;
        Object.assign(tag.style, {
          flex: "none",
          fontFamily: "ui-monospace, 'Martian Mono', monospace",
          fontSize: "11px",
          letterSpacing: "0.04em",
          textTransform: "uppercase",
          padding: "3px 8px",
          background: "#ff6a13",
          color: "#000",
          borderRadius: "2px",
        });
        el.appendChild(tag);
        if (b) {
          const p = document.createElement("span");
          p.textContent = b;
          Object.assign(p.style, { fontFamily: "system-ui, sans-serif", fontSize: "15px", lineHeight: "1.35" });
          el.appendChild(p);
        }
        document.documentElement.appendChild(el);
      },
      [title ?? "", body ?? "", this.captionAt],
    );
  }

  /** Glide the pointer to a point, the way a hand would. */
  async moveTo(x: number, y: number, ms = 650) {
    const steps = Math.max(8, Math.round(ms / 16));
    const [sx, sy] = [this.x, this.y];
    for (let i = 1; i <= steps; i++) {
      const k = i / steps;
      const e = k < 0.5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2; // ease in-out
      await this.page.mouse.move(sx + (x - sx) * e, sy + (y - sy) * e);
    }
    [this.x, this.y] = [x, y];
  }

  private async center(target: Locator) {
    await target.scrollIntoViewIfNeeded();
    const box = await target.boundingBox();
    if (!box) throw new Error(`No box for ${target}`);
    return [box.x + box.width / 2, box.y + box.height / 2] as const;
  }

  async hover(target: Locator, ms?: number) {
    const [x, y] = await this.center(target);
    await this.moveTo(x, y, ms);
    await this.pause(250);
  }

  async click(target: Locator) {
    await target.waitFor({ state: "visible" });
    await this.hover(target);
    await target.click();
    await this.pause(450);
  }

  /** Click into a field and type at reading speed. */
  async type(target: Locator, text: string, delay = 38) {
    await this.click(target);
    await target.pressSequentially(text, { delay });
    await this.pause(400);
  }

  /** Smooth wheel scroll over whatever is under the pointer. */
  async scroll(dy: number, ms = 900) {
    const steps = Math.max(6, Math.round(ms / 30));
    for (let i = 0; i < steps; i++) {
      await this.page.mouse.wheel(0, dy / steps);
      await this.page.waitForTimeout(ms / steps);
    }
    await this.pause(300);
  }

  /** Run a wait (the panel thinking, a draft) and play that stretch at `speed`× in the cut. */
  async fastForward<T>(fn: () => Promise<T>, speed = 6): Promise<T> {
    const from = this.now();
    const out = await fn();
    const to = this.now();
    if (to - from > 1.5) this.fast.push({ from: from + 0.4, to: to - 0.4, speed });
    return out;
  }

  edits() {
    return { start: this.start, fast: this.fast };
  }
}

/** Sign in with the access code, as the gate's form would. */
export async function signIn(context: BrowserContext, baseURL: string) {
  const r = await context.request.post(new URL("/api/v1/auth/access", baseURL).toString(), { data: { code: ACCESS_CODE } });
  if (!r.ok()) throw new Error(`Sign-in failed (${r.status()}). Is the stack running at ${baseURL}?`);
}

/** Skip the intro counter on every page after the landing. */
export async function skipIntro(context: BrowserContext) {
  await context.addInitScript(() => {
    try {
      sessionStorage.setItem("vicky-preloaded", "1");
    } catch {}
  });
}

/** `demo` records one tab; the recording is saved under its name when the test ends. */
export const test = base.extend<{ demo: Demo }>({
  demo: async ({ page, context }, provide, testInfo) => {
    await context.addInitScript(cursorScript);
    const name = testInfo.title.split(" ")[0];
    const demo = new Demo(page, name);
    await provide(demo);
    const video = page.video();
    await page.close();
    if (video && testInfo.status === "passed") {
      mkdirSync(RAW, { recursive: true });
      await video.saveAs(join(RAW, `${name}.webm`));
      writeFileSync(join(RAW, `${name}.json`), JSON.stringify(demo.edits(), null, 2));
    }
  },
});

export { expect } from "@playwright/test";
