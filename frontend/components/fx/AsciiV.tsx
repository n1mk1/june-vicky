"use client";

import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";

/**
 * The landing's hero: a big V drawn in digits, black and white, flickering like a dithered
 * point cloud. The V is the wordmark's V (0,0 30,0 62,94.7 94,0 124,0 76,142 48,142); every cell
 * of a character grid gets a brightness from how deep inside the V it is, a soft halo of stray
 * digits outside it, a slow light sweep and per-cell noise. Bright cells draw dense digits (8, 0),
 * dim ones thin digits (1, 7), and some cells re-roll their digit each frame: the flicker.
 */

const V: [number, number][] = [
  [0, 0],
  [30, 0],
  [62, 94.7],
  [94, 0],
  [124, 0],
  [76, 142],
  [48, 142],
];
const V_W = 124;
const V_H = 142;
const DENSE = "8069";
const MID = "5342";
const THIN = "17";
const FPS = 14;

function inside(x: number, y: number): boolean {
  let hit = false;
  for (let i = 0, j = V.length - 1; i < V.length; j = i++) {
    const [xi, yi] = V[i];
    const [xj, yj] = V[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) hit = !hit;
  }
  return hit;
}

function segDist(px: number, py: number, ax: number, ay: number, bx: number, by: number): number {
  const dx = bx - ax;
  const dy = by - ay;
  const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)));
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

/** Signed distance to the V's outline in V units: negative inside. */
function signedDist(x: number, y: number): number {
  let d = Infinity;
  for (let i = 0, j = V.length - 1; i < V.length; j = i++) d = Math.min(d, segDist(x, y, V[j][0], V[j][1], V[i][0], V[i][1]));
  return inside(x, y) ? -d : d;
}

/** A cheap deterministic hash → [0, 1). */
function hash(n: number): number {
  const s = Math.sin(n * 127.1 + 311.7) * 43758.5453;
  return s - Math.floor(s);
}

interface Cell {
  x: number;
  y: number;
  base: number; // 0..1 brightness from the shape
  seed: number;
  ch: string;
}

function buildCells(cols: number, rows: number, cw: number, ch: number): Cell[] {
  // Fit the V (plus room for the halo) into the grid, keeping its proportions on screen.
  const pad = 0.07;
  const scale = Math.min((cols * cw * (1 - pad * 2)) / V_W, (rows * ch * (1 - pad * 2)) / V_H);
  const ox = (cols * cw - V_W * scale) / 2;
  const oy = (rows * ch - V_H * scale) / 2;
  const cells: Cell[] = [];
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const px = c * cw + cw / 2;
      const py = r * ch + ch / 2;
      const vx = (px - ox) / scale;
      const vy = (py - oy) / scale;
      const d = signedDist(vx, vy);
      const seed = hash(r * 997 + c);
      let base: number;
      if (d <= 0) {
        // Inside: brighter towards the middle of each stroke, with large soft patches of light and
        // shade (like a dithered photo) and fine grain on top.
        const depth = Math.min(1, -d / 10);
        const patch =
          0.5 +
          0.28 * Math.sin(vx * 0.11 + 1.3) * Math.sin(vy * 0.09 + 0.4) +
          0.16 * Math.sin((vx + vy) * 0.23 + 2.1) +
          0.1 * Math.sin(vy * 0.6 + vx * 0.05);
        base = Math.max(0.12, Math.min(1, 0.25 + depth * 0.35 + (patch - 0.5) * 0.9 + (seed - 0.5) * 0.18));
      } else {
        // Outside: a fuzzy halo of stray digits that thins out with distance.
        const fall = Math.exp(-d / 7);
        base = seed < fall * 0.9 ? fall * 0.7 : 0;
      }
      // Fade the far top/bottom slightly, like the reference's soft frame.
      base *= 0.75 + 0.25 * Math.sin((Math.PI * (r + 0.5)) / rows);
      if (base > 0.02) cells.push({ x: px, y: py, base, seed, ch: pick(base, seed) });
    }
  }
  return cells;
}

function pick(b: number, r: number): string {
  const set = b > 0.75 ? DENSE : b > 0.4 ? MID : THIN;
  return set[Math.floor(r * set.length) % set.length];
}

export function AsciiV({ className }: { className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    let cells: Cell[] = [];
    let w = 0;
    let h = 0;
    let fontPx = 10;
    let raf = 0;
    let last = 0;
    let frame = 0;

    const layout = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = canvas.clientWidth;
      h = canvas.clientHeight;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      // Small glyphs read as texture, like the reference: about 7–10 px depending on the box.
      fontPx = Math.max(6, Math.min(10, Math.round(Math.min(w, h) / 58)));
      const cw = fontPx * 0.62;
      const ch = fontPx * 0.95;
      cells = buildCells(Math.floor(w / cw), Math.floor(h / ch), cw, ch);
    };

    const draw = (t: number) => {
      ctx.clearRect(0, 0, w, h);
      ctx.font = `${fontPx}px ui-monospace, "Martian Mono", monospace`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      // A soft band of light sweeps diagonally across the V (not with reduced motion).
      const sweep = ((t / 5200) % 1.6) - 0.3;
      for (const c of cells) {
        const along = (c.x / w) * 0.6 + (c.y / h) * 0.4;
        const band = reduced ? 0 : Math.exp(-((along - sweep) ** 2) / 0.012);
        // Flicker: each cell has its own phase; a few cells blink hard every frame. Reduced motion
        // keeps a gentle shimmer: small swings, no hard blinks, fewer digits re-rolled.
        const n = hash(c.seed * 1000 + frame);
        const flick = reduced
          ? 0.9 + 0.1 * Math.sin(t / 400 + c.seed * 40)
          : 0.78 + 0.22 * Math.sin(t / 180 + c.seed * 40) + (n > 0.985 ? 0.6 : 0) - (n < 0.02 ? 0.5 : 0);
        const a = Math.max(0, Math.min(1, c.base * flick + band * 0.35 * c.base));
        if (a < 0.04) continue;
        if (n > (reduced ? 0.985 : 0.93)) c.ch = pick(a, hash(c.seed + frame * 0.37));
        ctx.fillStyle = `rgba(255,255,255,${a.toFixed(3)})`;
        ctx.fillText(c.ch, c.x, c.y);
      }
    };

    const fps = reduced ? 5 : FPS;
    const loop = (t: number) => {
      raf = requestAnimationFrame(loop);
      if (t - last < 1000 / fps) return;
      last = t;
      frame++;
      draw(t);
    };

    layout();
    draw(0);
    raf = requestAnimationFrame(loop);
    const ro = new ResizeObserver(() => {
      layout();
      draw(performance.now());
    });
    ro.observe(canvas);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, []);

  return <canvas ref={ref} aria-hidden className={cn("block h-full w-full", className)} />;
}
