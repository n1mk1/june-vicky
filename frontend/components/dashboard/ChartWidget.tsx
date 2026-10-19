"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { EChart, type ChartClick } from "@/components/charts/EChart";
import { Panel } from "@/components/ui/Panel";
import { fmtAxis, fmtValue } from "@/lib/format";
import { chronological, rangeFromWindow, zoomWindow } from "@/lib/dashboard-layout";
import type { EChartsOptionJson, Provenance, TimeRange, Widget } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ExplainCard, type Explanation } from "./Explain";

const esc = (s: unknown) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] ?? c);

interface TipParam {
  seriesIndex: number;
  seriesName: string;
  name: string;
  marker: string;
  value: unknown;
  encode?: { y?: number[]; value?: number[] };
}

/**
 * The backend's option, minus Vik's underscore metadata, plus display formatters for the units
 * it declares and the dashboard-wide time range on its dataZoom. No values are added or changed here.
 */
function prepare(raw: EChartsOptionJson, range: TimeRange | null, compact = false): Record<string, unknown> {
  const meta = raw._meta ?? {};
  const units = meta.units ?? {};
  const currency = meta.currency ?? null;
  const opt: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(raw)) if (!k.startsWith("_") && k !== "theme") opt[k] = v;
  opt.title = { show: false };

  const yUnits = meta.y_units ?? [];
  if (Array.isArray(opt.yAxis)) {
    // Three ticks read cleanly even in the short panels of the dashboard's first screen.
    opt.yAxis = (opt.yAxis as Record<string, unknown>[]).map((ax, i) => {
      const base = { ...ax, splitNumber: 3 };
      return yUnits[i] !== undefined
        ? { ...base, axisLabel: { ...((ax.axisLabel as object) ?? {}), formatter: (v: number) => fmtAxis(v, yUnits[i], currency) } }
        : base;
    });
  }

  const template = meta.template;
  // Series the backend keeps out of the tooltip (the invisible base bars of a waterfall).
  const series = Array.isArray(opt.series) ? (opt.series as { tooltip?: { show?: boolean } }[]) : [];
  const silent = new Set(series.flatMap((s, i) => (s.tooltip?.show === false ? [i] : [])));
  if (template === "heatmap") {
    opt.tooltip = {
      ...((opt.tooltip as object) ?? {}),
      formatter: (p: TipParam) => {
        const row = Array.isArray(p.value) ? p.value : [];
        return `${esc(row[1])} · ${esc(row[0])}<br/><b>${esc(fmtValue(row[2] as number, units.value, currency))}</b>`;
      },
    };
  } else if (template === "scatter") {
    // Rows are [period, x, y]; each axis has its own unit and name.
    const labels = (meta.labels ?? {}) as { x?: string; y?: string };
    opt.tooltip = {
      ...((opt.tooltip as object) ?? {}),
      formatter: (p: TipParam) => {
        const row = Array.isArray(p.value) ? p.value : [];
        const line = (name: string | undefined, v: unknown, unit: string | null | undefined) =>
          `${esc(name ?? "")} <b style="float:right;margin-left:16px">${esc(fmtValue(v as number | null, unit, currency))}</b>`;
        return `<span style="opacity:.6">${esc(row[0])}</span><br/>${line(labels.x, row[1], units.x)}<br/>${line(labels.y, row[2], units.y)}<br/><span style="opacity:.5;font-size:10px">Click a point to explain</span>`;
      },
    };
  } else if (opt.tooltip && template !== "gauge_ring") {
    opt.tooltip = {
      ...(opt.tooltip as object),
      formatter: (ps: TipParam | TipParam[]) => {
        const arr = (Array.isArray(ps) ? ps : [ps]).filter((p) => !silent.has(p.seriesIndex));
        const head = arr[0]?.name ?? "";
        const lines = arr.flatMap((p) => {
          const idx = p.encode?.y?.[0];
          const v = Array.isArray(p.value) && idx !== undefined ? p.value[idx] : p.value;
          // A waterfall step is up or down: the other half of its split is 0 and says nothing.
          if (template === "waterfall" && v === 0) return [];
          return [
            `${p.marker}${esc(p.seriesName)} <b style="float:right;margin-left:16px">${esc(
              fmtValue(v as number | null, units[String(p.seriesIndex)], currency),
            )}</b>`,
          ];
        });
        return `<span style="opacity:.6">${esc(head)}</span><br/>${lines.join("<br/>")}<br/><span style="opacity:.5;font-size:10px">Click a point to explain</span>`;
      },
    };
  }
  // Room for the legend above the axis unit labels.
  if (opt.grid && opt.legend) opt.grid = { ...(opt.grid as object), top: 52 };
  // The brush toolbox competes with the legend in small panels; keep zoom, drop the toolbox chrome.
  if (opt.toolbox) opt.toolbox = { ...(opt.toolbox as object), show: false };
  // Every chart follows the dashboard's time range ("zoom to the last 6 months").
  // Wheel zoom needs Ctrl, so scrolling the page over a chart scrolls the page.
  const zoom = template === "heatmap" ? null : zoomWindow(meta.periods, range);
  if (Array.isArray(opt.dataZoom)) {
    opt.dataZoom = (opt.dataZoom as Record<string, unknown>[]).map((dz) => ({
      ...dz,
      ...(dz.type === "inside" ? { zoomOnMouseWheel: "ctrl", moveOnMouseWheel: false } : {}),
      ...(zoom ? { startValue: zoom[0], endValue: zoom[1] } : {}),
    }));
  }
  if (compact) {
    // Short panels keep wheel/pinch zoom but drop the slider so the plot keeps its height.
    if (Array.isArray(opt.dataZoom)) opt.dataZoom = (opt.dataZoom as Record<string, unknown>[]).filter((dz) => dz.type === "inside");
    if (opt.grid) opt.grid = { ...(opt.grid as object), bottom: 6, top: opt.legend ? 44 : 28 };
  }
  return opt;
}

