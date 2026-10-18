"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { OrbScene } from "@/components/fx/scenes";
import { Panel } from "@/components/ui/Panel";
import { ErrorNote, Loading } from "@/components/ui/States";
import { fmtDate, fmtScore, humanize } from "@/lib/format";
import type { AttackItem, ReportDims, ReportSummary, TimeRange, Widget } from "@/lib/types";
import { errorText } from "@/lib/use-api";
import { cn } from "@/lib/utils";
import { WidgetView } from "./WidgetView";

/**
 * Dashboard modules: the building blocks the layout (`layout.ts`) places. A module is either a
 * stored widget picked by its role (`role:trend`) or a panel that isn't a widget (`readiness`,
 * `attack_list`). To add a panel, add a renderer to `PANELS`; to move anything, edit the layout.
 */
export interface ModuleContext {
  byRole: Map<string, Widget>;
  company: string;
  reports: ReportSummary[] | undefined;
  attack: { items: AttackItem[]; loading: boolean; error: unknown };
  engagementId: string;
  currency?: string;
  timeRange: TimeRange | null;
  onRangeChange?: (range: { from: string; to: string } | null) => void;
}

export function AttackList({ items, loading, error }: { items: AttackItem[]; loading: boolean; error: unknown }) {
  const shown = [...items].sort((a, b) => b.severity - a.severity);
  return (
    <Panel
      title="What they'll ask first"
      aside={shown.length ? <span className="label">{shown.length}</span> : null}
      bodyClassName="scroll-thin overflow-y-auto"
    >
      {loading && !items.length ? (
        <Loading label="Ranking weak spots" className="p-4" />
      ) : error ? (
        <ErrorNote message={errorText(error)} className="p-4" />
      ) : !shown.length ? (
        <p className="p-4 text-[12.5px] text-ink-2">Nothing stands out yet. The panel will still ask about your headline numbers.</p>
      ) : (
        <ol className="divide-y divide-line">
          {shown.map((a) => (
            <li key={a.id} className="flex gap-3 px-4 py-3">
              <span
                className={cn("mt-1.5 h-1.5 shrink-0 rounded-[3px]", a.missing ? "border border-dashed border-ember" : "bg-ember")}
                style={{ width: 6 + a.severity * 18, opacity: 0.4 + a.severity * 0.6 }}
                aria-label={`Severity ${Math.round(a.severity * 100)} of 100`}
                role="img"
              />
              <span className="min-w-0">
                <span className="flex flex-wrap items-baseline gap-x-2">
                  <span className="font-display text-[16px] tracking-[-0.03em]">{a.topic}</span>
                  <span className="font-mono text-[9.5px] uppercase tracking-[-0.04em] text-dim">{humanize(a.lens)}</span>
                </span>
                <span className="block text-[12.5px] leading-snug text-ink-2">{a.detail}</span>
              </span>
            </li>
          ))}
        </ol>
      )}
    </Panel>
  );
}

const DIMS: [keyof ReportDims, string][] = [
  ["accuracy", "Accuracy"],
  ["evidence", "Evidence"],
  ["clarity", "Clarity"],
  ["composure", "Composure"],
  ["investor_fit", "Investor fit"],
];

/**
 * Pitch readiness: the orb with the latest score (0–100) in it, the five scores behind it (0–5,
 * the weakest in ember), and the change since the session before.
 */
