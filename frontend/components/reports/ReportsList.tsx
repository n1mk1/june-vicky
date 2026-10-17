"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useActiveEngagement } from "@/components/app/EngagementProvider";
import { Panel } from "@/components/ui/Panel";
import { PillLink } from "@/components/ui/Pill";
import { EmptyState, ErrorNote, Loading } from "@/components/ui/States";
import { fmtDate, fmtScore, humanize } from "@/lib/format";
import type { ReportSummary } from "@/lib/types";
import { errorText, useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";

/** Overall score per session, oldest to newest. */
function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return null;
  const w = 96;
  const h = 24;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * w},${h - (Math.max(0, Math.min(5, v)) / 5) * h}`).join(" ");
  return (
    <svg viewBox={`-2 -2 ${w + 4} ${h + 4}`} className="h-6 w-24" role="img" aria-label={`Overall score trend: ${values.map((v) => v.toFixed(1)).join(", ")}`}>
      <polyline points={pts} fill="none" stroke="var(--ink)" strokeWidth="1.25" strokeLinejoin="round" />
      <circle cx={w} cy={h - (Math.max(0, Math.min(5, values[values.length - 1])) / 5) * h} r="2" fill="var(--ember)" />
    </svg>
  );
}

function Delta({ d }: { d: number | null | undefined }) {
  if (d === null || d === undefined) return <span className="text-dim">–</span>;
  return <span className={d < 0 ? "text-ember" : "text-ink"}>{`${d > 0 ? "+" : d < 0 ? "−" : "±"}${Math.abs(d).toFixed(1)}`}</span>;
}

/** Reports grouped by engagement (company), the active one first (UI doc §3.8). */
export function ReportsList() {
  const res = useApi<ReportSummary[]>("reports");
  const { engagement } = useActiveEngagement();
  const activeName = engagement?.profile?.name || engagement?.name;

  if (res.loading && !res.data) return <Loading label="Loading reports" className="p-2" />;
  if (res.error && !res.data) return <ErrorNote message={errorText(res.error)} onRetry={res.reload} className="p-2" />;
  const reports = res.data ?? [];

  if (!reports.length) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <EmptyState label="Reports" title="No reports yet." body="Every Preparation session ends with a report: verdict, a stronger answer for each question, the claims ledger and sources.">
          <PillLink href="/preparation" label="Start a session" variant="solid" />
        </EmptyState>
      </div>
    );
  }

  const groups = new Map<string, ReportSummary[]>();
  for (const r of reports) groups.set(r.company, [...(groups.get(r.company) ?? []), r]);
  const ordered = [...groups.entries()].sort(([a], [b]) => (a === activeName ? -1 : b === activeName ? 1 : 0));

  return (
    <div className="scroll-thin -mx-1 min-h-0 flex-1 overflow-y-auto px-1 pb-6">
      <div className="mx-auto flex w-full max-w-[1080px] flex-col gap-6">
        <header className="flex flex-col gap-3 pt-2">
          <span className="label">Reports</span>
          <h1 className="display text-[clamp(40px,5vw,76px)]">Every session, written up.</h1>
        </header>
        {ordered.map(([company, rows]) => {
          const sorted = [...rows].sort((a, b) => b.created_at.localeCompare(a.created_at));
          const trend = [...sorted]
            .reverse()
            .map((r) => r.overall)
            .filter((v): v is number => typeof v === "number");
          return (
            <Panel
              key={company}
              title={company}
              marks
              aside={
                <span className="flex items-center gap-3">
                  <Sparkline values={trend} />
                  {company === activeName && <span className="rounded-full bg-invert-bg px-2 py-0.5 font-mono text-[9.5px] uppercase text-invert-ink">Active</span>}
                </span>
              }
            >
              <ul className="divide-y divide-line">
                {sorted.map((r) => (
                  <li key={r.id}>
                    <Link
                      href={`/reports/${encodeURIComponent(r.id)}`}
                      className="group grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-1 px-4 py-3 transition-colors hover:bg-surface-solid/40 sm:grid-cols-[auto_1fr_auto_auto_auto]"
                    >
                      <span className="rounded-full border border-line px-2 py-0.5 font-mono text-[9.5px] uppercase tracking-[-0.04em] justify-self-start text-ink-2">
                        Prepare
                      </span>
                      <span className="col-span-2 text-[12.5px] text-ink-2 sm:col-span-1">
                        {fmtDate(r.created_at, true)}
                        {r.readiness ? ` · ${humanize(r.readiness)}` : ""}
                      </span>
                      <span className="font-display text-[22px] tracking-[-0.04em] tabular-nums">
                        {fmtScore(r.overall)}
                        <span className="ml-1 font-sans text-[11px] tracking-normal text-ink-2">/ 5</span>
                      </span>
                      <span className={cn("font-mono text-[11px] tabular-nums")} title="Change from the previous session">
                        <Delta d={r.delta} />
                      </span>
                      <span className="flex items-center gap-1 text-[12px] text-ink-2 group-hover:text-ink">
                        Open <ArrowRight className="size-3.5" strokeWidth={1.5} />
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </Panel>
          );
        })}
      </div>
    </div>
  );
}
