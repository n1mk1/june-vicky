"use client";

import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { PromptBar } from "@/components/app/PromptBar";
import { OrbScene } from "@/components/fx/scenes";
import { Panel } from "@/components/ui/Panel";
import { PillLink } from "@/components/ui/Pill";
import { EmptyState, ErrorNote, Loading } from "@/components/ui/States";
import { apiPost } from "@/lib/api";
import { fmtDate, humanize } from "@/lib/format";
import type { AttackItem, Dashboard, Engagement, ReportSummary, Truth, Widget } from "@/lib/types";
import { errorText, useAccessGuard, useApi } from "@/lib/use-api";
import { themeName } from "@/lib/echarts-theme";
import { useTheme } from "@/lib/use-theme";
import { cn } from "@/lib/utils";
import { WidgetView } from "./WidgetView";

const FIXED = ["margin_ring", "headline_kpi", "trend"] as const;

const SPAN: Record<number, string> = {
  1: "lg:col-span-1",
  2: "lg:col-span-2",
  3: "lg:col-span-3",
  4: "lg:col-span-4",
  5: "lg:col-span-5",
  6: "lg:col-span-6",
  7: "lg:col-span-7",
  8: "lg:col-span-8",
  9: "lg:col-span-9",
  10: "lg:col-span-10",
  11: "lg:col-span-11",
  12: "lg:col-span-12",
};