/** True when the element is shorter than `px` (so a chart can switch to its compact form). */
function useShort(px: number) {
  const ref = useRef<HTMLDivElement>(null);
  const [short, setShort] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) => setShort(e.contentRect.height < px));
    ro.observe(el);
    return () => ro.disconnect();
  }, [px]);
  return [ref, short] as const;
}

function explainFrom(raw: EChartsOptionJson, widget: Widget, click: ChartClick): Explanation | null {
  const prov = raw._provenance ?? {};
  const meta = raw._meta ?? {};
  const units = meta.units ?? {};
  const ev = widget.evaluated;
  let p: Provenance | undefined;
  let unit: string | null | undefined;
  let name = "";

  if (meta.template === "heatmap" || widget.spec.template === "heatmap") {
    const row = Array.isArray(click.value) ? click.value : [];
    const r = (meta.rows ?? []).indexOf(String(row[1]));
    const i = ev.period_labels.indexOf(String(row[0]));
    const period = ev.periods[i];
    p = prov[String(r)]?.[period];
    unit = units.value;
    name = String(row[1] ?? "");
  } else if (meta.template === "scatter") {
    // One point is two numbers: provenance is {x, y} per period.
    const period = meta.periods?.[click.dataIndex];
    const xy = (period ? prov["0"]?.[period] : undefined) as unknown as { x?: Provenance; y?: Provenance } | undefined;
    if (!xy?.x || !xy.y) return null;
    const labels = (meta.labels ?? {}) as { x?: string; y?: string };
    const x = xy.x;
    const y = xy.y;
    return {
      label: `${labels.y ?? "y"} vs ${labels.x ?? "x"} · ${y.label}`,
      value: y.value,
      unit: units.y,
      currency: meta.currency,
      formula: `${labels.x ?? "x"} ${fmtValue(x.value, units.x, meta.currency)}: ${x.formula} · ${labels.y ?? "y"}: ${y.formula}`,
      inputs: [...x.inputs, ...y.inputs],
      source: y.source ?? x.source,
    };
  } else {
    const period = meta.periods?.[click.dataIndex];
    p = period ? prov[String(click.seriesIndex)]?.[period] : undefined;
    unit = units[String(click.seriesIndex)];
    name = ev.series[click.seriesIndex]?.label ?? "";
  }
  if (!p) return null;
  return {
    label: name ? `${name} · ${p.label}` : p.label,
    value: p.value,
    unit,
    currency: meta.currency,
    formula: p.formula,
    inputs: p.inputs,
    source: p.source,
  };
}

