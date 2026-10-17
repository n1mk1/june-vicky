"use client";

import { ArrowUp, Paperclip } from "lucide-react";
import { useId, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

export const ATTACH_ACCEPT = ".csv,.xlsx,.pdf,.docx,.md";

interface PromptBarProps {
  placeholder: string;
  label: string;
  onSubmit: (text: string) => void;
  /** Called with the picked file; the attach button only appears when this is set (or `leading` replaces it). */
  onAttach?: (file: File) => void;
  /** Replaces the attach button on the left, e.g. a microphone. */
  leading?: ReactNode;
  hint?: ReactNode;
  /** Shows a thin progress line under the bar (upload, waiting for the panel). */
  busy?: boolean;
  disabled?: boolean;
  className?: string;
}

/** Glass input bar with a tool button on the left and send on the right, as in the wireframe. */
export function PromptBar({ placeholder, label, onSubmit, onAttach, leading, hint, busy, disabled, className }: PromptBarProps) {
  const [value, setValue] = useState("");
  const id = useId();
  const file = useRef<HTMLInputElement>(null);

  return (
    <form
      className={cn("glass relative overflow-hidden rounded-[18px] p-2", className)}
      onSubmit={(e) => {
        e.preventDefault();
        const text = value.trim();
        if (!text || disabled) return;
        onSubmit(text);
        setValue("");
      }}
    >
      <div className="flex items-center gap-2 rounded-[12px] border border-line bg-surface-solid/60 p-1.5">
        {leading ??
          (onAttach && (
            <>
              <button
                type="button"
                onClick={() => file.current?.click()}
                disabled={busy}
                className="flex size-8 shrink-0 items-center justify-center rounded-[9px] border border-line text-ink-2 transition-colors hover:border-line-strong hover:text-ink disabled:opacity-40"
                aria-label="Attach a file (CSV, XLSX, PDF, DOCX or MD)"
                title="Attach CSV, XLSX, PDF, DOCX or MD"
              >
                <Paperclip className="size-4" strokeWidth={1.5} />
              </button>
              <input
                ref={file}
                type="file"
                accept={ATTACH_ACCEPT}
                className="sr-only"
                tabIndex={-1}
                aria-hidden
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  e.target.value = "";
                  if (f) onAttach(f);
                }}
              />
            </>
          ))}
        <label htmlFor={id} className="sr-only">
          {label}
        </label>
        <input
          id={id}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={placeholder}
          autoComplete="off"
          disabled={disabled}
          className="h-8 min-w-0 flex-1 bg-transparent px-1 text-[14px] text-ink placeholder:text-dim focus:outline-none disabled:cursor-not-allowed"
        />
        <button
          type="submit"
          disabled={!value.trim() || disabled}
          className="flex size-8 shrink-0 items-center justify-center rounded-[9px] bg-invert-bg text-invert-ink transition-opacity disabled:opacity-35"
          aria-label="Send"
        >
          <ArrowUp className="size-4" strokeWidth={1.75} />
        </button>
      </div>
      {hint && <p className="px-2 pt-2 text-[11.5px] text-dim">{hint}</p>}
      {busy && (
        <span aria-hidden className="absolute inset-x-0 bottom-0 h-px overflow-hidden">
          <span className="block h-full w-1/3 bg-ember animate-[progress-slide_1.1s_var(--ease-soft)_infinite]" />
        </span>
      )}
    </form>
  );
}
