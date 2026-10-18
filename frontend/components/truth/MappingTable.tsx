"use client";

import { Check } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { selectCls } from "@/components/ui/Field";
import { ErrorNote, Loading } from "@/components/ui/States";
import { apiPut } from "@/lib/api";
import { CURRENCY_CODES, isCurrency } from "@/lib/currency";
import { humanize } from "@/lib/format";
import type { ColumnMapping, DatasetColumn, DatasetSummary, MappingResponse, MappingTarget } from "@/lib/types";
import { errorText, useAccessGuard, useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";

const LOW = 0.6;
const RAW = "__raw__";
const NEW_CUSTOM = "__new_custom__";
const CUSTOM = "custom.";

/** The id the API gives a custom field named `label` ("Active pilots" → custom.active_pilots). */
function customId(label: string): string {
  const slug = label
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 48);
  return slug ? CUSTOM + slug : "";
}
const FIGURE_UNITS = ["count", "pct", "months", "ratio", "x"];
const UNIT_LABEL: Record<string, string> = {
  "": "—",
  pct: "%",
  count: "Count",
  months: "Months",
  ratio: "Ratio",
  x: "Multiple (×)",
  date: "Date",
  text: "Text",
};
const SCALE_WORD: Record<number, string> = { 1000: "thousands", 1000000: "millions", 1000000000: "billions" };

/** Saves one table's mapping; resolves false when it failed (the table shows why). */
export type MappingSaver = () => Promise<boolean>;

type Kind = MappingTarget["kind"];

function unitLabel(u: string): string {
  return UNIT_LABEL[u] ?? u.toUpperCase();
}

/** The unit a column takes once it maps to a field of this kind; a raw column says what its values are. */
function unitFor(kind: Kind | undefined, col: DatasetColumn | undefined, currency: string): string {
  if (kind === "custom") kind = undefined; // a custom field takes the unit its values are in
  if (kind === "money") return (col?.currency || currency).toLowerCase();
  if (kind === "count") return "count";
  if (kind === "date" || kind === "text") return kind;
  if (col?.unit_hint) return col.unit_hint;
  if (col?.dtype === "period") return "date";
  if (col?.dtype === "text") return "text";
  return (col?.currency ?? "").toLowerCase();
}

function unitOptions(kind: Kind | undefined, current: string, currency: string): string[] {
  if (kind === "custom") kind = undefined;
  const list =
    kind === "date" || kind === "text"
      ? [kind]
      : kind === "money"
        ? [currency, ...CURRENCY_CODES]
        : kind === "count"
          ? FIGURE_UNITS
          : ["", currency, ...FIGURE_UNITS, "date", "text", ...CURRENCY_CODES];
  return [...(list.includes(current) ? [] : [current]), ...list].filter((u, i, a) => a.indexOf(u) === i);
}

function Confidence({ value }: { value: number }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <span className="flex items-center gap-2" role="img" aria-label={`Confidence ${pct} of 100`}>
      <span className="relative h-[3px] w-14 overflow-hidden rounded-full bg-line">
        <span className={cn("absolute inset-y-0 left-0 rounded-full", value < LOW ? "bg-ember" : "bg-ink")} style={{ width: `${pct}%` }} />
      </span>
      <span className="w-7 font-mono text-[10px] tabular-nums text-ink-2">{pct}</span>
    </span>
  );
}

function sampleText(values: unknown[] | undefined): string {
  return (values ?? [])
    .slice(0, 3)
    .map((v) => (v === null || v === undefined ? "–" : String(v)))
    .join(" · ");
}

interface EditorProps {
  data: MappingResponse;
  currency: string;
  register: (save: MappingSaver | null) => void;
  onSaved: (r: MappingResponse) => void;
}

/**
 * One editable row per source column; low-confidence rows get an ember border and sort to the top.
 * The step's "Save and continue" saves every table through `register`, so there is no button per table.
 */
