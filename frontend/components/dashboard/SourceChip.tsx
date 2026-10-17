"use client";

import { useState } from "react";
import type { Figure } from "@/lib/tidewell";
import { cn } from "@/lib/utils";

/** Every figure shows where it came from; clicking reveals the calculation. */
export function SourceChip({ figure, className }: { figure: Figure; className?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <span className={cn("relative inline-flex", className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className={cn(
          "rounded-full border px-2 py-0.5 font-mono text-[9.5px] uppercase tracking-[-0.04em] transition-colors",
          figure.kind === "pack_summary" ? "border-dashed border-line-strong text-ink-2" : "border-line text-ink-2 hover:border-line-strong",
        )}
      >
        {figure.source}
      </button>
      {open && (
        <span className="glass absolute top-full left-0 z-30 mt-2 w-60 rounded-[12px] p-3 text-[12px] leading-snug text-ink-2 shadow-none">
          <span className="block text-ink">{figure.label}</span>
          {figure.formula}
        </span>
      )}
    </span>
  );
}