export function Readiness({ reports, company }: { reports: ReportSummary[] | undefined; company: string }) {
  const mine = (reports ?? []).filter((r) => r.company === company && r.overall !== null);
  const latest = [...mine].sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  const score = latest?.overall != null ? Math.round(latest.overall * 20) : null;
  const delta = latest?.delta != null ? Math.round(latest.delta * 20) : null;
  const dims = DIMS.map(([k, label]) => ({ k, label, value: latest?.dims?.[k] ?? null })).filter((d) => d.value !== null);
  const weakest = dims.length ? dims.reduce((a, b) => (b.value! < a.value! ? b : a)).k : null;
  return (
    <Panel
      title="Pitch readiness"
      marks
      aside={
        <Link href="/preparation" className="shrink-0 text-[11.5px] text-ink underline underline-offset-2 hover:text-ember">
          {latest ? "Practise again" : "Face the panel"}
        </Link>
      }
      bodyClassName="flex items-center gap-4 overflow-hidden px-4 py-3"
      className="min-h-[150px] lg:min-h-0"
    >
      <div
        aria-label={score === null ? "No score yet" : `Readiness ${score} of 100`}
        role="img"
        className="relative aspect-square h-full max-h-[min(200px,42vw)] min-h-[96px] lg:min-h-[56px] shrink-0"
      >
        <div className="absolute inset-0">
          <OrbScene score={score ?? 0} />
        </div>
        <span className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="display text-[clamp(28px,4.2vh,44px)] leading-none tabular-nums">{score ?? "—"}</span>
          <span className="mt-1 font-mono text-[9px] uppercase tracking-[-0.04em] text-dim">of 100</span>
        </span>
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        {latest ? (
          <>
            <div className="flex flex-col">
              <span className="font-display text-[16px] leading-tight tracking-[-0.03em]">{humanize(latest.readiness ?? "scored")}</span>
              <span className="text-[11px] leading-snug text-ink-2">
                {fmtDate(latest.created_at)}
                {delta !== null && (
                  <>
                    {" · "}
                    <span className={delta < 0 ? "text-ember" : "text-ink"}>
                      {`${delta > 0 ? "+" : delta < 0 ? "−" : "±"}${Math.abs(delta)} since last`}
                    </span>
                  </>
                )}
              </span>
            </div>
            {dims.length > 0 && (
              <dl className="flex flex-col gap-[3px]">
                {dims.map((d) => (
                  <div key={d.k} className="flex items-center gap-2">
                    <dt className={cn("w-[68px] shrink-0 truncate text-[10.5px]", d.k === weakest ? "text-ember" : "text-ink-2")}>{d.label}</dt>
                    <dd className="flex min-w-0 flex-1 items-center gap-1.5">
                      <span className="relative h-[3px] flex-1 overflow-hidden rounded-full bg-line">
                        <span
                          className={cn("absolute inset-y-0 left-0 rounded-full", d.k === weakest ? "bg-ember" : "bg-ink")}
                          style={{ width: `${(Math.max(0, Math.min(5, d.value!)) / 5) * 100}%` }}
                        />
                      </span>
                      <span className="w-6 text-right font-mono text-[10px] tabular-nums text-ink-2">{fmtScore(d.value)}</span>
                    </dd>
                  </div>
                ))}
              </dl>
            )}
          </>
        ) : (
          <span className="text-[11.5px] leading-snug text-ink-2">No session yet. Face the panel to get a score.</span>
        )}
      </div>
    </Panel>
  );
}

function Unavailable({ title }: { title: string }) {
  return (
    <Panel title={title} bodyClassName="p-4">
      <p className="text-[12.5px] text-ink-2">Not available for this data.</p>
    </Panel>
  );
}

/** Panels that aren't stored widgets. */
export const PANELS: Record<string, (ctx: ModuleContext) => ReactNode> = {
  readiness: (ctx) => <Readiness reports={ctx.reports} company={ctx.company} />,
  attack_list: (ctx) => <AttackList {...ctx.attack} />,
};

/** A module by id: `role:<widget role>` or a panel name. */
export function Module({ id, ctx, fallbackTitle }: { id: string; ctx: ModuleContext; fallbackTitle?: string }) {
  if (id.startsWith("role:")) {
    const w = ctx.byRole.get(id.slice(5));
    return w ? (
      <WidgetView widget={w} engagementId={ctx.engagementId} currency={ctx.currency} timeRange={ctx.timeRange} onRangeChange={ctx.onRangeChange} />
    ) : (
      <Unavailable title={fallbackTitle ?? humanize(id.slice(5))} />
    );
  }
  const panel = PANELS[id];
  return panel ? panel(ctx) : <Unavailable title={fallbackTitle ?? humanize(id)} />;
}