function MappingEditor({ data, currency, register, onSaved }: EditorProps) {
  const guard = useAccessGuard();
  // A mapping saved before units followed the field (a date axis with no unit, money with none) shows the implied one.
  const [rows, setRows] = useState<ColumnMapping[]>(() => {
    const kindOf = new Map(data.targets.map((t) => [t.id, t.kind]));
    const cols = new Map(data.dataset.columns.map((c) => [c.name, c]));
    return (data.confirmed ?? data.proposed).map((r) => {
      const kind = r.canonical_field ? kindOf.get(r.canonical_field) : undefined;
      const unit = r.unit ?? "";
      const fits =
        kind === "date" || kind === "text" ? unit === kind : kind === "money" ? isCurrency(unit) : kind === "count" ? FIGURE_UNITS.includes(unit) : true;
      return fits ? r : { ...r, unit: unitFor(kind, cols.get(r.source_column), currency) };
    });
  });
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [order] = useState(() =>
    (data.confirmed ?? data.proposed)
      .map((r, i) => ({ i, low: r.confidence < LOW }))
      .sort((a, b) => Number(b.low) - Number(a.low) || a.i - b.i)
      .map((x) => x.i),
  );
  const ds = data.dataset;
  const columns = useMemo(() => new Map(ds.columns.map((c) => [c.name, c])), [ds.columns]);
  // Custom fields: the engagement's own (from the API) plus any this table names before it is saved.
  const [custom, setCustom] = useState<MappingTarget[]>(() => {
    const out = data.targets.filter((t) => t.kind === "custom");
    for (const r of data.confirmed ?? data.proposed) {
      if (r.canonical_field?.startsWith(CUSTOM) && !out.some((t) => t.id === r.canonical_field)) {
        out.push({ id: r.canonical_field, label: r.label || r.canonical_field.slice(CUSTOM.length), group: "custom", kind: "custom" });
      }
    }
    return out;
  });
  const [naming, setNaming] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const standard = useMemo(() => data.targets.filter((t) => t.kind !== "custom"), [data.targets]);
  const kinds = useMemo(() => new Map([...standard, ...custom].map((t) => [t.id, t.kind])), [standard, custom]);
  const groups = useMemo(() => {
    const g = new Map<string, MappingTarget[]>();
    for (const t of standard) g.set(t.group, [...(g.get(t.group) ?? []), t]);
    return [...g.entries()];
  }, [standard]);

  const setTarget = (i: number, field: string | null) => {
    setDirty(true);
    const label = field?.startsWith(CUSTOM) ? custom.find((t) => t.id === field)?.label : undefined;
    setRows((rs) =>
      rs.map((r, j) => {
        if (j === i) {
          const kind = field ? kinds.get(field) : undefined;
          return {
            ...r,
            canonical_field: field,
            label: label ?? "",
            unit: unitFor(kind, columns.get(r.source_column), currency),
            confidence: 1,
          };
        }
        // One date axis per table: the column that had it goes back to raw.
        if (field === "period" && r.canonical_field === "period") {
          return { ...r, canonical_field: null, unit: unitFor(undefined, columns.get(r.source_column), currency), confidence: 1 };
        }
        return r;
      }),
    );
  };
  const addCustom = (i: number) => {
    const label = draft.trim().slice(0, 80);
    const id = customId(label);
    if (!id) return;
    setCustom((cs) => (cs.some((c) => c.id === id) ? cs : [...cs, { id, label, group: "custom", kind: "custom" }]));
    setNaming(null);
    setDraft("");
    setDirty(true);
    setRows((rs) =>
      rs.map((r, j) =>
        j === i ? { ...r, canonical_field: id, label, unit: unitFor(undefined, columns.get(r.source_column), currency), confidence: 1 } : r,
      ),
    );
  };
  const setUnit = (i: number, unit: string) => {
    setDirty(true);
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, unit } : r)));
  };

  const save = useCallback(async (): Promise<boolean> => {
    if (!dirty && ds.mapping_confirmed) return true;
    setError(null);
    try {
      onSaved(await apiPut<MappingResponse>(`datasets/${ds.id}/mapping`, { mapping: rows }));
      return true;
    } catch (err) {
      if (!guard(err)) setError(errorText(err));
      return false;
    }
  }, [dirty, ds.id, ds.mapping_confirmed, rows, onSaved, guard]);

  useEffect(() => {
    register(save);
    return () => register(null);
  }, [register, save]);

  const lowCount = rows.filter((r) => r.confidence < LOW).length;

  return (
    <div className="flex flex-col gap-3">
      <div className="scroll-thin overflow-x-auto rounded-[4px] border border-line">
        <table className="w-full min-w-[640px] border-collapse text-left text-[12.5px]">
          <thead>
            <tr className="border-b border-line">
              <th className="label px-3 py-2 font-normal">Source column</th>
              <th className="label px-3 py-2 font-normal">Maps to</th>
              <th className="label px-3 py-2 font-normal">Unit</th>
              <th className="label px-3 py-2 font-normal">Confidence</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {order.map((i) => {
              const r = rows[i];
              if (!r) return null;
              const col = columns.get(r.source_column);
              const low = r.confidence < LOW;
              const kind = r.canonical_field ? kinds.get(r.canonical_field) : undefined;
              const units = unitOptions(kind, r.unit ?? "", currency);
              const newAxis = r.canonical_field === "period" && r.source_column !== ds.period_axis && r.source_column !== "period" && !ds.transposed;
              const scale = col?.scale && col.scale !== 1 ? col.scale : null;
              return (
                <tr key={r.source_column} className={cn("align-top", low && "shadow-[inset_2px_0_0_var(--ember)]")}>
                  <td className="px-3 py-2.5">
                    <span className="block font-medium text-ink">{r.source_column}</span>
                    <span className="block max-w-[28ch] truncate font-mono text-[10px] text-dim" title={sampleText(col?.sample_values)}>
                      {sampleText(col?.sample_values) || "no sample values"}
                    </span>
                    {r.note && <span className="mt-0.5 block text-[11px] text-ink-2">{r.note}</span>}
                    {scale && (
                      <span className="mt-0.5 block text-[11px] text-ink-2">
                        Values in {SCALE_WORD[scale] ?? `×${scale}`} (from the file); multiplied by {scale.toLocaleString("en-US")}.
                      </span>
                    )}
                    {newAxis && (
                      <span className="mt-0.5 block text-[11px] text-ink">
                        Vicky reads this table again with this column as its dates when you save.
                      </span>
                    )}
                    {isCurrency(r.unit) && r.unit !== currency && (
                      <span className="mt-0.5 block text-[11px] text-ink-2">
                        {r.unit?.toUpperCase()} {col?.currency === r.unit ? "read from the file" : "chosen"}; converted to {currency.toUpperCase()} at
                        Bank of Canada rates for each period.
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <label className="sr-only" htmlFor={`map-${ds.id}-${i}`}>
                      Canonical field for {r.source_column}
                    </label>
                    <select
                      id={`map-${ds.id}-${i}`}
                      className={cn(selectCls, "h-8 min-w-[180px] text-[12.5px]")}
                      value={naming === i ? NEW_CUSTOM : (r.canonical_field ?? RAW)}
                      onChange={(e) => {
                        const v = e.target.value;
                        if (v === NEW_CUSTOM) {
                          setNaming(i);
                          setDraft("");
                          return;
                        }
                        if (naming === i) setNaming(null);
                        setTarget(i, v === RAW ? null : v);
                      }}
                    >
                      <option value={RAW}>Keep as raw column</option>
                      {r.canonical_field && !kinds.has(r.canonical_field) && <option value={r.canonical_field}>{r.canonical_field}</option>}
                      {groups.map(([group, targets]) => (
                        <optgroup key={group} label={humanize(group)}>
                          {targets.map((t) => (
                            <option key={t.id} value={t.id}>
                              {t.label}
                            </option>
                          ))}
                        </optgroup>
                      ))}
                      <optgroup label="Custom">
                        {custom.map((t) => (
                          <option key={t.id} value={t.id}>
                            {t.label}
                          </option>
                        ))}
                        <option value={NEW_CUSTOM}>+ New custom field…</option>
                      </optgroup>
                    </select>
                    {naming === i && (
                      <div className="mt-1.5 flex items-center gap-1.5">
                        <label className="sr-only" htmlFor={`custom-${ds.id}-${i}`}>
                          Name of the custom field for {r.source_column}
                        </label>
                        <input
                          id={`custom-${ds.id}-${i}`}
                          autoFocus
                          value={draft}
                          maxLength={80}
                          placeholder="e.g. Active pilots"
                          onChange={(e) => setDraft(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {
                              e.preventDefault();
                              addCustom(i);
                            } else if (e.key === "Escape") setNaming(null);
                          }}
                          className="h-8 w-[150px] rounded-[3px] border border-line-strong bg-transparent px-2 text-[12.5px] text-ink placeholder:text-dim focus:border-ink focus:outline-none"
                        />
                        <button
                          type="button"
                          disabled={!customId(draft)}
                          onClick={() => addCustom(i)}
                          className="h-8 rounded-[3px] border border-line-strong px-2 font-mono text-[10.5px] uppercase text-ink hover:border-ink disabled:opacity-40"
                        >
                          Add
                        </button>
                        <button type="button" onClick={() => setNaming(null)} className="h-8 px-1 text-[11.5px] text-ink-2 hover:text-ink">
                          Cancel
                        </button>
                      </div>
                    )}
                    {r.canonical_field?.startsWith(CUSTOM) && naming !== i && (
                      <span className="mt-1 block text-[11px] text-ink-2">Custom field: charted and searchable, not used in standard metrics.</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <label className="sr-only" htmlFor={`unit-${ds.id}-${i}`}>
                      Unit for {r.source_column}
                    </label>
                    <select
                      id={`unit-${ds.id}-${i}`}
                      className={cn(selectCls, "h-8 w-[112px] text-[12.5px]")}
                      value={r.unit ?? ""}
                      disabled={units.length === 1}
                      title={kind === "date" ? `Dates, read as ${ds.granularity === "none" ? "periods" : `${ds.granularity}s`}` : undefined}
                      onChange={(e) => setUnit(i, e.target.value)}
                    >
                      {units.map((u) => (
                        <option key={u} value={u}>
                          {unitLabel(u)}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-3 py-3">
                    <Confidence value={r.confidence} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {error && <ErrorNote message={error} />}
      <p className="text-[11.5px] text-ink-2">
        {lowCount > 0
          ? `${lowCount} column${lowCount === 1 ? "" : "s"} under ${LOW * 100}% confidence, marked in ember. Check ${lowCount === 1 ? "it" : "them"} first.`
          : "Every column is mapped with good confidence."}
      </p>
    </div>
  );
}

/** Step 02 for one dataset: `GET/PUT /datasets/{id}/mapping`. The step saves every table at once via `register`. */
export function MappingTable({
  dataset,
  currency,
  register,
  onChanged,
}: {
  dataset: DatasetSummary;
  currency: string;
  register: (datasetId: string, save: MappingSaver | null) => void;
  onChanged: () => void;
}) {
  const res = useApi<MappingResponse>(`datasets/${dataset.id}/mapping`);
  const [version, setVersion] = useState(0);
  const d = res.data?.dataset ?? dataset;
  const registerOwn = useCallback((save: MappingSaver | null) => register(dataset.id, save), [register, dataset.id]);
  const { mutate } = res;
  const saved = useCallback(
    (r: MappingResponse) => {
      mutate(r);
      setVersion((v) => v + 1);
      onChanged();
    },
    [mutate, onChanged],
  );

  return (
    <section className="flex flex-col gap-3 rounded-[4px] border border-line p-3.5 md:p-4">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate font-display text-[18px] tracking-[-0.04em]">{d.name}</h3>
          <p className="label">
            {[humanize(d.table_kind || "table"), d.granularity && d.granularity !== "none" && `by ${d.granularity}`, `${d.mapped}/${d.total} mapped`]
              .filter(Boolean)
              .join(" · ")}
          </p>
          {d.notes?.length ? (
            d.notes.map((n) => (
              <p key={n} className="mt-1 text-[11.5px] text-ink-2">
                {n}
              </p>
            ))
          ) : d.transposed ? (
            <p className="mt-1 text-[11.5px] text-ink-2">Transposed: periods were columns, so each row became a field.</p>
          ) : null}
        </div>
        {d.mapping_confirmed && (
          <span className="inline-flex h-6 items-center gap-1 rounded-[3px] border border-line-strong px-2 text-[11px] text-ink">
            <Check className="size-3" strokeWidth={2} /> Saved
          </span>
        )}
      </header>
      {res.loading && !res.data ? (
        <Loading label="Loading the proposed mapping" />
      ) : res.error && !res.data ? (
        <ErrorNote message={errorText(res.error)} onRetry={res.reload} />
      ) : res.data ? (
        <MappingEditor key={`${res.data.dataset.id}:${version}`} data={res.data} currency={currency} register={registerOwn} onSaved={saved} />
      ) : null}
    </section>
  );
}
