"use client";

import { GripVertical, X } from "lucide-react";
import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";
import {
  COLUMNS,
  GAP_PX,
  MAX_H,
  MIN_H,
  MIN_W,
  ROW_PX,
  moveTo,
  ordered,
  pack,
} from "@/lib/dashboard-layout";
import type { LayoutItem, TimeRange, Widget } from "@/lib/types";
import { cn } from "@/lib/utils";
import { kindOf } from "./registry";
import { WidgetView } from "./WidgetView";

export type Sized = Pick<LayoutItem, "widget_id" | "w" | "h">;

interface DashboardGridProps {
  widgets: Widget[];
  layout: LayoutItem[];
  /** The widget to flash and scroll to (just added here or in another tab). */
  highlight?: string | null;
  onCommit: (items: Sized[]) => void;
  onRemove: (widgetId: string) => void;
  engagementId: string;
  currency?: string;
  timeRange: TimeRange | null;
  onRangeChange?: (range: { from: string; to: string } | null) => void;
  /**
   * Fit the widgets into the height the parent gives (desktop): rows of side-by-side widgets whose
   * widths follow their stored `w`, sharing the height equally. Order and width stay editable.
   */
  fit?: boolean;
}

/** How many rows fit mode uses: up to six widgets side by side, then two rows, then three. */
export function fitRowCount(n: number): number {
  return n <= 6 ? 1 : n <= 12 ? 2 : 3;
}

/** Rows for fit mode, in order, sharing the widgets as evenly as possible. */
function fitRows<T>(items: T[]): T[][] {
  const n = items.length;
  const rows = fitRowCount(n);
  const per = Math.ceil(n / rows);
  const out: T[][] = [];
  for (let i = 0; i < n; i += per) out.push(items.slice(i, i + per));
  return out;
}

type Gesture =
  | { kind: "move"; id: string; pointer: number; last: string | null }
  | { kind: "resize"; id: string; pointer: number; x0: number; y0: number; w0: number; h0: number; col: number };

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

/** The current flow: widgets with a stored position in reading order, then any without one. */
function flow(widgets: Widget[], layout: LayoutItem[]): Sized[] {
  const ids = new Set(widgets.map((w) => w.id));
  const placed = ordered(layout.filter((l) => ids.has(l.widget_id))).map(({ widget_id, w, h }) => ({ widget_id, w, h }));
  const seen = new Set(placed.map((p) => p.widget_id));
  const rest = widgets.filter((w) => !seen.has(w.id)).map((w) => ({ widget_id: w.id, ...kindOf(w).size }));
  return [...placed, ...rest];
}

/**
 * The editable widget grid below the hero: drag a widget by its grip to reorder, drag the corner
 * to resize (snaps to the 12-column grid), or use the grip with the keyboard (arrows move,
 * Shift + arrows resize). Changes are committed on release; positions come from `pack`, the same
 * rule the backend uses, so other tabs render exactly this arrangement.
 */
