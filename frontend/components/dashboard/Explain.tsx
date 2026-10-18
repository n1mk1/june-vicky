"use client";

import { X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { fmtValue, inputLabel, sourceLabel } from "@/lib/format";
import type { InputRef, PointSource, Source } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface Explanation {
  label: string;
  /** Display string from the API, or a value + unit to format. */
  display?: string;
  value?: number | null;
  unit?: string | null;
  currency?: string | null;
  period?: string | null;
  formula?: string | null;
  inputs?: InputRef[];
  source?: Source | PointSource | null;
  kind?: string | null;
}

/** Value, formula, inputs and source for one number: the "click to explain" content (UI doc §3.4). */
export function ExplainCard({ x, onClose, className }: { x: Explanation; onClose?: () => void; className?: string }) {
  const shown = x.display || fmtValue(x.value, x.unit, x.currency);
  const url = (x.source as Source | null | undefined)?.url;
  return (
    <div className={cn("flex w-72 border border-line-strong bg-surface-solid/95 shadow-[0_12px_40px_-12px_rgba(0,0,0,0.45)] backdrop-blur-md max-w-[calc(100vw-48px)] flex-col gap-2 rounded-[4px] p-3.5 text-[12px] leading-snug text-ink-2", className)}>
      <div className="flex items-start justify-between gap-2">
        <span className="min-w-0">
          <span className="block text-ink">{x.label}</span>
          {x.period && <span className="font-mono text-[10px] text-dim">{x.period}</span>}
        </span>
        <span className="flex items-start gap-1.5">
          <span className="font-display text-[20px] leading-none tracking-[-0.04em] text-ink tabular-nums">{shown}</span>
          {onClose && (
            <button type="button" onClick={onClose} aria-label="Close" className="-mt-0.5 rounded-[3px] p-0.5 text-ink-2 hover:text-ink">
              <X className="size-3.5" strokeWidth={1.75} />
            </button>
          )}
        </span>
      </div>
      {x.kind && x.kind !== "historical" && (
        <span className="self-start rounded-[3px] border border-dashed border-line-strong px-2 py-0.5 font-mono text-[9.5px] uppercase tracking-[-0.04em]">
          {x.kind.replace("_", " ")}
        </span>
      )}
      {x.formula && <p className="text-ink-2">{x.formula}</p>}
      {!!x.inputs?.length && (
        <ul className="scroll-thin flex max-h-28 flex-col gap-0.5 overflow-y-auto border-t border-line pt-2 font-mono text-[10px] text-dim">
          {x.inputs.slice(0, 24).map((i, n) => (
            <li key={n} className="truncate" title={i.ref ?? undefined}>
              {inputLabel(i)}
              {i.ref ? ` · ${i.ref}` : ""}
            </li>
          ))}
        </ul>
      )}
      <span className="flex items-center justify-between gap-2 border-t border-line pt-2">
        <span className="font-mono text-[9.5px] uppercase tracking-[-0.04em] text-dim">{sourceLabel(x.source)}</span>
        {url && (
          <a href={url} target="_blank" rel="noreferrer" className="text-[11.5px] text-ink underline underline-offset-2">
            Open source
          </a>
        )}
      </span>
    </div>
  );
}

/** Wraps a trigger (a number or a chip); clicking toggles the explain card under it. */
export function Explainable({
  x,
  children,
  className,
  align = "left",
  triggerClassName,
}: {
  x: Explanation;
  children: ReactNode;
  className?: string;
  align?: "left" | "right";
  triggerClassName?: string;
}) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <span ref={box} className={cn("relative inline-flex max-w-full", className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        title="Click to explain"
        className={cn("text-left", triggerClassName)}
      >
        {children}
      </button>
      {open && <ExplainCard x={x} className={cn("absolute top-full z-40 mt-2", align === "right" ? "right-0" : "left-0")} />}
    </span>
  );
}
