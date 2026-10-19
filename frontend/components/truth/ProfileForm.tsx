"use client";

import { useState } from "react";
import { Field, inputCls, selectCls } from "@/components/ui/Field";
import { PillButton } from "@/components/ui/Pill";
import { Segmented } from "@/components/ui/Segmented";
import { ErrorNote } from "@/components/ui/States";
import { apiPut } from "@/lib/api";
import { CURRENCIES, CURRENCY_CODES, DEFAULT_CURRENCY, normCurrency } from "@/lib/currency";
import type { Engagement, Profile, Stage } from "@/lib/types";
import { errorText, useAccessGuard } from "@/lib/use-api";

const COUNTRIES = [
  ["CA", "Canada"],
  ["US", "United States"],
  ["GB", "United Kingdom"],
  ["IE", "Ireland"],
  ["AU", "Australia"],
  ["DE", "Germany"],
  ["FR", "France"],
  ["NL", "Netherlands"],
  ["OTHER", "Other"],
] as const;

const STAGES: { value: Stage; label: string }[] = [
  { value: "pre_seed", label: "Pre-seed" },
  { value: "seed", label: "Seed" },
  { value: "series_a", label: "Series A" },
  { value: "series_b_plus", label: "Series B+" },
  { value: "other", label: "Other" },
];
const ROUND_TYPES = [
  ["priced_equity", "Priced equity"],
  ["safe", "SAFE"],
  ["convertible_note", "Convertible note"],
  ["none", "Not raising"],
  ["other", "Other"],
] as const;
const MONTHS = Array.from({ length: 12 }, (_, i) => new Intl.DateTimeFormat("en", { month: "long", timeZone: "UTC" }).format(Date.UTC(2000, i, 1)));

const EMPTY: Profile = {
  name: "",
  country: "US",
  currency: DEFAULT_CURRENCY,
  fiscal_year_start_month: 1,
  stage: "seed",
  round_type: "priced_equity",
  round_size: null,
  business_model: "recurring",
  granularity: "month",
  one_liner: "",
};

/** Step 01: the company profile. Values prefilled from a sample or inferred from a file are editable. */
export function ProfileForm({ engagement, onSaved }: { engagement: Engagement; onSaved: (e: Engagement) => void }) {
  const guard = useAccessGuard();
  const sources = engagement.profile_sources ?? {};
  const prefilled = !!engagement.profile?.name || Object.keys(sources).length > 0;
  /** "From financials/P&L.csv: “…”" under a field the knowledge base filled in. */
  const from = (k: string) => (sources[k] ? <SourceHint text={sources[k]} /> : undefined);
  const [p, setP] = useState<Profile>(() => {
    const merged = { ...EMPTY, ...(engagement.profile ?? {}) };
    return { ...merged, currency: normCurrency(merged.currency) };
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = <K extends keyof Profile>(k: K, v: Profile[K]) => setP((s) => ({ ...s, [k]: v }));
  const countries = COUNTRIES.some(([c]) => c === p.country) ? COUNTRIES : [[p.country, p.country] as const, ...COUNTRIES];

  const save = async () => {
    if (!p.name.trim()) {
      setError("Add the company name.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      onSaved(await apiPut<Engagement>(`engagements/${engagement.id}/profile`, { ...p, name: p.name.trim() }));
    } catch (err) {
      if (!guard(err)) setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      className="flex flex-col gap-5"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      {prefilled && (
        <p className="flex items-center gap-2 text-[12px] text-ink-2">
          <span className="rounded-[3px] border border-dashed border-line-strong px-2 py-0.5 font-mono text-[9.5px] uppercase tracking-[-0.04em]">
            Prefilled
          </span>
          Vik filled these in from your {Object.keys(sources).length > 0 ? "knowledge base" : "files"}. Check them before you
          continue.
        </p>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Company name" htmlFor="pf-name" className="sm:col-span-2" hint={from("name")}>
          <input id="pf-name" className={inputCls} value={p.name} onChange={(e) => set("name", e.target.value)} required />
        </Field>
        <Field label="Country" htmlFor="pf-country" hint={from("country")}>
          <select id="pf-country" className={selectCls} value={p.country} onChange={(e) => set("country", e.target.value)}>
            {countries.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </Field>
        <Field
          label="Reporting currency"
          htmlFor="pf-currency"
          hint={from("currency") ?? "Every figure is shown in it. Tables in another currency convert at Bank of Canada rates."}
        >
          <select id="pf-currency" className={selectCls} value={p.currency} onChange={(e) => set("currency", e.target.value)}>
            {CURRENCY_CODES.map((c) => (
              <option key={c} value={c}>
                {c.toUpperCase()} · {CURRENCIES[c][0]}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Fiscal year starts" htmlFor="pf-fy" hint={from("fiscal_year_start_month")}>
          <select
            id="pf-fy"
            className={selectCls}
            value={p.fiscal_year_start_month}
            onChange={(e) => set("fiscal_year_start_month", Number(e.target.value))}
          >
            {MONTHS.map((m, i) => (
              <option key={m} value={i + 1}>
                {m}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Stage" htmlFor="pf-stage" hint={from("stage")}>
          <select id="pf-stage" className={selectCls} value={p.stage} onChange={(e) => set("stage", e.target.value as Stage)}>
            {STAGES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Round type" htmlFor="pf-round" hint={from("round_type")}>
          <select id="pf-round" className={selectCls} value={p.round_type ?? "other"} onChange={(e) => set("round_type", e.target.value)}>
            {ROUND_TYPES.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </Field>
        <Field label={`Round size (${p.currency.toUpperCase()})`} htmlFor="pf-size" hint={from("round_size") ?? "Leave empty if you aren't raising."}>
          <input
            id="pf-size"
            className={inputCls}
            inputMode="numeric"
            value={p.round_size ?? ""}
            onChange={(e) => {
              const n = e.target.value.replace(/[^\d]/g, "");
              set("round_size", n ? Number(n) : null);
            }}
          />
        </Field>
        <Field label="Business model" hint={from("business_model")}>
          <Segmented
            label="Business model"
            value={p.business_model}
            onChange={(v) => set("business_model", v)}
            options={[
              { value: "recurring", label: "Recurring" },
              { value: "other", label: "Other" },
            ]}
            className="self-start"
          />
        </Field>
        <Field label="Your data is" hint={from("granularity")}>
          <Segmented
            label="Granularity"
            value={p.granularity}
            onChange={(v) => set("granularity", v)}
            options={[
              { value: "month", label: "Monthly" },
              { value: "quarter", label: "Quarterly" },
            ]}
            className="self-start"
          />
        </Field>
        <Field label="One line on what you do" htmlFor="pf-one" className="sm:col-span-2" hint={from("one_liner")}>
          <textarea
            id="pf-one"
            rows={2}
            className={`${inputCls} h-auto resize-none py-2`}
            value={p.one_liner ?? ""}
            onChange={(e) => set("one_liner", e.target.value)}
          />
        </Field>
      </div>
      {error && <ErrorNote message={error} />}
      <div className="flex justify-end">
        <PillButton type="submit" variant="solid" label={busy ? "Saving" : "Save and continue"} disabled={busy} />
      </div>
    </form>
  );
}

/** The note a value came from, without the wikilink brackets. */
function SourceHint({ text }: { text: string }) {
  const clean = text.replace(/\[\[([^\]|]+)(?:\|[^\]]*)?\]\]/g, "$1");
  return (
    <span className="line-clamp-2" title={clean}>
      {clean}
    </span>
  );
}
