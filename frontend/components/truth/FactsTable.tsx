"use client";

import { Plus, X } from "lucide-react";
import { useState } from "react";
import { Field, inputCls, selectCls } from "@/components/ui/Field";
import { PillButton } from "@/components/ui/Pill";
import { ErrorNote } from "@/components/ui/States";
import { apiDelete, apiPost } from "@/lib/api";
import { fmtValue, humanize, sourceLabel } from "@/lib/format";
import type { Engagement, Fact, FigureKind } from "@/lib/types";
import { errorText, useAccessGuard } from "@/lib/use-api";
import { cn } from "@/lib/utils";

const KIND: Record<string, string> = {
  historical: "Historical",
  forecast: "Forecast",
  founder_claim: "Founder claim",
  benchmark: "Benchmark",
};

const SUGGESTED = [
  "cash_balance",
  "customers",
  "headcount",
  "nrr",
  "grr",
  "logo_churn_rate",
  "cac",
  "top_customer_share",
  "pipeline",
];

export function KindChip({ kind }: { kind: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center rounded-[3px] border px-2 font-mono text-[9.5px] uppercase tracking-[-0.04em] whitespace-nowrap",
        kind === "historical" ? "border-line-strong text-ink-2" : "border-dashed border-line-strong text-ink-2",
      )}
    >
      {KIND[kind] ?? humanize(kind)}
    </span>
  );
}

function SourceTag({ fact }: { fact: Fact }) {
  const s = fact.source;
  const unverified = s && (s.kind === "pdf" || s.kind === "docx") && s.cited_text && s.verified === false;
  return (
    <span className="flex flex-wrap items-center gap-1">
      <span
        title={s?.cited_text ?? undefined}
        className="inline-flex h-5 items-center rounded-[3px] border border-line px-2 font-mono text-[9.5px] uppercase tracking-[-0.04em] whitespace-nowrap text-ink-2"
      >
        {sourceLabel(s)}
      </span>
      {unverified && (
        <span className="inline-flex h-5 items-center rounded-[3px] border border-dashed border-ember px-2 font-mono text-[9.5px] uppercase tracking-[-0.04em] whitespace-nowrap text-ember">
          Couldn&apos;t verify on page
        </span>
      )}
    </span>
  );
}

