"use client";

import { Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { OrbScene } from "@/components/fx/scenes";
import { Panel } from "@/components/ui/Panel";
import { PillButton, PillLink } from "@/components/ui/Pill";
import { EmptyState, ErrorNote, Loading } from "@/components/ui/States";
import { ApiError, apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { pack } from "@/lib/dashboard-layout";
import { fmtDate, humanize } from "@/lib/format";
import { useChannel, useSocketStatus, type Envelope } from "@/lib/socket";
import type { AttackItem, ChatResult, Dashboard, Engagement, ReportSummary, TimeRange, Truth, Widget } from "@/lib/types";
import { errorText, useAccessGuard, useApi } from "@/lib/use-api";
import { themeName } from "@/lib/echarts-theme";
import { useTheme } from "@/lib/use-theme";
import { cn } from "@/lib/utils";
import { AddWidget } from "./AddWidget";
import { DashboardChat } from "./DashboardChat";
import { DashboardGrid, type Sized } from "./DashboardGrid";
import { WidgetView } from "./WidgetView";

const FIXED = ["margin_ring", "headline_kpi", "trend"] as const;
const isFixed = (role: string) => (FIXED as readonly string[]).includes(role);
/** First grid row of the editable flow when nothing is placed yet (below the hero and prompt bar). */
const FLOW_TOP = 10;

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/** Keep unchanged widgets (and the time range) as the same objects so their charts don't redraw. */
function reconcile(prev: Dashboard | undefined, next: Dashboard): Dashboard {
  if (!prev || prev.id !== next.id) return next;
  const old = new Map(prev.widgets.map((w) => [w.id, w]));
  return {
    ...next,
    time_range: same(prev.time_range, next.time_range) ? prev.time_range : next.time_range,
    widgets: next.widgets.map((w) => {
      const o = old.get(w.id);
      return o && same(o, w) ? o : w;
    }),
  };
}

function LiveDot() {
  const status = useSocketStatus();
  const live = status === "open";
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] text-dim" role="status" title="Changes from other tabs appear here live">
      <span
        className={cn("size-1.5 rounded-full", live ? "bg-ember animate-[pulse-dot_2.4s_ease-in-out_infinite]" : "border border-dim")}
        aria-hidden
      />
      {live ? "Live" : status === "reconnecting" ? "Reconnecting…" : "Connecting…"}
    </span>
  );
}

function RangeChip({ range, onReset }: { range: TimeRange; onReset: () => void }) {
  return (
    <span className="inline-flex h-7 items-center gap-2 rounded-full border border-line px-3 text-[11.5px] text-ink-2">
      <span className="text-ink">{range.label}</span>
      <button type="button" onClick={onReset} className="text-ink underline underline-offset-2 hover:text-ember">
        Reset
      </button>
    </span>
  );
}

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

function Slot({
  widget,
  className,
  fallback,
  ...rest
}: {
  widget?: Widget;
  className?: string;
  fallback: ReactNode;
  engagementId: string;
  currency?: string;
  timeRange: TimeRange | null;
  onRangeChange?: (range: { from: string; to: string } | null) => void;
}) {
  return <div className={cn("flex min-w-0 [&>*]:min-w-0 [&>*]:flex-1", className)}>{widget ? <WidgetView widget={widget} {...rest} /> : fallback}</div>;
}

