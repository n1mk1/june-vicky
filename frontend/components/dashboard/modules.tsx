"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { OrbScene } from "@/components/fx/scenes";
import { Panel } from "@/components/ui/Panel";
import { ErrorNote, Loading } from "@/components/ui/States";
import { fmtDate, humanize } from "@/lib/format";
import type { AttackItem, ReportSummary, TimeRange, Widget } from "@/lib/types";
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
                className={cn("mt-1.5 h-1.5 shrink-0 rounded-full", a.missing ? "border border-dashed border-ember" : "bg-ember")}
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

/** Pitch readiness as a small widget: the orb with the score in it, and where the score came from. */
export function Readiness({ reports, company }: { reports: ReportSummary[] | undefined; company: string }) {
  const mine = (reports ?? []).filter((r) => r.company === company && r.overall !== null);
  const latest = [...mine].sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  const score = latest?.overall != null ? Math.round(latest.overall * 20) : null;
  return (
    <Panel title="Pitch readiness" marks bodyClassName="flex items-center gap-3 px-3 py-2" className="min-h-[120px]">
      <div
        aria-label={score === null ? "No score yet" : `Readiness ${score} of 100`}
        role="img"
        className="relative aspect-square h-full max-h-[104px] min-h-[64px] shrink-0"
      >
        <div className="absolute inset-0">
          <OrbScene score={score ?? 0} />
        </div>
        <span className="display absolute inset-0 flex items-center justify-center text-[clamp(22px,3.4vh,34px)] tabular-nums">
          {score ?? "—"}
        </span>
      </div>
      <div className="flex min-w-0 flex-col gap-1">
        {latest ? (
          <>
            <span className="font-display text-[15px] leading-tight tracking-[-0.03em]">{humanize(latest.readiness ?? "scored")}</span>
            <span className="text-[11.5px] leading-snug text-ink-2">Last session {fmtDate(latest.created_at)}</span>
            <Link href="/preparation" className="text-[11.5px] text-ink underline underline-offset-2 hover:text-ember">
              Practise again
            </Link>
          </>
        ) : (
          <>
            <span className="text-[11.5px] leading-snug text-ink-2">No session yet.</span>
            <Link href="/preparation" className="text-[11.5px] text-ink underline underline-offset-2 hover:text-ember">
              Face the panel
            </Link>
          </>
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
