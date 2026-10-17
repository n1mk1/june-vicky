"use client";

import { sourceLabel } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Explainable, type Explanation } from "./Explain";

/** Every figure shows where it came from; clicking reveals the calculation. */
export function SourceChip({ x, className, align }: { x: Explanation; className?: string; align?: "left" | "right" }) {
  const summary = x.source?.kind === "pack_summary" || (x.kind && x.kind !== "historical");
  return (
    <Explainable
      x={x}
      align={align}
      className={className}
      triggerClassName={cn(
        "max-w-full truncate rounded-full border px-2 py-0.5 font-mono text-[9.5px] uppercase tracking-[-0.04em] text-ink-2 transition-colors hover:text-ink",
        summary ? "border-dashed border-line-strong" : "border-line hover:border-line-strong",
      )}
    >
      {sourceLabel(x.source)}
    </Explainable>
  );
}