export function DashboardView() {
  const router = useRouter();
  const guard = useAccessGuard();
  const { theme } = useTheme();
  const tname = themeName(theme);
  const dash = useApi<Dashboard>("dashboards/active", { theme: tname });
  const ready = !!dash.data;
  const truth = useApi<Truth>(ready ? "truth" : null);
  const reports = useApi<ReportSummary[]>(ready ? "reports" : null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [highlight, setHighlight] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  // ---- live state: REST is the record, the socket says when to re-read it
  const { mutate } = dash;
  const did = dash.data?.id ?? null;
  const version = useRef(0);
  const inFlight = useRef(0);
  const stale = useRef(0); // highest event version seen while a request of ours was in flight
  useEffect(() => {
    if (dash.data) version.current = Math.max(version.current, dash.data.version);
  }, [dash.data]);

  /** Apply a dashboard from the API unless something newer is already shown. */
  const apply = useCallback(
    (next: Dashboard) => {
      if (next.version < version.current) return;
      version.current = next.version;
      mutate((prev) => reconcile(prev, next));
    },
    [mutate],
  );

  const flash = useCallback((id: string | null, text?: string) => {
    setHighlight(id);
    if (text) setNote(text);
    window.setTimeout(() => {
      setHighlight((h) => (h === id ? null : h));
      if (text) setNote((n) => (n === text ? null : n));
    }, 4000);
  }, []);

  const refetch = useCallback(async () => {
    if (!did) return null;
    try {
      const next = await apiGet<Dashboard>(`dashboards/${encodeURIComponent(did)}`, { theme: tname });
      apply(next);
      return next;
    } catch (err) {
      guard(err);
      return null;
    }
  }, [did, tname, apply, guard]);

  /**
   * Track a request from this tab. The server publishes before it responds, so our own change can
   * arrive as an event first: events seen meanwhile wait, and are re-read only if the server moved
   * past what the response gave us (another tab wrote at the same time).
   */
  const track = useCallback(
    async <T,>(p: Promise<T>): Promise<T> => {
      inFlight.current += 1;
      try {
        return await p;
      } finally {
        inFlight.current -= 1;
        if (!inFlight.current && stale.current > version.current) void refetch();
        if (!inFlight.current) stale.current = 0;
      }
    },
    [refetch],
  );

  /** Run a dashboard write and apply its result; a 409 re-reads the dashboard. */
  const write = useCallback(
    async (fn: () => Promise<Dashboard>): Promise<Dashboard | null> => {
      try {
        const next = await track(fn().then((d) => (apply(d), d)));
        return next;
      } catch (err) {
        if (guard(err)) return null;
        if (err instanceof ApiError && err.status === 409) {
          setNote("The dashboard changed in another tab, so it was reloaded. Try that again.");
          await refetch();
        } else setNote(errorText(err));
        return null;
      }
    },
    [apply, guard, refetch, track],
  );

  const onEvent = useCallback(
    async (e: Envelope) => {
      const v = (e.payload as { version?: unknown }).version;
      if (typeof v === "number" && v <= version.current) return; // our own change, or already applied
      if (inFlight.current) {
        stale.current = Math.max(stale.current, typeof v === "number" ? v : Number.MAX_SAFE_INTEGER);
        return;
      }
      const before = new Set((dash.data?.widgets ?? []).map((w) => w.id));
      const next = await refetch();
      const p = e.payload as { op?: string; title?: string; by?: string };
      if (next && e.type === "widget.diff" && p.op === "add") {
        const added = next.widgets.find((w) => !before.has(w.id));
        flash(added?.id ?? null, p.title ? `${p.by === "vicky" ? "Vicky added" : "Added"} “${p.title}” in another tab.` : undefined);
      }
    },
    [dash.data, refetch, flash],
  );
  useChannel(did ? `dashboard:${did}` : null, (e) => void onEvent(e), () => void refetch());

  // ---- actions
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

  const remove = async (wid: string): Promise<boolean> => {
    if (!dash.data) return false;
    const id = dash.data.id;
    // optimistic: drop it now, the response (or a re-read on failure) is the record
    mutate((prev) => (prev ? { ...prev, widgets: prev.widgets.filter((w) => w.id !== wid), layout: prev.layout.filter((l) => l.widget_id !== wid) } : prev!));
    const next = await write(() => apiDelete<Dashboard>(`dashboards/${encodeURIComponent(id)}/widgets/${encodeURIComponent(wid)}`));
    if (!next) await refetch();
    return !!next;
  };

  const commitLayout = (items: Sized[]) => {
    const d = dash.data;
    if (!d) return;
    const flowIds = new Set(items.map((i) => i.widget_id));
    const fixed = d.layout.filter((l) => !flowIds.has(l.widget_id));
    const flowYs = d.layout.filter((l) => flowIds.has(l.widget_id)).map((l) => l.y);
    const top = flowYs.length ? Math.min(...flowYs) : FLOW_TOP;
    const layout = [...fixed, ...pack(items, top)];
    mutate((prev) => (prev ? { ...prev, layout } : prev!));
    void write(() => apiPatch<Dashboard>(`dashboards/${encodeURIComponent(d.id)}/layout`, { layout, version: d.version }));
  };

  const setRange = (time_range: { last_months: number } | { from: string; to: string } | null) => {
    if (!dash.data) return;
    const id = dash.data.id;
    void write(() => apiPatch<Dashboard>(`dashboards/${encodeURIComponent(id)}/time-range`, { time_range }));
  };

  // Zooming any chart sets the dashboard-wide range (UI doc: linked interaction). Slider drags and
  // pinches fire many events, so only the last one in a short pause is saved.
  const zoomTimer = useRef<number | null>(null);
  const zoomTo = (range: { from: string; to: string } | null) => {
    if (zoomTimer.current !== null) window.clearTimeout(zoomTimer.current);
    zoomTimer.current = window.setTimeout(() => {
      zoomTimer.current = null;
      const cur = dash.data?.time_range ?? null;
      if (!range ? !cur : cur && cur.from === range.from && cur.to === range.to) return;
      setRange(range);
    }, 450);
  };

  const onChat = (r: ChatResult) => {
    if (r.dashboard) apply(r.dashboard);
    if (r.widget_id && (r.kind === "widget_added" || r.kind === "exists")) flash(r.widget_id);
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
  const currency = truth.data?.profile?.currency;
  const rest = d.widgets.filter((w) => !isFixed(w.role));
  const common = { engagementId: d.engagement_id, currency, timeRange: d.time_range, onRangeChange: zoomTo };
  const empty = (title: string) => (
    <Panel title={title} bodyClassName="p-4">
      <p className="text-[12.5px] text-ink-2">Not available for this data.</p>
    </Panel>
  );

  return (
    <div className="scroll-thin -mx-1 flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-1 pb-2">
      <div className="flex min-h-7 shrink-0 flex-wrap items-center justify-between gap-x-4 gap-y-1 px-1">
        <div className="flex min-w-0 items-center gap-3">
          <LiveDot />
          {note && (
            <span role="status" className="truncate text-[11.5px] text-ink-2">
              {note}
            </span>
          )}
        </div>
        {d.time_range && <RangeChip range={d.time_range} onReset={() => setRange(null)} />}
      </div>

      <div className="grid shrink-0 grid-cols-1 gap-4 md:grid-cols-2 lg:h-full lg:min-h-[720px] lg:grid-cols-12 lg:grid-rows-[minmax(0,0.9fr)_minmax(0,1.1fr)_auto]">
        <Slot widget={byRole.get("margin_ring")} fallback={empty("Gross margin")} className="min-h-[300px] lg:col-span-3 lg:row-start-1 lg:min-h-0" {...common} />
        <Slot widget={byRole.get("headline_kpi")} fallback={empty("Headline")} className="lg:col-span-3 lg:row-start-2" {...common} />

        <Readiness reports={reports.data} company={d.company} />

        <Slot widget={byRole.get("trend")} fallback={empty("Trend")} className="min-h-[300px] lg:col-span-4 lg:col-start-9 lg:row-start-1 lg:min-h-0" {...common} />
        <div className="flex min-h-[260px] min-w-0 lg:col-span-4 lg:col-start-9 lg:row-start-2 lg:min-h-0 [&>*]:flex-1">
          <AttackList items={truth.data?.attack_list ?? []} loading={truth.loading} error={truth.error} />
        </div>

        <div className="md:col-span-2 lg:col-span-6 lg:col-start-4 lg:row-start-3">
          <DashboardChat
            dashboardId={d.id}
            track={track}
            engagementId={d.engagement_id}
            onResult={onChat}
            onAsk={ask}
            onUndo={remove}
            onShow={(id) => flash(id)}
            onResetRange={() => setRange(null)}
            onAttach={attach}
            attachBusy={uploading}
            attachError={uploadError}
          />
        </div>
      </div>

      <section aria-label="More widgets" className="flex flex-col gap-3 pt-2">
        <div className="flex items-center justify-between gap-3 px-1">
          <h2 className="label">
            {d.company} · {rest.length} more
          </h2>
          {!adding && <PillButton label="Add widget" icon={<Plus className="size-3.5" strokeWidth={1.75} />} onClick={() => setAdding(true)} />}
        </div>
        {adding && (
          <AddWidget
            dashboardId={d.id}
            track={track}
            version={d.version}
            engagementId={d.engagement_id}
            currency={currency}
            onAdded={(next, title) => {
              const before = new Set(d.widgets.map((w) => w.id));
              apply(next);
              setAdding(false);
              flash(next.widgets.find((w) => !before.has(w.id))?.id ?? null, `Added “${title}”.`);
            }}
            onConflict={async () => (await refetch())?.version ?? null}
            onClose={() => setAdding(false)}
          />
        )}
        {rest.length > 0 ? (
          <DashboardGrid widgets={rest} layout={d.layout} highlight={highlight} onCommit={commitLayout} onRemove={(id) => void remove(id)} {...common} />
        ) : (
          !adding && <p className="px-1 text-[12.5px] text-ink-2">Ask Vicky for a chart above, or add one here.</p>
        )}
      </section>
    </div>
  );
}