export function DashboardGrid({ widgets, layout, highlight, onCommit, onRemove, engagementId, currency, timeRange, onRangeChange, fit }: DashboardGridProps) {
  const grid = useRef<HTMLDivElement>(null);
  const cells = useRef(new Map<string, HTMLDivElement>());
  const [draft, setDraft] = useState<Sized[] | null>(null);
  const [gesture, setGesture] = useState<Gesture | null>(null);
  const items = draft ?? flow(widgets, layout);
  const placed = pack(items, 0);
  const byId = new Map(widgets.map((w) => [w.id, w]));

  useEffect(() => {
    if (!highlight) return;
    cells.current.get(highlight)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [highlight]);

  const commit = (next: Sized[]) => {
    setDraft(null);
    setGesture(null);
    const before = flow(widgets, layout);
    const changed = next.length !== before.length || next.some((n, i) => n.widget_id !== before[i].widget_id || n.w !== before[i].w || n.h !== before[i].h);
    if (changed) onCommit(next);
  };

  const startMove = (e: ReactPointerEvent, id: string) => {
    if (e.button !== 0) return;
    e.preventDefault();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    setDraft(items);
    setGesture({ kind: "move", id, pointer: e.pointerId, last: null });
  };

  const startResize = (e: ReactPointerEvent, id: string) => {
    if (e.button !== 0) return;
    e.preventDefault();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    const g = grid.current?.getBoundingClientRect();
    const col = g ? (g.width - (COLUMNS - 1) * GAP_PX) / COLUMNS + GAP_PX : 100;
    const it = items.find((i) => i.widget_id === id);
    if (!it) return;
    setDraft(items);
    setGesture({ kind: "resize", id, pointer: e.pointerId, x0: e.clientX, y0: e.clientY, w0: it.w, h0: it.h, col });
  };

  const onPointerMove = (e: ReactPointerEvent) => {
    if (!gesture || e.pointerId !== gesture.pointer || !draft) return;
    if (gesture.kind === "resize") {
      const w = clamp(gesture.w0 + Math.round((e.clientX - gesture.x0) / gesture.col), MIN_W, COLUMNS);
      // In fit mode heights are shared equally, so only the width (the widget's share of its row) changes.
      const h = fit ? gesture.h0 : clamp(gesture.h0 + Math.round((e.clientY - gesture.y0) / (ROW_PX + GAP_PX)), MIN_H, MAX_H);
      const cur = draft.find((d) => d.widget_id === gesture.id);
      if (cur && (cur.w !== w || cur.h !== h)) setDraft(draft.map((d) => (d.widget_id === gesture.id ? { ...d, w, h } : d)));
      return;
    }
    // Moving: reorder in front of whichever widget the pointer is over. Waiting for the pointer to
    // reach a different widget before moving again stops two unequal widgets swapping back and forth.
    let over: string | null = null;
    for (const [id, el] of cells.current) {
      if (id === gesture.id) continue;
      const r = el.getBoundingClientRect();
      if (e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom) over = id;
    }
    if (!over || over === gesture.last) {
      if (!over && gesture.last) setGesture({ ...gesture, last: null });
      return;
    }
    const to = draft.findIndex((d) => d.widget_id === over);
    setDraft(moveTo(draft, gesture.id, to));
    setGesture({ ...gesture, last: over });
  };

  const onPointerUp = (e: ReactPointerEvent) => {
    if (!gesture || e.pointerId !== gesture.pointer) return;
    commit(draft ?? items);
  };

  const onKey = (e: KeyboardEvent, id: string) => {
    const i = items.findIndex((x) => x.widget_id === id);
    const it = items[i];
    if (!it) return;
    const step = { ArrowLeft: -1, ArrowUp: -1, ArrowRight: 1, ArrowDown: 1 }[e.key];
    if (step === undefined) return;
    e.preventDefault();
    if (e.shiftKey) {
      const horizontal = e.key === "ArrowLeft" || e.key === "ArrowRight";
      const w = horizontal ? clamp(it.w + step, MIN_W, COLUMNS) : it.w;
      const h = horizontal ? it.h : clamp(it.h + step, MIN_H, MAX_H);
      commit(items.map((x) => (x.widget_id === id ? { ...x, w, h } : x)));
    } else {
      commit(moveTo(items, id, i + step));
    }
  };

  const handlers = {
    onPointerMove,
    onPointerUp,
    onPointerCancel: () => commit(draft ?? items),
  };

  if (fit) {
    return (
      <div ref={grid} className="flex flex-col gap-4 lg:h-full lg:min-h-0" {...handlers}>
        {fitRows(items).map((row) => (
          <div
            key={row.map((r) => r.widget_id).join("|")}
            style={{ "--cols": row.map((r) => `minmax(0,${r.w}fr)`).join(" ") } as CSSProperties}
            className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:min-h-0 lg:flex-1 lg:[grid-template-columns:var(--cols)]"
          >
            {row.map((p) => cell(p, true))}
          </div>
        ))}
      </div>
    );
  }

  return (
    <div ref={grid} className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-12 lg:auto-rows-[60px]" {...handlers}>
      {placed.map((p) => cell(p, false))}
    </div>
  );

  function cell(p: Sized & Partial<Pick<LayoutItem, "x" | "y">>, inFit: boolean) {
        const w = byId.get(p.widget_id);
        if (!w) return null;
        const chart = !kindOf(w).scalar;
        const active = gesture?.id === w.id;
        const style = inFit ? undefined : ({ "--gc": `${(p.x ?? 0) + 1} / span ${p.w}`, "--gr": `${(p.y ?? 0) + 1} / span ${p.h}` } as CSSProperties);
        return (
          <div
            key={w.id}
            ref={(el) => {
              if (el) cells.current.set(w.id, el);
              else cells.current.delete(w.id);
            }}
            style={style}
            data-widget={w.id}
            className={cn(
              "group/cell relative flex min-w-0 transition-[box-shadow,opacity] duration-300 lg:min-h-0 [&>*:first-child]:min-w-0 [&>*:first-child]:flex-1",
              !inFit && "lg:[grid-column:var(--gc)] lg:[grid-row:var(--gr)]",
              chart ? "min-h-[300px] md:col-span-2" : "min-h-[180px]",
              chart && inFit && "lg:col-span-1",
              active && "z-20 opacity-90",
              highlight === w.id && "rounded-[20px] ring-2 ring-ember/70 ring-offset-2 ring-offset-bg",
            )}
          >
            <WidgetView widget={w} engagementId={engagementId} currency={currency} timeRange={timeRange} onRangeChange={onRangeChange} />
            <div
              className={cn(
                "absolute -top-3 left-1/2 z-30 flex -translate-x-1/2 items-center gap-0.5 rounded-full border border-line bg-surface-solid p-0.5 shadow-sm transition-opacity",
                active ? "opacity-100" : "opacity-0 group-hover/cell:opacity-100 focus-within:opacity-100",
              )}
            >
              <button
                type="button"
                onPointerDown={(e) => startMove(e, w.id)}
                onKeyDown={(e) => onKey(e, w.id)}
                className="flex size-6 cursor-grab touch-none items-center justify-center rounded-full text-ink-2 hover:text-ink active:cursor-grabbing"
                aria-label={`Move or resize ${w.spec.title}. Arrow keys move it, Shift with arrows resizes it.`}
                title="Drag to move"
              >
                <GripVertical className="size-3.5" strokeWidth={1.5} />
              </button>
              <button
                type="button"
                onClick={() => onRemove(w.id)}
                className="flex size-6 items-center justify-center rounded-full text-ink-2 hover:text-ember"
                aria-label={`Remove ${w.spec.title}`}
                title="Remove"
              >
                <X className="size-3.5" strokeWidth={1.5} />
              </button>
            </div>
            <span
              onPointerDown={(e) => startResize(e, w.id)}
              aria-hidden
              title="Drag to resize"
              className={cn(
                "absolute right-1 bottom-1 z-30 hidden size-4 cursor-nwse-resize touch-none rounded-br-[16px] border-r-2 border-b-2 border-line-strong transition-opacity lg:block",
                active ? "opacity-100" : "opacity-0 group-hover/cell:opacity-100",
              )}
            />
          </div>
        );
  }
}
