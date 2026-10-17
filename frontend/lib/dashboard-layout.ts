/**
 * Layout helpers for the editable part of the dashboard (everything below the wireframe's hero).
 *
 * The backend stores `{widget_id, x, y, w, h}` on a 12-column grid. Editing works on an ordered
 * list: dragging reorders it, resizing changes w/h, and `pack` turns the list back into x/y with
 * the same row-flow rule the backend uses for the default layout, so every tab renders the same
 * arrangement from the stored coordinates.
 */

import type { LayoutItem, TimeRange, Widget } from "./types";

export const COLUMNS = 12;
/** Grid row height in px; a chart at h = 5 is about 360 px tall. */
export const ROW_PX = 60;
export const GAP_PX = 16;

export const MIN_W = 3;
export const MIN_H = 3;
export const MAX_H = 10;

const SCALAR = new Set(["kpi", "gauge_ring"]);

export function defaultSize(w: Widget): { w: number; h: number } {
  if (w.status !== "ok") return { w: 3, h: 3 };
  return SCALAR.has(w.spec.template) ? { w: 3, h: 4 } : { w: 6, h: 5 };
}

/** Flow items in reading order (top to bottom, left to right). */
export function ordered(items: LayoutItem[]): LayoutItem[] {
  return [...items].sort((a, b) => a.y - b.y || a.x - b.x);
}

/** Row-flow packing from `top`: an item that doesn't fit on the current row starts a new one. */
export function pack(items: Pick<LayoutItem, "widget_id" | "w" | "h">[], top: number): LayoutItem[] {
  const out: LayoutItem[] = [];
  let x = 0;
  let y = top;
  let rowH = 0;
  for (const it of items) {
    const w = Math.max(1, Math.min(COLUMNS, Math.round(it.w)));
    const h = Math.max(1, Math.round(it.h));
    if (x + w > COLUMNS) {
      x = 0;
      y += rowH;
      rowH = 0;
    }
    out.push({ widget_id: it.widget_id, x, y, w, h });
    x += w;
    rowH = Math.max(rowH, h);
  }
  return out;
}

/** Move `id` to `index` in the list (no-op when it is already there). */
export function moveTo<T extends { widget_id: string }>(items: T[], id: string, index: number): T[] {
  const from = items.findIndex((i) => i.widget_id === id);
  if (from < 0) return items;
  const to = Math.max(0, Math.min(items.length - 1, index));
  if (from === to) return items;
  const next = [...items];
  const [it] = next.splice(from, 1);
  next.splice(to, 0, it);
  return next;
}

export const sameLayout = (a: LayoutItem[], b: LayoutItem[]) =>
  a.length === b.length &&
  a.every((x, i) => x.widget_id === b[i].widget_id && x.x === b[i].x && x.y === b[i].y && x.w === b[i].w && x.h === b[i].h);

// ---------------------------------------------------------------- time range → dataZoom

/** The first and last month (YYYY-MM) a period covers: 2026-05, 2026-Q2 or 2026. */
export function periodMonths(p: string): [string, string] | null {
  let m = /^(\d{4})-(0[1-9]|1[0-2])$/.exec(p);
  if (m) return [p, p];
  m = /^(\d{4})-Q([1-4])$/.exec(p);
  if (m) {
    const q = Number(m[2]);
    const pad = (n: number) => String(n).padStart(2, "0");
    return [`${m[1]}-${pad(q * 3 - 2)}`, `${m[1]}-${pad(q * 3)}`];
  }
  m = /^(\d{4})$/.exec(p);
  return m ? [`${p}-01`, `${p}-12`] : null;
}

/** Whether a chart's periods are known and in time order, so its zoom can map to months. */
export function chronological(periods: string[] | undefined): boolean {
  if (!periods?.length) return false;
  const spans = periods.map(periodMonths);
  return spans.every((s, i) => s && (i === 0 || s[0] >= spans[i - 1]![0]));
}

/**
 * The months a zoomed window `[start, end]` of a chart's periods covers, or null when the window
 * shows every period (the full range) or the chart's periods can't be mapped.
 */
export function rangeFromWindow(periods: string[] | undefined, win: [number, number]): { from: string; to: string } | null {
  if (!periods || !chronological(periods)) return null;
  const lo = Math.max(0, Math.min(periods.length - 1, Math.round(win[0])));
  const hi = Math.max(lo, Math.min(periods.length - 1, Math.round(win[1])));
  if (lo === 0 && hi === periods.length - 1) return null;
  return { from: periodMonths(periods[lo])![0], to: periodMonths(periods[hi])![1] };
}

/**
 * Category indexes `[start, end]` of a chart's periods that overlap the range, or null when the
 * chart can't follow it (unknown periods, periods not in time order, or nothing overlaps).
 */
export function zoomWindow(periods: string[] | undefined, range: TimeRange | null): [number, number] | null {
  if (!range || !periods || !chronological(periods)) return null; // e.g. bars sorted by value
  const spans = periods.map(periodMonths);
  let lo = -1;
  let hi = -1;
  spans.forEach((s, i) => {
    if (s![1] >= range.from && s![0] <= range.to) {
      if (lo < 0) lo = i;
      hi = i;
    }
  });
  return lo < 0 ? null : [lo, hi];
}
