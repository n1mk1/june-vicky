"use client";

import { useEffect, useMemo, useState } from "react";
import { Panel } from "@/components/ui/Panel";
import { PillButton } from "@/components/ui/Pill";
import { Segmented } from "@/components/ui/Segmented";
import { ApiError, apiPost } from "@/lib/api";
import type { Dashboard, Widget, WidgetPreview, WidgetSpec } from "@/lib/types";
import { errorText, useAccessGuard } from "@/lib/use-api";
import { WidgetView } from "./WidgetView";

// Generic metric vocabulary (DSL names and metric ids, docs/02-TRD.md §6). Values come from the backend.
const SERIES: { ref: string; label: string }[] = [
  { ref: "revenue", label: "Revenue" },
  { ref: "mrr", label: "MRR" },
  { ref: "arr", label: "ARR" },
  { ref: "revenue.recurring", label: "Recurring revenue" },
  { ref: "burn", label: "Burn" },
  { ref: "burn_ex_non_dilutive", label: "Burn ex-credits" },
  { ref: "gross_margin", label: "Gross margin" },
  { ref: "cogs", label: "Cost of revenue" },
  { ref: "opex.total", label: "Operating expenses" },
  { ref: "opex.r_and_d", label: "R&D" },
  { ref: "opex.s_and_m", label: "Sales & marketing" },
  { ref: "opex.g_and_a", label: "G&A" },
  { ref: "net_income", label: "Net income" },
  { ref: "cash_balance", label: "Cash balance" },
  { ref: "customers.count", label: "Customers" },
  { ref: "headcount.total", label: "Headcount" },
];
const FIGURES: { ref: string; label: string }[] = [
  { ref: "runway_months", label: "Runway" },
  { ref: "nrr", label: "Net revenue retention" },
  { ref: "burn_multiple", label: "Burn multiple" },
  { ref: "cac_payback_months", label: "CAC payback" },
  { ref: "top_customer_share", label: "Top customer share" },
];
const SCALAR = new Set(FIGURES.map((f) => f.ref));
const CUSTOM = "__custom";

type Group = "native" | "month" | "quarter" | "year";
type Chart = "line" | "area" | "bar" | "table";

const select =
  "h-8 min-w-0 rounded-[3px] border border-line bg-surface-solid/60 px-2 text-[12.5px] text-ink focus:border-line-strong focus:outline-none";

interface AddWidgetProps {
  dashboardId: string;
  version: number;
  engagementId: string;
  currency?: string;
  /** "?currency=usd" when the dashboard shows another currency than the reporting one, else "". */
  query?: string;
  /** Marks a request from this tab so its own realtime event isn't mistaken for another tab's. */
  track: <T>(p: Promise<T>) => Promise<T>;
  /** Called with the new dashboard after a successful add. */
  onAdded: (d: Dashboard, title: string) => void;
  /** Re-reads the dashboard after a 409 and returns its version (null if that failed). */
  onConflict: () => Promise<number | null>;
  onClose: () => void;
}

