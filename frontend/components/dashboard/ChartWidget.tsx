"use client";

import { useMemo, useState } from "react";
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
 * The backend's option, minus Vicky's underscore metadata, plus display formatters for the units
 * it declares and the dashboard-wide time range on its dataZoom. No values are added or changed here.
 */
function prepare(raw: EChartsOptionJson, range: TimeRange | null): Record<string, unknown> {
  const meta = raw._meta ?? {};
  const units = meta.units ?? {};
  const currency = meta.currency ?? null;
  const opt: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(raw)) if (!k.startsWith("_") && k !== "theme") opt[k] = v;
  opt.title = { show: false };

  const yUnits = meta.y_units ?? [];
  if (Array.isArray(opt.yAxis)) {
    opt.yAxis = (opt.yAxis as Record<string, unknown>[]).map((ax, i) =>
      yUnits[i] !== undefined
        ? { ...ax, axisLabel: { ...((ax.axisLabel as object) ?? {}), formatter: (v: number) => fmtAxis(v, yUnits[i], currency) } }
        : ax,
    );
  }

  const template = meta.template;
  if (template === "heatmap") {
    opt.tooltip = {
      ...((opt.tooltip as object) ?? {}),
      formatter: (p: TipParam) => {
        const row = Array.isArray(p.value) ? p.value : [];
        return `${esc(row[1])} · ${esc(row[0])}<br/><b>${esc(fmtValue(row[2] as number, units.value, currency))}</b>`;
      },
    };
  } else if (opt.tooltip && template !== "gauge_ring") {
    opt.tooltip = {
      ...(opt.tooltip as object),
      formatter: (ps: TipParam | TipParam[]) => {
        const arr = Array.isArray(ps) ? ps : [ps];
        const head = arr[0]?.name ?? "";
        const lines = arr.map((p) => {
          const idx = p.encode?.y?.[0];
          const v = Array.isArray(p.value) && idx !== undefined ? p.value[idx] : p.value;
          return `${p.marker}${esc(p.seriesName)} <b style="float:right;margin-left:16px">${esc(
            fmtValue(v as number | null, units[String(p.seriesIndex)], currency),
          )}</b>`;
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
  return opt;
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
  const [table, setTable] = useState(false);
  const option = useMemo(() => (raw ? prepare(raw, timeRange) : null), [raw, timeRange]);
  const ev = widget.evaluated;
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
                  "rounded-full border px-2.5 py-0.5 text-[11px] transition-colors",
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
        <div className="scroll-thin min-h-[180px] flex-1 overflow-auto">
          <table className="w-full border-collapse text-[12px]">
            <thead>
              <tr className="border-b border-line">
                <th className="label px-2 py-1.5 text-left font-normal">Period</th>
                {ev.series.map((s, i) => (
                  <th key={i} className="label px-2 py-1.5 text-right font-normal">
                    {s.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {ev.periods.map((period, j) => (
                <tr key={period}>
                  <td className="px-2 py-1 font-mono text-[10.5px] text-ink-2">{ev.period_labels[j] ?? period}</td>
                  {ev.series.map((s, i) => {
                    const pt = s.points[j];
                    return (
                      <td key={i} className="px-2 py-1 text-right tabular-nums">
                        {pt && pt.value !== null ? (
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
        <div className="min-h-[200px] flex-1">
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
      {notes.length > 0 && <p className="px-1 pt-2 text-[11px] leading-snug text-dim">{notes.join(" ")}</p>}
      {explain && <ExplainCard x={explain} onClose={() => setExplain(null)} className="absolute right-3 bottom-3 z-30" />}
    </Panel>
  );
}
