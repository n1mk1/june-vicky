"use client";

import { GitFork, Trash2 } from "lucide-react";
import { useState } from "react";
import { CornerMarks } from "@/components/ui/Panel";
import { PillButton } from "@/components/ui/Pill";
import { ErrorNote, Loading } from "@/components/ui/States";
import { VcGlyph } from "@/components/ui/VcGlyph";
import { apiDelete, apiPost } from "@/lib/api";
import { humanize } from "@/lib/format";
import type { PersonaSummary } from "@/lib/types";
import { errorText, useAccessGuard, useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";

const LENS_LABEL: Record<string, string> = {
  claims: "Claims",
  forecast: "Forecast",
  retention: "Retention",
  unit_economics: "Unit economics",
  concentration: "Concentration",
  runway: "Runway",
  governance: "Governance",
  market: "Market",
  team: "Team",
  product_tech: "Product & tech",
  terms_cap_table: "Terms & cap table",
  impact: "Impact",
};

function Bar({ value, max = 1, strong }: { value: number; max?: number; strong?: boolean }) {
  const frac = Math.max(0, Math.min(1, value / max));
  return (
    <span className="relative block h-[3px] flex-1 overflow-hidden rounded-full bg-line">
      <span className={cn("absolute inset-y-0 left-0 rounded-full", strong ? "bg-ink" : "bg-ink-2/70")} style={{ width: `${frac * 100}%` }} />
    </span>
  );
}

function PersonaCard({
  p,
  fresh,
  busy,
  onFork,
  onDelete,
}: {
  p: PersonaSummary;
  fresh: boolean;
  busy: boolean;
  onFork: () => void;
  onDelete: () => void;
}) {
  const lenses = Object.entries(p.priorities ?? {}).sort((a, b) => b[1] - a[1]);
  const top = new Set(lenses.slice(0, 2).map(([k]) => k));
  const interrupt = typeof p.style?.interrupt_tendency === "number" ? p.style.interrupt_tendency : null;
  const depth = typeof p.style?.follow_up_depth === "number" ? p.style.follow_up_depth : null;

  return (
    <article
      className={cn(
        "glass relative flex flex-col gap-4 rounded-[20px] p-4",
        fresh && "animate-[rise_0.7s_var(--ease-soft)_both] border-line-strong",
      )}
    >
      <CornerMarks />
      <header className="flex items-start gap-3">
        <VcGlyph glyph={p.glyph} className="size-9" />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-2">
            <h2 className="truncate font-display text-[22px] tracking-[-0.045em]">{p.name}</h2>
            <span className={cn("label shrink-0", !p.builtin && "text-ember")}>{p.builtin ? "Built-in" : "Custom"}</span>
          </div>
          <p className="truncate text-[12px] text-ink-2">
            {p.firm} · {humanize(p.archetype)}
          </p>
        </div>
      </header>

      <p className="line-clamp-3 text-[12.5px] leading-snug text-ink-2">{p.bio}</p>

      <div className="flex flex-col gap-1">
        <span className="label">Lens</span>
        <p className="text-[13px] leading-snug">{p.lens || lenses.slice(0, 2).map(([k]) => LENS_LABEL[k] ?? humanize(k)).join(" → ")}</p>
      </div>

      <div className="flex flex-col gap-1">
        <span className="label">Signature move</span>
        <p className="font-display text-[16px] leading-tight tracking-[-0.03em]">{p.signature_move}</p>
      </div>

      {lenses.length > 0 && (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5" aria-label="Lens weights">
          {lenses.map(([k, v]) => (
            <div key={k} className="flex items-center gap-2">
              <dt className={cn("w-[92px] shrink-0 truncate text-[10.5px]", top.has(k) ? "text-ink" : "text-ink-2")}>{LENS_LABEL[k] ?? humanize(k)}</dt>
              <dd className="flex flex-1 items-center" title={`${Math.round(v * 100)} of 100`}>
                <Bar value={v} strong={top.has(k)} />
              </dd>
            </div>
          ))}
        </dl>
      )}

      {(interrupt !== null || depth !== null) && (
        <dl className="grid grid-cols-2 gap-4 border-t border-line pt-3">
          {interrupt !== null && (
            <div className="flex flex-col gap-1">
              <dt className="text-[10.5px] text-ink-2">Interrupts</dt>
              <dd className="flex items-center">
                <Bar value={interrupt} strong />
              </dd>
            </div>
          )}
          {depth !== null && (
            <div className="flex flex-col gap-1">
              <dt className="text-[10.5px] text-ink-2">Follow-up depth · {depth}</dt>
              <dd className="flex items-center">
                <Bar value={depth} max={3} strong />
              </dd>
            </div>
          )}
        </dl>
      )}

      <footer className="mt-auto flex flex-wrap items-center justify-between gap-2">
        <ul className="flex flex-wrap gap-1">
          {(p.kits ?? []).map((k) => (
            <li key={k} className="rounded-full border border-line px-2 py-0.5 font-mono text-[9.5px] uppercase tracking-[-0.04em] text-ink-2">
              {k}
            </li>
          ))}
        </ul>
        {p.builtin ? (
          <PillButton
            label={busy ? "Forking" : "Fork"}
            variant="outline"
            disabled={busy}
            onClick={onFork}
            icon={<GitFork className="size-3.5" strokeWidth={1.5} />}
            title="Make an editable copy that keeps this investor's method"
          />
        ) : (
          <PillButton
            label={busy ? "Deleting" : "Delete"}
            variant="ghost"
            disabled={busy}
            onClick={onDelete}
            icon={<Trash2 className="size-3.5" strokeWidth={1.5} />}
          />
        )}
      </footer>
    </article>
  );
}

/** The Areopagus: every investor persona the panel can seat (UI doc §3.7). */
export function AreopagusView() {
  const guard = useAccessGuard();
  const list = useApi<PersonaSummary[]>("areopagus");
  const [busy, setBusy] = useState<string | null>(null);
  const [fresh, setFresh] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fork = async (p: PersonaSummary) => {
    setBusy(p.id);
    setError(null);
    try {
      const copy = await apiPost<PersonaSummary>(`areopagus/${encodeURIComponent(p.id)}/fork`);
      setFresh(copy?.id ?? null);
      list.reload();
    } catch (err) {
      if (!guard(err)) setError(errorText(err));
    } finally {
      setBusy(null);
    }
  };

  const remove = async (p: PersonaSummary) => {
    if (!window.confirm(`Delete ${p.name}? This removes them from every roster.`)) return;
    setBusy(p.id);
    setError(null);
    try {
      await apiDelete(`areopagus/${encodeURIComponent(p.id)}`);
      list.mutate((cur) => (cur ?? []).filter((x) => x.id !== p.id));
    } catch (err) {
      if (!guard(err)) setError(errorText(err));
    } finally {
      setBusy(null);
    }
  };

  const items = list.data ?? [];
  const builtins = items.filter((p) => p.builtin).length;

  return (
    <div className="scroll-thin -mx-1 min-h-0 flex-1 overflow-y-auto px-1 pb-6">
      <div className="mx-auto flex w-full max-w-[1320px] flex-col gap-6">
        <header className="flex flex-col gap-3 pt-2">
          <span className="label">Investor personas</span>
          <h1 className="display text-[clamp(40px,5.4vw,84px)]">The Areopagus</h1>
          <p className="max-w-[62ch] text-[14px] leading-snug text-ink-2">
            Every investor who can sit on your panel. Each reads your numbers through their own lenses, writes a private memo, and
            asks in their own style. Fork a built-in to make a copy you can tune; it keeps the original&apos;s method.
          </p>
          {items.length > 0 && (
            <p className="label">
              {builtins} built-in · {items.length - builtins} custom
            </p>
          )}
        </header>
        {error && <ErrorNote message={error} />}
        {list.loading && !list.data ? (
          <Loading label="Gathering the Areopagus" />
        ) : list.error && !list.data ? (
          <ErrorNote message={errorText(list.error)} onRetry={list.reload} />
        ) : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {items.map((p) => (
              <PersonaCard key={p.id} p={p} fresh={p.id === fresh} busy={busy === p.id} onFork={() => void fork(p)} onDelete={() => void remove(p)} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