/** Build a widget from the metric vocabulary, preview it (evaluated by the backend), then add it. */
export function AddWidget({ dashboardId, version, engagementId, currency, query = "", track, onAdded, onConflict, onClose }: AddWidgetProps) {
  const guard = useAccessGuard();
  const [ref, setRef] = useState("revenue");
  const [custom, setCustom] = useState("");
  const [per, setPer] = useState("");
  const [group, setGroup] = useState<Group>("native");
  const [chart, setChart] = useState<Chart>("line");
  const [title, setTitle] = useState("");
  const [preview, setPreview] = useState<{ key: string; data: WidgetPreview | null; error: string | null } | null>(null);
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  const spec: WidgetSpec | null = useMemo(() => {
    const base = ref === CUSTOM ? custom.trim() : ref;
    if (!base) return null;
    const label = ref === CUSTOM ? base : [...SERIES, ...FIGURES].find((s) => s.ref === ref)?.label ?? base;
    if (SCALAR.has(ref)) return { template: "kpi", title: title.trim() || label, series: [{ ref: base, label }] };
    const den = per ? SERIES.find((s) => s.ref === per) : undefined;
    const sref = den ? `pct_of(${base}, ${den.ref})` : base;
    const slabel = den ? `${label} as % of ${den.label.toLowerCase()}` : label;
    const auto = group === "native" ? slabel : `${slabel} by ${group}`;
    return {
      template: chart,
      title: (title.trim() || auto).slice(0, 120),
      series: [{ ref: sref, label: slabel.slice(0, 80) }],
      ...(group === "native" ? {} : { group_by: group }),
    };
  }, [ref, custom, per, group, chart, title]);
  const key = JSON.stringify(spec);

  // Preview: the backend evaluates the spec; nothing here computes a value.
  useEffect(() => {
    if (!spec) return;
    let live = true;
    const t = window.setTimeout(() => {
      apiPost<WidgetPreview>(`dashboards/${encodeURIComponent(dashboardId)}/widgets/preview${query}`, { spec: spec as unknown as Record<string, unknown> }).then(
        (data) => live && setPreview({ key, data, error: null }),
        (err: unknown) => {
          if (!live || guard(err)) return;
          setPreview({ key, data: null, error: errorText(err) });
        },
      );
    }, 300);
    return () => {
      live = false;
      window.clearTimeout(t);
    };
    // `key` is the spec.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, dashboardId, guard, query]);

  const current = preview?.key === key ? preview : null;
  const widget: Widget | null =
    spec && current?.data
      ? { id: "preview", role: "custom", spec, status: current.data.evaluated.status, evaluated: current.data.evaluated, option: current.data.option, created_by: "founder" }
      : null;

  const add = async () => {
    if (!spec || widget?.status !== "ok") return;
    setAdding(true);
    setAddError(null);
    const body = (v: number) => ({ spec: spec as unknown as Record<string, unknown>, version: v });
    const post = (v: number) =>
      apiPost<Dashboard>(`dashboards/${encodeURIComponent(dashboardId)}/widgets${query}`, body(v)).then((d) => {
        onAdded(d, spec.title);
        return d;
      });
    try {
      try {
        await track(post(version));
      } catch (err) {
        if (!(err instanceof ApiError && err.status === 409)) throw err;
        const fresh = await onConflict(); // someone else changed the dashboard: retry once on the new version
        if (fresh === null) throw err;
        await track(post(fresh));
      }
    } catch (err) {
      if (!guard(err)) setAddError(errorText(err));
    } finally {
      setAdding(false);
    }
  };

  const scalar = SCALAR.has(ref);
  return (
    <Panel
      title="Add a widget"
      aside={<PillButton label="Close" variant="ghost" onClick={onClose} />}
      bodyClassName="grid gap-4 p-4 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]"
    >
      <form
        className="flex flex-col gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          void add();
        }}
      >
        <label className="flex flex-col gap-1">
          <span className="label">Metric</span>
          <select className={select} value={ref} onChange={(e) => setRef(e.target.value)}>
            <optgroup label="Over time">
              {SERIES.map((s) => (
                <option key={s.ref} value={s.ref}>
                  {s.label}
                </option>
              ))}
            </optgroup>
            <optgroup label="Single figure">
              {FIGURES.map((s) => (
                <option key={s.ref} value={s.ref}>
                  {s.label}
                </option>
              ))}
            </optgroup>
            <option value={CUSTOM}>Formula…</option>
          </select>
        </label>
        {ref === CUSTOM && (
          <label className="flex flex-col gap-1">
            <span className="label">Formula</span>
            <input
              className={`${select} font-mono`}
              value={custom}
              onChange={(e) => setCustom(e.target.value)}
              placeholder="e.g. rolling(revenue, 3) or opex.s_and_m / revenue"
              autoComplete="off"
            />
          </label>
        )}
        {!scalar && (
          <>
            <label className="flex flex-col gap-1">
              <span className="label">As a share of</span>
              <select className={select} value={per} onChange={(e) => setPer(e.target.value)}>
                <option value="">Nothing (show the value)</option>
                {SERIES.filter((s) => s.ref !== ref).map((s) => (
                  <option key={s.ref} value={s.ref}>
                    % of {s.label.toLowerCase()}
                  </option>
                ))}
              </select>
            </label>
            <div className="flex flex-col gap-1">
              <span className="label">Group by</span>
              <Segmented<Group>
                label="Group by"
                value={group}
                onChange={setGroup}
                options={[
                  { value: "native", label: "As uploaded" },
                  { value: "month", label: "Month" },
                  { value: "quarter", label: "Quarter" },
                  { value: "year", label: "Year" },
                ]}
              />
            </div>
            <div className="flex flex-col gap-1">
              <span className="label">Chart</span>
              <Segmented<Chart>
                label="Chart type"
                value={chart}
                onChange={setChart}
                options={[
                  { value: "line", label: "Line" },
                  { value: "area", label: "Area" },
                  { value: "bar", label: "Bars" },
                  { value: "table", label: "Table" },
                ]}
              />
            </div>
          </>
        )}
        <label className="flex flex-col gap-1">
          <span className="label">Title</span>
          <input className={select} value={title} onChange={(e) => setTitle(e.target.value)} placeholder={spec?.title} maxLength={120} />
        </label>
        <div className="flex items-center gap-3 pt-1">
          <PillButton type="submit" label={adding ? "Adding" : "Add to dashboard"} variant="solid" disabled={adding || widget?.status !== "ok"} />
          {addError && <span className="text-[12px] text-ember">{addError}</span>}
        </div>
      </form>
      <div className="flex min-h-[300px] min-w-0 [&>*]:min-w-0 [&>*]:flex-1" aria-live="polite">
        {widget ? (
          <WidgetView widget={widget} engagementId={engagementId} currency={currency} />
        ) : (
          <p className="self-center text-[12.5px] text-ink-2">{current?.error ?? "Previewing…"}</p>
        )}
      </div>
    </Panel>
  );
}