/** Line / area / bar / stacked / combo / heatmap from the backend's option, with click-to-explain and a table view. */
export function ChartWidget({
  widget,
  timeRange = null,
  onRangeChange,
  className,
}: {
  widget: Widget;
  timeRange?: TimeRange | null;
  /** Called when the user zooms this chart: the months now shown, or null for the full range. */
  onRangeChange?: (range: { from: string; to: string } | null) => void;
  className?: string;
}) {
  const raw = widget.option;
  const [explain, setExplain] = useState<Explanation | null>(null);
  // A table widget has no chart to draw: it opens on its Table view.
  const [table, setTable] = useState(widget.spec.template === "table");
  const [box, compact] = useShort(230);
  const option = useMemo(() => (raw ? prepare(raw, timeRange, compact) : null), [raw, timeRange, compact]);
  const ev = widget.evaluated;
  // Table rows follow the option's order (a sorted table stays sorted); a waterfall's invisible base
  // bars are chart scaffolding, not figures, so they get no column.
  const rows = useMemo(() => {
    const at = new Map(ev.periods.map((p, j) => [p, j]));
    const order = (raw?._meta?.periods ?? []).filter((p) => at.has(p));
    return (order.length === ev.periods.length ? order : ev.periods).map((p) => at.get(p)!);
  }, [ev.periods, raw]);
  const columns = ev.series.filter((s) => s.role !== "waterfall_base");
  // Each waterfall step is either up or down; the 0 in the other column is the split, not a figure.
  const waterfall = widget.spec.template === "waterfall";
  const currency = raw?._meta?.currency ?? ev.currency;
  const notes = [...(ev.notes ?? []), ...(raw?._meta?.notes ?? [])].filter((n, i, a) => a.indexOf(n) === i);

  return (
    <Panel
      title={widget.spec.title}
      marks
      className={className}
      aside={
        <div role="tablist" aria-label="View" className="flex gap-1">
          {(["Chart", "Table"] as const).map((v) => {
            const on = (v === "Table") === table;
            return (
              <button
                key={v}
                role="tab"
                aria-selected={on}
                onClick={() => setTable(v === "Table")}
                className={cn(
                  "rounded-[3px] border px-2.5 py-0.5 text-[11px] transition-colors",
                  on ? "border-invert-bg bg-invert-bg text-invert-ink" : "border-line text-ink-2 hover:text-ink",
                )}
              >
                {v}
              </button>
            );
          })}
        </div>
      }
      bodyClassName="relative flex min-h-0 flex-col p-3 pt-3"
    >
      {table ? (
        <div className="scroll-thin min-h-[140px] flex-1 overflow-auto">
          <table className="w-full border-collapse text-[12px]">
            <thead>
              <tr className="border-b border-line">
                <th className="label px-2 py-1.5 text-left font-normal">Period</th>
                {columns.map((s, i) => (
                  <th key={i} className="label px-2 py-1.5 text-right font-normal">
                    {s.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map((j) => (
                <tr key={ev.periods[j]}>
                  <td className="px-2 py-1 font-mono text-[10.5px] text-ink-2">{ev.period_labels[j] ?? ev.periods[j]}</td>
                  {columns.map((s, i) => {
                    const pt = s.points[j];
                    return (
                      <td key={i} className="px-2 py-1 text-right tabular-nums">
                        {pt && pt.value !== null && !(waterfall && pt.value === 0) ? (
                          <button
                            type="button"
                            className="hover:text-ember"
                            onClick={() =>
                              setExplain({
                                label: `${s.label} · ${pt.label}`,
                                value: pt.value,
                                unit: s.unit,
                                currency,
                                formula: pt.formula,
                                inputs: pt.inputs,
                                source: pt.source,
                              })
                            }
                          >
                            {fmtValue(pt.value, s.unit, currency)}
                          </button>
                        ) : (
                          <span className="text-dim">–</span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : option ? (
        <div ref={box} className="min-h-[120px] flex-1" data-compact={compact || undefined}>
          <EChart
            option={option}
            ariaLabel={`${widget.spec.title} chart. Use the Table view for values.`}
            onPointClick={(c) => raw && setExplain(explainFrom(raw, widget, c))}
            onZoom={
              onRangeChange && raw?._meta?.template !== "heatmap" && chronological(raw?._meta?.periods)
                ? (win) => onRangeChange(rangeFromWindow(raw?._meta?.periods, win))
                : undefined
            }
          />
        </div>
      ) : (
        <p className="p-2 text-[12.5px] text-ink-2">No chart for this widget.</p>
      )}
      {notes.length > 0 && !compact && <p className="px-1 pt-2 text-[11px] leading-snug text-dim">{notes.join(" ")}</p>}
      {explain && <ExplainCard x={explain} onClose={() => setExplain(null)} className="absolute right-3 bottom-3 z-30" />}
    </Panel>
  );
}