function AddFact({ engagement, onSaved }: { engagement: Engagement; onSaved: (e: Engagement) => void }) {
  const guard = useAccessGuard();
  const currency = (engagement.profile?.currency ?? "usd").toLowerCase();
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ name: "", label: "", value: "", unit: currency, period: "", kind: "founder_claim" as FigureKind });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    const raw = Number(f.value.replace(/[,\s$£€%]/g, ""));
    if (!f.name.trim() || !f.value.trim() || Number.isNaN(raw)) {
      setError("Add a name and a number.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const value = f.unit === "pct" ? raw / 100 : raw;
      const body = {
        name: f.name.trim().toLowerCase().replace(/\s+/g, "_"),
        label: f.label.trim() || undefined,
        value,
        unit: f.unit,
        period: f.period.trim() || undefined,
        kind: f.kind,
      };
      onSaved(await apiPost<Engagement>(`engagements/${engagement.id}/facts`, body));
      setF((s) => ({ ...s, name: "", label: "", value: "", period: "" }));
      setOpen(false);
    } catch (err) {
      if (!guard(err)) setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <PillButton variant="outline" label="Add a figure" icon={<Plus className="size-3.5" strokeWidth={1.75} />} onClick={() => setOpen(true)} />
    );
  }

  return (
    <form
      className="flex flex-col gap-3 rounded-[4px] border border-line p-3.5"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <p className="text-[12px] text-ink-2">Figures you type are recorded as &ldquo;You said&rdquo;. The panel treats them as claims, not records.</p>
      <div className="grid gap-3 sm:grid-cols-6">
        <Field label="Name" htmlFor="fact-name" className="sm:col-span-2">
          <input id="fact-name" list="fact-names" className={inputCls} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="cash_balance" />
          <datalist id="fact-names">
            {SUGGESTED.map((n) => (
              <option key={n} value={n} />
            ))}
          </datalist>
        </Field>
        <Field label="Label (optional)" htmlFor="fact-label" className="sm:col-span-2">
          <input id="fact-label" className={inputCls} value={f.label} onChange={(e) => setF({ ...f, label: e.target.value })} placeholder="Cash in the bank" />
        </Field>
        <Field label="Kind" htmlFor="fact-kind" className="sm:col-span-2">
          <select id="fact-kind" className={selectCls} value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value as FigureKind })}>
            <option value="founder_claim">Founder claim</option>
            <option value="historical">Historical</option>
            <option value="forecast">Forecast</option>
          </select>
        </Field>
        <Field label={f.unit === "pct" ? "Value (%)" : "Value"} htmlFor="fact-value" className="sm:col-span-2">
          <input id="fact-value" inputMode="decimal" className={inputCls} value={f.value} onChange={(e) => setF({ ...f, value: e.target.value })} />
        </Field>
        <Field label="Unit" htmlFor="fact-unit" className="sm:col-span-2">
          <select id="fact-unit" className={selectCls} value={f.unit} onChange={(e) => setF({ ...f, unit: e.target.value })}>
            {[currency, "pct", "count", "months", "ratio", "x"].map((u) => (
              <option key={u} value={u}>
                {u.toUpperCase()}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Period" htmlFor="fact-period" className="sm:col-span-2">
          <input id="fact-period" className={inputCls} value={f.period} onChange={(e) => setF({ ...f, period: e.target.value })} placeholder="2026-09" />
        </Field>
      </div>
      {error && <ErrorNote message={error} />}
      <div className="flex justify-end gap-2">
        <PillButton variant="ghost" label="Cancel" onClick={() => setOpen(false)} />
        <PillButton type="submit" variant="solid" label={busy ? "Adding" : "Add figure"} disabled={busy} />
      </div>
    </form>
  );
}

/** Step 03: facts from documents, the sample pack and the founder. Remove inline; add a typed figure. */
export function FactsTable({ engagement, onChanged }: { engagement: Engagement; onChanged: (e: Engagement) => void }) {
  const guard = useAccessGuard();
  const [removing, setRemoving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const all = engagement.facts.filter((f) => f.status !== "removed");
  const currency = engagement.profile?.currency?.toLowerCase();
  const [kind, setKind] = useState<string>("all");
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(30);
  const kinds = ["all", ...Array.from(new Set(all.map((f) => f.kind)))];
  const q = query.trim().toLowerCase();
  const filtered = all.filter(
    (f) => (kind === "all" || f.kind === kind) && (!q || `${f.name} ${f.label ?? ""} ${f.period ?? ""}`.toLowerCase().includes(q)),
  );
  const facts = filtered.slice(0, limit);

  const remove = async (id: string) => {
    setRemoving(id);
    setError(null);
    try {
      onChanged(await apiDelete<Engagement>(`engagements/${engagement.id}/facts/${encodeURIComponent(id)}`));
    } catch (err) {
      if (!guard(err)) setError(errorText(err));
    } finally {
      setRemoving(null);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      {all.length > 8 && (
        <div className="flex flex-wrap items-center gap-2">
          <div role="tablist" aria-label="Kind" className="scroll-thin flex gap-1 overflow-x-auto">
            {kinds.map((k) => (
              <button
                key={k}
                role="tab"
                aria-selected={kind === k}
                onClick={() => {
                  setKind(k);
                  setLimit(30);
                }}
                className={cn(
                  "shrink-0 rounded-[3px] border px-2.5 py-0.5 text-[11.5px] transition-colors",
                  kind === k ? "border-invert-bg bg-invert-bg text-invert-ink" : "border-line text-ink-2 hover:text-ink",
                )}
              >
                {k === "all" ? `All · ${all.length}` : `${KIND[k] ?? humanize(k)} · ${all.filter((f) => f.kind === k).length}`}
              </button>
            ))}
          </div>
          <label htmlFor="fact-filter" className="sr-only">
            Filter facts
          </label>
          <input
            id="fact-filter"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter by name or period"
            className={cn(inputCls, "h-8 max-w-[240px] text-[12.5px]")}
          />
        </div>
      )}
      {all.length > 0 && facts.length === 0 ? (
        <p className="text-[12.5px] text-ink-2">No facts match that filter.</p>
      ) : facts.length === 0 ? (
        <p className="rounded-[4px] border border-dashed border-line-strong p-4 text-[12.5px] text-ink-2">
          No facts beyond your tables yet. Add figures your files don&apos;t contain, such as cash in the bank or customer count.
        </p>
      ) : (
        <div className="scroll-thin overflow-x-auto rounded-[4px] border border-line">
          <table className="w-full min-w-[640px] border-collapse text-left text-[12.5px]">
            <thead>
              <tr className="border-b border-line">
                <th className="label px-3 py-2 font-normal">Fact</th>
                <th className="label px-3 py-2 text-right font-normal">Value</th>
                <th className="label px-3 py-2 font-normal">Period</th>
                <th className="label px-3 py-2 font-normal">Kind</th>
                <th className="label px-3 py-2 font-normal">Source</th>
                <th className="px-2 py-2">
                  <span className="sr-only">Remove</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {facts.map((f) => (
                <tr key={f.id} className={cn("align-top", removing === f.id && "opacity-40")}>
                  <td className="px-3 py-2.5">
                    <span className="block text-ink">{f.label || humanize(f.name)}</span>
                    <span className="font-mono text-[10px] text-dim">{f.name}</span>
                    {f.note && <span className="mt-0.5 block text-[11px] text-ink-2">{f.note}</span>}
                  </td>
                  <td className="px-3 py-2.5 text-right font-display text-[15px] tracking-[-0.03em] tabular-nums whitespace-nowrap">
                    {fmtValue(f.value, f.unit, currency)}
                  </td>
                  <td className="px-3 py-2.5 font-mono text-[11px] text-ink-2 whitespace-nowrap">{f.period ?? "–"}</td>
                  <td className="px-3 py-2.5">
                    <KindChip kind={f.kind} />
                  </td>
                  <td className="px-3 py-2.5">
                    <SourceTag fact={f} />
                  </td>
                  <td className="px-2 py-2">
                    <button
                      type="button"
                      onClick={() => void remove(f.id)}
                      disabled={!!removing}
                      aria-label={`Remove ${f.label || f.name}`}
                      className="flex size-7 items-center justify-center rounded-full text-ink-2 transition-colors hover:bg-surface-solid hover:text-ember disabled:opacity-40"
                    >
                      <X className="size-3.5" strokeWidth={1.75} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {filtered.length > facts.length && (
        <button type="button" onClick={() => setLimit((n) => n + 60)} className="self-start text-[12px] text-ink underline underline-offset-2">
          Show {Math.min(60, filtered.length - facts.length)} more of {filtered.length - facts.length}
        </button>
      )}
      {error && <ErrorNote message={error} />}
      <div>
        <AddFact engagement={engagement} onSaved={onChanged} />
      </div>
    </div>
  );
}
