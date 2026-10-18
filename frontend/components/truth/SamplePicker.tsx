"use client";

import { ArrowRight } from "lucide-react";
import { useState } from "react";
import { ErrorNote, Loading } from "@/components/ui/States";
import { apiPost } from "@/lib/api";
import { humanize } from "@/lib/format";
import type { Engagement, Sample } from "@/lib/types";
import { errorText, useAccessGuard, useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";

/** "Try a sample": the fixture goes through the same TruthPack path as an upload (App flow §2b). */
export function SamplePicker({ onLoaded }: { onLoaded: (e: Engagement) => void }) {
  const samples = useApi<Sample[]>("samples");
  const guard = useAccessGuard();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async (id: string) => {
    setBusy(id);
    setError(null);
    try {
      onLoaded(await apiPost<Engagement>(`samples/${encodeURIComponent(id)}/load`));
    } catch (err) {
      setBusy(null);
      if (!guard(err)) setError(errorText(err));
    }
  };

  if (samples.loading && !samples.data) return <Loading label="Loading samples" />;
  if (samples.error) return <ErrorNote message={errorText(samples.error)} onRetry={samples.reload} />;
  if (!samples.data?.length) return <p className="text-[12.5px] text-ink-2">No samples are installed on this server.</p>;

  return (
    <div className="flex flex-col gap-2">
      <ul className="grid gap-2">
        {samples.data.map((s) => (
          <li key={s.id}>
            <button
              type="button"
              onClick={() => void load(s.id)}
              disabled={!!busy}
              className={cn(
                "group flex w-full items-start gap-3 rounded-[4px] border p-3.5 text-left transition-colors disabled:opacity-60",
                busy === s.id ? "border-ink bg-surface-solid/70" : "border-line hover:border-line-strong hover:bg-surface-solid/40",
              )}
            >
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-baseline gap-x-2">
                  <span className="font-display text-[18px] tracking-[-0.04em]">{s.name}</span>
                  <span className="label">
                    {[s.country, s.business_model && humanize(s.business_model), s.granularity && `by ${s.granularity}`]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </span>
                {s.one_liner && <span className="mt-1 line-clamp-2 block text-[12.5px] leading-snug text-ink-2">{s.one_liner}</span>}
              </span>
              <span className="mt-1 flex shrink-0 items-center gap-1 text-[11.5px] text-ink-2 group-hover:text-ink">
                {busy === s.id ? "Loading…" : "Load"}
                <ArrowRight className="size-3.5" strokeWidth={1.5} />
              </span>
            </button>
          </li>
        ))}
      </ul>
      {error && <ErrorNote message={error} />}
      <p className="text-[11.5px] text-dim">Synthetic data. Fictional companies.</p>
    </div>
  );
}
