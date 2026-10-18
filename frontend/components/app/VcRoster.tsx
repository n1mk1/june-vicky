"use client";

import { Check, PanelLeftClose, PanelLeftOpen, Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { ErrorNote, Loading } from "@/components/ui/States";
import { VcGlyph } from "@/components/ui/VcGlyph";
import type { PersonaSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

export const MAX_PANEL = 5;

interface VcRosterProps {
  personas: PersonaSummary[] | undefined;
  selected: string[];
  onToggle: (id: string) => void;
  speaking?: string | null;
  /** Seats can't change during a live session. */
  locked?: boolean;
  /** Questions asked per VC id in this session. */
  counts?: Record<string, number>;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
}

/** Investor panel from the wireframe's left column: the chair, then who sits in (up to five). */
export function VcRoster({ personas, selected, onToggle, speaking, locked, counts, loading, error, onRetry }: VcRosterProps) {
  const [collapsed, setCollapsed] = useState(false);
  const full = selected.length >= MAX_PANEL;
  // During a session only the seated investors are shown; otherwise the whole Areopagus in its order.
  const people = locked ? (personas ?? []).filter((p) => selected.includes(p.id)) : (personas ?? []);

  return (
    <aside className={cn("glass flex min-h-0 flex-col rounded-[4px] p-3", collapsed && "lg:w-[64px]")}>
      <div className="flex items-center justify-between pb-3">
        <button
          type="button"
          onClick={() => setCollapsed((v) => !v)}
          className="flex h-7 w-10 items-center justify-center rounded-[3px] border border-line text-ink-2 hover:border-line-strong hover:text-ink"
          aria-label={collapsed ? "Expand panel" : "Collapse panel"}
          aria-expanded={!collapsed}
        >
          {collapsed ? <PanelLeftOpen className="size-4" strokeWidth={1.5} /> : <PanelLeftClose className="size-4" strokeWidth={1.5} />}
        </button>
        {!collapsed && (
          <span className="label">
            Panel · {selected.length}/{MAX_PANEL}
          </span>
        )}
      </div>

      {/* Scrolls sideways on phones; focusable so the keyboard can scroll it when the seats are locked. */}
      <ul
        tabIndex={0}
        aria-label="Investors on the panel"
        className="scroll-thin flex min-h-0 flex-1 gap-2 overflow-x-auto pb-1 lg:flex-col lg:overflow-x-visible lg:overflow-y-auto lg:pb-0"
      >
        {/* The chair is always seated. */}
        <li className="w-[200px] shrink-0 lg:w-auto">
          <div
            title={collapsed ? "Vicky, chair: picks the speaker, reviews every question, scores every answer" : undefined}
            className="flex w-full items-center gap-3 rounded-[4px] border border-dashed border-line-strong p-2.5"
          >
            <VcGlyph glyph="vicky" className="text-ember" />
            {!collapsed && (
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-2">
                  <span className="font-display text-[17px] tracking-[-0.04em]">Vicky</span>
                  {speaking === "vicky" && (
                    <span className="size-1.5 rounded-full bg-ember animate-[pulse-dot_1.2s_ease-in-out_infinite]" aria-label="Speaking" />
                  )}
                </span>
                <span className="block truncate text-[11.5px] text-ink-2">Chair · reviews and scores</span>
              </span>
            )}
          </div>
        </li>
        {loading && !personas && (
          <li className="px-1 py-2">
            <Loading label="Seating the panel" />
          </li>
        )}
        {error && !personas && (
          <li className="px-1 py-2">
            <ErrorNote message={error} onRetry={onRetry} />
          </li>
        )}
        {people.map((p) => {
          const on = selected.includes(p.id);
          const blocked = locked || (!on && full);
          const n = counts?.[p.id];
          return (
            <li key={p.id} className="w-[200px] shrink-0 lg:w-auto">
              <button
                type="button"
                aria-pressed={on}
                disabled={blocked}
                onClick={() => onToggle(p.id)}
                title={collapsed ? `${p.name}, ${p.firm}` : !on && full ? `The panel holds ${MAX_PANEL} investors` : undefined}
                className={cn(
                  "group relative flex w-full items-center gap-3 rounded-[4px] border p-2.5 text-left transition-colors duration-300",
                  // Unselected cards are dimmed by text colour, not opacity, so their text keeps AA contrast.
                  on ? "border-line-strong bg-surface-solid/70" : "border-line text-ink-2 hover:border-line-strong hover:text-ink",
                  blocked && !on && "hover:border-line hover:text-ink-2",
                  locked && "cursor-default",
                )}
              >
                <VcGlyph glyph={p.glyph} />
                {!collapsed && (
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2">
                      <span className="font-display text-[17px] tracking-[-0.04em]">{p.name}</span>
                      {speaking === p.id && (
                        <span className="size-1.5 rounded-full bg-ember animate-[pulse-dot_1.2s_ease-in-out_infinite]" aria-label="Speaking" />
                      )}
                    </span>
                    <span className={cn("block truncate text-[11.5px]", on ? "text-ink-2" : "text-dim")}>{p.firm}</span>
                  </span>
                )}
                {!collapsed && (
                  <span className="flex flex-col items-end gap-1.5">
                    <span className={cn("flex size-4 items-center justify-center rounded-[5px] border", on ? "border-ink bg-ink text-bg" : "border-line-strong")}>
                      {on && <Check className="size-3" strokeWidth={2.5} />}
                    </span>
                    {n !== undefined && n > 0 && (
                      <span className="font-mono text-[9.5px] tabular-nums text-dim" aria-label={`${n} questions asked`}>
                        {n}Q
                      </span>
                    )}
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ul>

      {!collapsed && (
        <Link
          // Seats can't change mid-session, so a live session's "+" only builds; otherwise the builder
          // brings you back here with the new investor seated next to the current panel.
          href={locked ? "/areopagus?build=1" : `/areopagus?build=1&return=preparation&panel=${encodeURIComponent(selected.join(","))}`}
          data-testid="roster-add"
          className="mx-auto mt-3 hidden size-10 items-center justify-center rounded-full border border-line-strong text-ink-2 transition-colors hover:border-ink hover:text-ink lg:flex"
          aria-label="Add or build an investor in the Areopagus"
          title="Build an investor in the Areopagus"
        >
          <Plus className="size-4" strokeWidth={1.5} />
        </Link>
      )}
    </aside>
  );
}
