"use client";

import { Check, PanelLeftClose, PanelLeftOpen, Plus } from "lucide-react";
import { useState } from "react";
import { VcGlyph } from "@/components/ui/VcGlyph";
import { PANEL, type Persona, type Temperature } from "@/lib/panel";
import { cn } from "@/lib/utils";

const TEMP: Record<Temperature, string> = { warming: "Warming", steady: "Steady", cooling: "Cooling" };

function TempBars({ t }: { t: Temperature }) {
  const lit = t === "warming" ? 3 : t === "steady" ? 2 : 1;
  return (
    <span className="flex items-end gap-[2px]" aria-label={`Interest ${TEMP[t].toLowerCase()}`} role="img">
      {[0, 1, 2].map((i) => (
        <span key={i} className={cn("w-[3px] rounded-full", i < lit ? "bg-ink" : "bg-line-strong")} style={{ height: 4 + i * 3 }} />
      ))}
    </span>
  );
}

interface VcRosterProps {
  selected: string[];
  onToggle: (id: string) => void;
  speaking?: string;
}

/** Investor panel from the wireframe's left column: pick who sits in, add your own. */
export function VcRoster({ selected, onToggle, speaking }: VcRosterProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [custom, setCustom] = useState<Persona[]>([]);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState("");
  const people = [...PANEL, ...custom];

  const add = () => {
    const text = draft.trim();
    if (!text) return;
    const id = `custom-${custom.length + 1}`;
    setCustom((c) => [
      ...c,
      {
        id,
        name: `Investor ${PANEL.length + c.length + 1}`,
        firm: "Custom",
        lens: text,
        move: "Generated from your description",
        glyph: "custom",
        temperature: "steady",
        builtin: false,
      },
    ]);
    onToggle(id);
    setDraft("");
    setAdding(false);
  };

  return (
    <aside className={cn("glass flex min-h-0 flex-col rounded-[20px] p-3", collapsed && "lg:w-[64px]")}>
      <div className="flex items-center justify-between pb-3">
        <button
          type="button"
          onClick={() => setCollapsed((v) => !v)}
          className="flex h-7 w-10 items-center justify-center rounded-[8px] border border-line text-ink-2 hover:border-line-strong hover:text-ink"
          aria-label={collapsed ? "Expand panel" : "Collapse panel"}
          aria-expanded={!collapsed}
        >
          {collapsed ? <PanelLeftOpen className="size-4" strokeWidth={1.5} /> : <PanelLeftClose className="size-4" strokeWidth={1.5} />}
        </button>
        {!collapsed && <span className="label">Panel · {selected.length}</span>}
      </div>

      <ul className="scroll-thin flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto">
        {people.map((p) => {
          const on = selected.includes(p.id);
          return (
            <li key={p.id}>
              <button
                type="button"
                aria-pressed={on}
                onClick={() => onToggle(p.id)}
                title={collapsed ? `${p.name}, ${p.firm}` : undefined}
                className={cn(
                  "group relative flex w-full items-center gap-3 rounded-[14px] border p-2.5 text-left transition-colors duration-300",
                  on ? "border-line-strong bg-surface-solid/70" : "border-line opacity-60 hover:opacity-100",
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
                    <span className="block truncate text-[11.5px] text-ink-2">{p.firm}</span>
                  </span>
                )}
                {!collapsed && (
                  <span className="flex flex-col items-end gap-1.5">
                    <span className={cn("flex size-4 items-center justify-center rounded-[5px] border", on ? "border-ink bg-ink text-bg" : "border-line-strong")}>
                      {on && <Check className="size-3" strokeWidth={2.5} />}
                    </span>
                    <TempBars t={p.temperature} />
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ul>

      {!collapsed && adding && (
        <div className="mt-3 flex flex-col gap-2 rounded-[14px] border border-line p-2.5">
          <label htmlFor="new-vc" className="text-[11.5px] text-ink-2">
            Describe the investor
          </label>
          <textarea
            id="new-vc"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={3}
            placeholder="A SaaS fund partner who cares most about net revenue retention"
            className="resize-none rounded-[8px] border border-line bg-transparent p-2 text-[12.5px] placeholder:text-dim focus:border-line-strong focus:outline-none"
          />
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setAdding(false)} className="text-[12px] text-ink-2 hover:text-ink">
              Cancel
            </button>
            <button type="button" onClick={add} className="rounded-full bg-invert-bg px-3 py-1 text-[12px] text-invert-ink">
              Add to panel
            </button>
          </div>
        </div>
      )}

      {!adding && (
        <button
          type="button"
          onClick={() => {
            setCollapsed(false);
            setAdding(true);
          }}
          className="mx-auto mt-3 flex size-10 items-center justify-center rounded-full border border-line-strong text-ink-2 transition-colors hover:border-ink hover:text-ink"
          aria-label="Add an investor"
        >
          <Plus className="size-4" strokeWidth={1.5} />
        </button>
      )}
    </aside>
  );
}
