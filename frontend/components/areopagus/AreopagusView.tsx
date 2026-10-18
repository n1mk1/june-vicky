"use client";

import { GitFork, Pencil, Plus, Trash2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { CornerMarks } from "@/components/ui/Panel";
import { PillButton } from "@/components/ui/Pill";
import { ErrorNote, Loading } from "@/components/ui/States";
import { MAX_PANEL } from "@/components/app/VcRoster";
import { VcGlyph } from "@/components/ui/VcGlyph";
import { apiDelete, apiPost } from "@/lib/api";
import { humanize } from "@/lib/format";
import type { PersonaSummary } from "@/lib/types";
import { errorText, useAccessGuard, useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";
import { PersonaBuilder } from "./PersonaBuilder";

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

/** Height of an opened card (bio, five lens weights, style, actions), used to pick its direction. */
const OPEN_HEIGHT = 470;

function Bar({ value, max = 1, strong }: { value: number; max?: number; strong?: boolean }) {
  const frac = Math.max(0, Math.min(1, value / max));
  return (
    <span className="relative block h-[3px] flex-1 overflow-hidden rounded-full bg-line">
      <span className={cn("absolute inset-y-0 left-0 rounded-full", strong ? "bg-ink" : "bg-ink-2/70")} style={{ width: `${frac * 100}%` }} />
    </span>
  );
}

/**
 * A compact tile (name, firm, signature move, lens) that opens on hover or keyboard focus into the
 * full card: bio, lens weights, style and actions. The open card floats over its neighbours instead
 * of pushing the grid, so the whole Areopagus stays on one screen. Near the bottom of the viewport it
 * opens upwards.
 */
function PersonaCard({
  p,
  fresh,
  busy,
  onFork,
  onEdit,
  onDelete,
}: {
  p: PersonaSummary;
  fresh: boolean;
  busy: boolean;
  onFork: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const [up, setUp] = useState(false);
  const [room, setRoom] = useState<number | null>(null);
  const lenses = Object.entries(p.priorities ?? {}).sort((a, b) => b[1] - a[1]);
  const top = new Set(lenses.slice(0, 2).map(([k]) => k));
  const interrupt = typeof p.style?.interrupt_tendency === "number" ? p.style.interrupt_tendency : null;
  const depth = typeof p.style?.follow_up_depth === "number" ? p.style.follow_up_depth : null;
  const lensLine = p.lens || lenses.slice(0, 2).map(([k]) => LENS_LABEL[k] ?? humanize(k)).join(" → ");

  // Open towards whichever side has room for the full card; cap it to that room (it scrolls inside).
  const place = (el: HTMLElement) => {
    const r = el.getBoundingClientRect();
    // Stay inside the page's scroll area so an open card never slides under the app header.
    const area = el.closest("[data-scroll-area]")?.getBoundingClientRect() ?? { top: 0, bottom: window.innerHeight };
    const down = area.bottom - r.top - 8;
    const upward = r.bottom - area.top - 8;
    const openUp = down < OPEN_HEIGHT && upward > down;
    setUp(openUp);
    setRoom(Math.max(r.height, openUp ? upward : down));
    el.querySelector("article")?.scrollTo({ top: 0 }); // always open on the header
  };

  return (
    <li
      className="group/card relative h-[156px] focus-within:z-30 hover:z-30"
      onMouseEnter={(e) => place(e.currentTarget)}
      onFocus={(e) => place(e.currentTarget)}
    >
      <article
        tabIndex={0}
        style={room ? { maxHeight: room } : undefined}
        aria-label={`${p.name}, ${p.firm}. ${p.signature_move}`}
        className={cn(
          "glass scroll-thin absolute inset-x-0 flex min-h-full flex-col overflow-hidden rounded-[4px] p-4 outline-none [&>*]:shrink-0 group-focus-within/card:overflow-y-auto group-hover/card:overflow-y-auto transition-[box-shadow,background-color,border-color] duration-300",
          "group-hover/card:border-line-strong group-hover/card:bg-surface-solid group-hover/card:shadow-[0_24px_60px_-20px_rgba(0,0,0,0.55)]",
          "group-focus-within/card:border-line-strong group-focus-within/card:bg-surface-solid group-focus-within/card:shadow-[0_24px_60px_-20px_rgba(0,0,0,0.55)]",
          "focus-visible:ring-1 focus-visible:ring-ink-2",
          up ? "bottom-0" : "top-0",
          fresh && "animate-[rise_0.7s_var(--ease-soft)_both] border-line-strong",
        )}
      >
        <CornerMarks />
        <header className="flex items-start gap-3">
          <VcGlyph glyph={p.glyph} className="size-8" />
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline justify-between gap-2">
              <h2 className="truncate font-display text-[20px] leading-tight tracking-[-0.045em]">{p.name}</h2>
              <span className={cn("label shrink-0", !p.builtin && "text-ember")}>{p.builtin ? "Built-in" : "Custom"}</span>
            </div>
            <p className="truncate text-[11.5px] text-ink-2">
              {p.firm} · {humanize(p.archetype)}
            </p>
          </div>
        </header>

        <p className="mt-3 line-clamp-2 font-display text-[15px] leading-tight tracking-[-0.03em]">{p.signature_move}</p>
        <p className="mt-auto truncate pt-2 text-[11.5px] text-ink-2" title={lensLine}>
          <span className="label mr-1.5">Lens</span>
          {lensLine}
        </p>

        {/* Details: collapsed to zero height until the card is hovered or focused. */}
        <div className="grid grid-rows-[0fr] opacity-0 transition-[grid-template-rows,opacity] duration-300 ease-[var(--ease-soft)] group-focus-within/card:grid-rows-[1fr] group-focus-within/card:opacity-100 group-hover/card:grid-rows-[1fr] group-hover/card:opacity-100">
          <div className="flex min-h-0 flex-col gap-3 overflow-hidden">
            <p className="mt-3 border-t border-line pt-3 line-clamp-5 text-[12.5px] leading-snug text-ink-2" title={p.bio}>{p.bio}</p>

            {lenses.length > 0 && (
              <dl className="flex flex-col gap-1.5" aria-label="Lens weights">
                {lenses.slice(0, 5).map(([k, v]) => (
                  <div key={k} className="flex items-center gap-2">
                    <dt className={cn("w-[104px] shrink-0 truncate text-[10.5px]", top.has(k) ? "text-ink" : "text-ink-2")}>
                      {LENS_LABEL[k] ?? humanize(k)}
                    </dt>
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

            <footer className="flex flex-wrap items-center justify-between gap-2 pb-0.5">
              <ul className="flex flex-wrap gap-1">
                {(p.kits ?? []).map((k) => (
                  <li key={k} className="rounded-[3px] border border-line px-2 py-0.5 font-mono text-[9.5px] uppercase tracking-[-0.04em] text-ink-2">
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
                <span className="flex items-center gap-1">
                  <PillButton label="Edit" variant="outline" disabled={busy} onClick={onEdit} icon={<Pencil className="size-3.5" strokeWidth={1.5} />} />
                  <PillButton
                    label={busy ? "Deleting" : "Delete"}
                    variant="ghost"
                    disabled={busy}
                    onClick={onDelete}
                    icon={<Trash2 className="size-3.5" strokeWidth={1.5} />}
                  />
                </span>
              )}
            </footer>
          </div>
        </div>
      </article>
    </li>
  );
}

/**
 * The Areopagus: every investor persona the panel can seat (UI doc §3.7), and the builder.
 * The URL opens the builder: `?build=1` (new) or `?edit=<id>`. `return=preparation&panel=a,b` marks
 * a trip from the Preparation roster's "+": saving goes back there with the new investor seated.
 */
export function AreopagusView() {
  const guard = useAccessGuard();
  const router = useRouter();
  const params = useSearchParams();
  const list = useApi<PersonaSummary[]>("areopagus");
  const editId = params.get("edit");
  const building = params.get("build") === "1" || !!editId;
  const fromPrep = params.get("return") === "preparation";
  const panel = (params.get("panel") ?? "").split(",").filter(Boolean).slice(0, MAX_PANEL);
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

  const prepUrl = (ids: string[], added?: string) => {
    const q = new URLSearchParams();
    if (ids.length) q.set("panel", ids.join(","));
    if (added) q.set("added", added);
    const qs = q.toString();
    return qs ? `/preparation?${qs}` : "/preparation";
  };

  const closeBuilder = () => {
    if (fromPrep) router.push(prepUrl(panel));
    else router.replace("/areopagus", { scroll: false });
  };

  const onSaved = (id: string) => {
    if (fromPrep) {
      router.push(prepUrl(panel.length < MAX_PANEL ? [...panel, id] : panel, id));
      return;
    }
    setFresh(id);
    list.reload();
    router.replace("/areopagus", { scroll: false });
  };

  const items = list.data ?? [];
  const builtins = items.filter((p) => p.builtin).length;

  return (
    <div data-scroll-area className="scroll-thin -mx-1 min-h-0 flex-1 overflow-y-auto px-1 pb-4">
      <div className="mx-auto flex w-full max-w-[1480px] flex-col gap-5">
        <header className="flex flex-col gap-x-8 gap-y-2 pt-1 lg:flex-row lg:items-end lg:justify-between">
          <div className="flex flex-col gap-1">
            <span className="label">
              Investor personas{items.length > 0 && ` · ${builtins} built-in · ${items.length - builtins} custom`}
            </span>
            <h1 className="display text-[clamp(34px,3.8vw,60px)]">The Areopagus</h1>
          </div>
          <div className="flex flex-col items-start gap-3 lg:items-end lg:pb-1.5">
            <p className="max-w-[58ch] text-[13px] leading-snug text-ink-2 lg:text-right">
              Every investor who can sit on your panel reads your numbers through their own lenses. Hover or tap a card for their method;
              describe a new one, or fork a built-in to make a copy you can tune.
            </p>
            <PillButton
              label="New investor"
              variant="solid"
              onClick={() => router.replace("/areopagus?build=1", { scroll: false })}
              icon={<Plus className="size-3.5" strokeWidth={1.75} />}
            />
          </div>
        </header>
        {error && <ErrorNote message={error} />}
        {list.loading && !list.data ? (
          <Loading label="Gathering the Areopagus" />
        ) : list.error && !list.data ? (
          <ErrorNote message={errorText(list.error)} onRetry={list.reload} />
        ) : (
          <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5" aria-label="Investors">
            {items.map((p) => (
              <PersonaCard
                key={p.id}
                p={p}
                fresh={p.id === fresh}
                busy={busy === p.id}
                onFork={() => void fork(p)}
                onEdit={() => router.replace(`/areopagus?edit=${encodeURIComponent(p.id)}`, { scroll: false })}
                onDelete={() => void remove(p)}
              />
            ))}
          </ul>
        )}
      </div>
      {building && (
        <PersonaBuilder key={editId ?? "new"} mode={editId ? "edit" : "create"} personaId={editId ?? undefined} onSaved={onSaved} onClose={closeBuilder} />
      )}
    </div>
  );
}
