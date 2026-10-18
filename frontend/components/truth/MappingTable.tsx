"use client";

import { Check } from "lucide-react";
import { useMemo, useState } from "react";
import { selectCls } from "@/components/ui/Field";
import { PillButton } from "@/components/ui/Pill";
import { ErrorNote, Loading } from "@/components/ui/States";
import { apiPut } from "@/lib/api";
import { humanize } from "@/lib/format";
import type { ColumnMapping, DatasetSummary, MappingResponse, MappingTarget } from "@/lib/types";
import { errorText, useAccessGuard, useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";

const LOW = 0.6;
const RAW = "__raw__";

function unitOptions(currency: string): string[] {
  return ["", currency, "pct", "count", "months", "ratio", "x"].filter((u, i, a) => a.indexOf(u) === i);
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
  onSaved: (r: MappingResponse) => void;
}

/** One editable row per source column; low-confidence rows get an ember border and sort to the top. */
function MappingEditor({ data, currency, onSaved }: EditorProps) {
  const guard = useAccessGuard();
  const [rows, setRows] = useState<ColumnMapping[]>(() => data.confirmed ?? data.proposed);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [order] = useState(() =>
    (data.confirmed ?? data.proposed)
      .map((r, i) => ({ i, low: r.confidence < LOW }))
      .sort((a, b) => Number(b.low) - Number(a.low) || a.i - b.i)
      .map((x) => x.i),
  );
  const columns = useMemo(() => new Map(data.dataset.columns.map((c) => [c.name, c])), [data.dataset.columns]);
  const groups = useMemo(() => {
    const g = new Map<string, MappingTarget[]>();
    for (const t of data.targets) g.set(t.group, [...(g.get(t.group) ?? []), t]);
    return [...g.entries()];
  }, [data.targets]);
  const units = unitOptions(currency);

  const update = (i: number, patch: Partial<ColumnMapping>) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch, confidence: patch.canonical_field !== undefined ? 1 : r.confidence } : r)));

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      onSaved(await apiPut<MappingResponse>(`datasets/${data.dataset.id}/mapping`, { mapping: rows }));
    } catch (err) {
      if (!guard(err)) setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

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
              return (
                <tr key={r.source_column} className={cn("align-top", low && "shadow-[inset_2px_0_0_var(--ember)]")}>
                  <td className="px-3 py-2.5">
                    <span className="block font-medium text-ink">{r.source_column}</span>
                    <span className="block max-w-[28ch] truncate font-mono text-[10px] text-dim" title={sampleText(col?.sample_values)}>
                      {sampleText(col?.sample_values) || "no sample values"}
                    </span>
                    {r.note && <span className="mt-0.5 block text-[11px] text-ink-2">{r.note}</span>}
                  </td>
                  <td className="px-3 py-2">
                    <label className="sr-only" htmlFor={`map-${data.dataset.id}-${i}`}>
                      Canonical field for {r.source_column}
                    </label>
                    <select
                      id={`map-${data.dataset.id}-${i}`}
                      className={cn(selectCls, "h-8 min-w-[180px] text-[12.5px]")}
                      value={r.canonical_field ?? RAW}
                      onChange={(e) => update(i, { canonical_field: e.target.value === RAW ? null : e.target.value })}
                    >
                      <option value={RAW}>Keep as raw column</option>
                      {r.canonical_field && !data.targets.some((t) => t.id === r.canonical_field) && (
                        <option value={r.canonical_field}>{r.canonical_field}</option>
                      )}
                      {groups.map(([group, targets]) => (
                        <optgroup key={group} label={humanize(group)}>
                          {targets.map((t) => (
                            <option key={t.id} value={t.id}>
                              {t.label}
                            </option>
                          ))}
                        </optgroup>
                      ))}
                    </select>
                  </td>
                  <td className="px-3 py-2">
                    <label className="sr-only" htmlFor={`unit-${data.dataset.id}-${i}`}>
                      Unit for {r.source_column}
                    </label>
                    <select
                      id={`unit-${data.dataset.id}-${i}`}
                      className={cn(selectCls, "h-8 w-[96px] text-[12.5px]")}
                      value={r.unit ?? ""}
                      onChange={(e) => update(i, { unit: e.target.value })}
                    >
                      {(units.includes(r.unit ?? "") ? units : [r.unit, ...units]).map((u) => (
                        <option key={u} value={u}>
                          {u ? u.toUpperCase() : "—"}
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
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-[11.5px] text-ink-2">
          {lowCount > 0
            ? `${lowCount} column${lowCount === 1 ? "" : "s"} under ${LOW * 100}% confidence, marked in ember. Check ${lowCount === 1 ? "it" : "them"} first.`
            : "Every column is mapped with good confidence."}
        </p>
        <PillButton
          variant={data.dataset.mapping_confirmed ? "outline" : "solid"}
          label={busy ? "Saving" : data.dataset.mapping_confirmed ? "Save changes" : "Confirm mapping"}
          disabled={busy}
          onClick={() => void save()}
        />
      </div>
    </div>
  );
}

/** Step 02 for one dataset: `GET/PUT /datasets/{id}/mapping`. */
export function MappingTable({
  dataset,
  currency,
  onChanged,
}: {
  dataset: DatasetSummary;
  currency: string;
  onChanged: () => void;
}) {
  const res = useApi<MappingResponse>(`datasets/${dataset.id}/mapping`);
  const [version, setVersion] = useState(0);
  const d = res.data?.dataset ?? dataset;

  return (
    <section className="flex flex-col gap-3 rounded-[4px] border border-line p-3.5 md:p-4">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate font-display text-[18px] tracking-[-0.04em]">{d.name}</h3>
          <p className="label">
            {[humanize(d.table_kind || "table"), d.granularity && `by ${d.granularity}`, `${d.mapped}/${d.total} mapped`]
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
            <Check className="size-3" strokeWidth={2} /> Confirmed
          </span>
        )}
      </header>
      {res.loading && !res.data ? (
        <Loading label="Loading the proposed mapping" />
      ) : res.error && !res.data ? (
        <ErrorNote message={errorText(res.error)} onRetry={res.reload} />
      ) : res.data ? (
        <MappingEditor
          key={`${res.data.dataset.id}:${version}`}
          data={res.data}
          currency={currency}
          onSaved={(r) => {
            res.mutate(r);
            setVersion((v) => v + 1);
            onChanged();
          }}
        />
      ) : null}
    </section>
  );
}
