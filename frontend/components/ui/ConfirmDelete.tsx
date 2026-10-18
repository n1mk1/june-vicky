"use client";

import { Trash2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

interface ConfirmDeleteProps {
  /** What is deleted, for the accessible names ("Delete <what>"). */
  what: string;
  onConfirm: () => void | Promise<void>;
  /** Classes for the idle trash button (size, colour, hover reveal). */
  className?: string;
  title?: string;
}

/**
 * Two-step delete in place: the trash button arms it, then "Delete" confirms (Escape or ✕ cancels).
 * Used instead of `window.confirm`, which embedded browsers can suppress: it returns false without
 * showing anything, so the delete silently never happens.
 */
export function ConfirmDelete({ what, onConfirm, className, title = "Delete" }: ConfirmDeleteProps) {
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const yes = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (armed) yes.current?.focus();
  }, [armed]);

  if (!armed) {
    return (
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setArmed(true);
        }}
        aria-label={`Delete ${what}`}
        title={title}
        className={cn("grid size-7 shrink-0 place-items-center rounded-full transition-colors hover:text-ember", className)}
      >
        <Trash2 className="size-3.5" strokeWidth={1.5} />
      </button>
    );
  }

  return (
    <span
      className="flex shrink-0 items-center gap-0.5"
      onKeyDown={(e) => {
        if (e.key === "Escape") setArmed(false);
      }}
      onBlur={(e) => {
        if (!busy && !e.currentTarget.contains(e.relatedTarget as Node | null)) setArmed(false);
      }}
    >
      <button
        ref={yes}
        type="button"
        disabled={busy}
        onClick={async (e) => {
          e.stopPropagation();
          setBusy(true);
          try {
            await onConfirm();
          } finally {
            setBusy(false);
            setArmed(false);
          }
        }}
        aria-label={`Confirm delete ${what}`}
        className="h-6 rounded-[3px] bg-ember px-2 font-mono text-[10.5px] uppercase tracking-[-0.02em] text-invert-ink transition-opacity hover:opacity-90 disabled:opacity-60"
      >
        {busy ? "Deleting" : "Delete"}
      </button>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setArmed(false);
        }}
        aria-label="Cancel delete"
        title="Cancel"
        className="grid size-6 shrink-0 place-items-center rounded-full opacity-70 transition-opacity hover:opacity-100"
      >
        <X className="size-3.5" strokeWidth={1.5} />
      </button>
    </span>
  );
}