function AttackList({ items, loading, error }: { items: AttackItem[]; loading: boolean; error: unknown }) {
  const shown = [...items].sort((a, b) => b.severity - a.severity);
  return (
    <Panel title="What they'll ask first" aside={shown.length ? <span className="label">{shown.length}</span> : null} bodyClassName="scroll-thin overflow-y-auto">
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

function Readiness({ reports, company }: { reports: ReportSummary[] | undefined; company: string }) {
  const mine = (reports ?? []).filter((r) => r.company === company && r.overall !== null);
  const latest = [...mine].sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  const score = latest?.overall != null ? Math.round(latest.overall * 20) : null;
  return (
    <section
      aria-label="Pitch readiness"
      className="relative order-first flex min-h-[380px] items-center justify-center md:col-span-2 lg:order-none lg:col-span-5 lg:col-start-4 lg:row-span-2 lg:row-start-1 lg:min-h-0"
    >
      <div className="absolute inset-0">
        <OrbScene score={score ?? 0} />
      </div>
      <div className="relative flex flex-col items-center text-center">
        <span className="label">Pitch readiness</span>
        <span className="display mt-2 text-[clamp(72px,9vw,140px)] tabular-nums">{score ?? "—"}</span>
        <span className="mt-1 max-w-[26ch] text-[12px] text-ink-2">
          {latest ? (
            <>
              From your last session, {fmtDate(latest.created_at)}
              {latest.readiness ? ` · ${humanize(latest.readiness)}` : ""}.
            </>
          ) : (
            "No session yet. Face the panel in Preparation to get a score."
          )}
        </span>
        {!latest && <PillLink href="/preparation" label="Start a session" variant="outline" className="mt-3" />}
      </div>
    </section>
  );
}

function Slot({ widget, className, fallback, ...rest }: { widget?: Widget; className?: string; fallback: ReactNode; engagementId: string; currency?: string }) {
  return <div className={cn("flex min-w-0 [&>*]:min-w-0 [&>*]:flex-1", className)}>{widget ? <WidgetView widget={widget} {...rest} /> : fallback}</div>;
}

export function DashboardView() {
  const router = useRouter();
  const guard = useAccessGuard();
  const { theme } = useTheme();
  const dash = useApi<Dashboard>("dashboards/active", { theme: themeName(theme) });
  const ready = !!dash.data;
  const truth = useApi<Truth>(ready ? "truth" : null);
  const reports = useApi<ReportSummary[]>(ready ? "reports" : null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const ask = (text: string) => {
    try {
      sessionStorage.setItem("vicky-question", text);
    } catch {}
    router.push("/preparation");
  };

  const attach = async (file: File) => {
    setUploading(true);
    setUploadError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      if (dash.data) form.append("engagement_id", dash.data.engagement_id);
      const e = await apiPost<Engagement>("uploads", form);
      router.push(`/intake?e=${encodeURIComponent(e.id)}&step=2`);
    } catch (err) {
      setUploading(false);
      if (!guard(err)) setUploadError(errorText(err));
    }
  };

  if (dash.status === 404 || (dash.status === 409 && !dash.data)) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <EmptyState
          label="Dashboard"
          title="No source of truth yet."
          body="Upload your financials or try a sample. Once you confirm them, every figure here is computed from your data and carries its source."
        >
          <PillLink href="/intake" label="Load data" variant="solid" />
        </EmptyState>
      </div>
    );
  }
  if (!dash.data) {
    return dash.error ? (
      <div className="flex flex-1 items-center justify-center">
        <ErrorNote message={errorText(dash.error)} onRetry={dash.reload} />
      </div>
    ) : (
      <Loading label="Building your dashboard" className="p-2" />
    );
  }

  const d = dash.data;
  const byRole = new Map(d.widgets.map((w) => [w.role, w]));
  const pos = new Map(d.layout.map((l) => [l.widget_id, l]));
  const currency = truth.data?.profile?.currency;
  const rest = d.widgets
    .filter((w) => !(FIXED as readonly string[]).includes(w.role))
    .sort((a, b) => {
      const pa = pos.get(a.id);
      const pb = pos.get(b.id);
      return (pa?.y ?? 99) - (pb?.y ?? 99) || (pa?.x ?? 99) - (pb?.x ?? 99);
    });
  const common = { engagementId: d.engagement_id, currency };
  const empty = (title: string) => (
    <Panel title={title} bodyClassName="p-4">
      <p className="text-[12.5px] text-ink-2">Not available for this data.</p>
    </Panel>
  );

  return (
    <div className="scroll-thin -mx-1 flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-1 pb-2">
      <div className="grid shrink-0 grid-cols-1 gap-4 md:grid-cols-2 lg:h-full lg:min-h-[620px] lg:grid-cols-12 lg:grid-rows-[minmax(0,1fr)_minmax(0,1fr)_auto]">
        <Slot widget={byRole.get("margin_ring")} fallback={empty("Gross margin")} className="min-h-[300px] lg:col-span-3 lg:row-start-1 lg:min-h-0" {...common} />
        <Slot widget={byRole.get("headline_kpi")} fallback={empty("Headline")} className="lg:col-span-3 lg:row-start-2" {...common} />

        <Readiness reports={reports.data} company={d.company} />

        <Slot widget={byRole.get("trend")} fallback={empty("Trend")} className="min-h-[300px] lg:col-span-4 lg:col-start-9 lg:row-start-1 lg:min-h-0" {...common} />
        <div className="flex min-h-[260px] min-w-0 lg:col-span-4 lg:col-start-9 lg:row-start-2 lg:min-h-0 [&>*]:flex-1">
          <AttackList items={truth.data?.attack_list ?? []} loading={truth.loading} error={truth.error} />
        </div>

        <div className="md:col-span-2 lg:col-span-6 lg:col-start-4 lg:row-start-3">
          <PromptBar
            label="Ask about a number"
            placeholder="Ask about a number, e.g. why is burn falling?"
            onSubmit={ask}
            onAttach={attach}
            busy={uploading}
            hint={uploadError ? <span className="text-ember">{uploadError}</span> : undefined}
          />
        </div>
      </div>

      {rest.length > 0 && (
        <section aria-label="More widgets" className="flex flex-col gap-3 pt-2">
          <h2 className="label px-1">
            {d.company} · {rest.length} more
          </h2>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-12">
            {rest.map((w) => {
              const l = pos.get(w.id);
              const chart = w.status === "ok" && !["kpi", "gauge_ring"].includes(w.spec.template);
              return (
                <div
                  key={w.id}
                  className={cn("flex min-w-0 [&>*]:min-w-0 [&>*]:flex-1", SPAN[l?.w ?? (chart ? 6 : 3)], chart ? "min-h-[340px] md:col-span-2" : "min-h-[180px]")}
                >
                  <WidgetView widget={w} {...common} />
                </div>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}
