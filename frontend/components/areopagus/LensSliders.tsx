"use client";

import { cn } from "@/lib/utils";

/** Weights at or above this pull in the lens's kit tools on the backend (`kits.LENS_THRESHOLD`). */
const KIT_THRESHOLD = 0.6;

/** One slider per lens, 0–100: how hard this investor presses on it. */
export function LensSliders({
  lenses,
  value,
  onChange,
}: {
  lenses: { id: string; label: string }[];
  value: Record<string, number>;
  onChange: (v: Record<string, number>) => void;
}) {
  return (
    <ul className="flex flex-col gap-1" aria-label="Lens weights">
      {lenses.map((l) => {
        const w = value[l.id] ?? 0;
        const strong = w >= KIT_THRESHOLD;
        return (
          <li key={l.id} className="grid grid-cols-[minmax(0,150px)_1fr_28px] items-center gap-3">
            <label htmlFor={`lens-${l.id}`} className={cn("truncate text-[12px]", strong ? "text-ink" : "text-ink-2")} title={l.label}>
              {l.label}
            </label>
            <input
              id={`lens-${l.id}`}
              type="range"
              min={0}
              max={100}
              step={5}
              value={Math.round(w * 100)}
              onChange={(e) => onChange({ ...value, [l.id]: Number(e.target.value) / 100 })}
              className={cn("h-6 w-full", strong ? "accent-[var(--ember)]" : "accent-[var(--ink-2)]")}
            />
            <span className="text-right font-mono text-[10.5px] tabular-nums text-ink-2">{Math.round(w * 100)}</span>
          </li>
        );
      })}
    </ul>
  );
}
