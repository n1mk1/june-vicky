"use client";

import { ArrowUp, Paperclip } from "lucide-react";
import { useId, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

interface PromptBarProps {
  placeholder: string;
  label: string;
  onSubmit: (text: string) => void;
  /** Replaces the attach button on the left, e.g. a microphone. */
  leading?: ReactNode;
  hint?: ReactNode;
  className?: string;
}

/** Glass input bar with a tool button on the left and send on the right, as in the wireframe. */
export function PromptBar({ placeholder, label, onSubmit, leading, hint, className }: PromptBarProps) {
  const [value, setValue] = useState("");
  const id = useId();

  return (
    <form
      className={cn("glass relative rounded-[18px] p-2", className)}
      onSubmit={(e) => {
        e.preventDefault();
        const text = value.trim();
        if (!text) return;
        onSubmit(text);
        setValue("");
      }}
    >
      <div className="flex items-center gap-2 rounded-[12px] border border-line bg-surface-solid/60 p-1.5">
        {leading ?? (
          <button
            type="button"
            className="flex size-8 shrink-0 items-center justify-center rounded-[9px] border border-line text-ink-2 transition-colors hover:border-line-strong hover:text-ink"
            aria-label="Attach a file"
          >
            <Paperclip className="size-4" strokeWidth={1.5} />
          </button>
        )}
        <label htmlFor={id} className="sr-only">
          {label}
        </label>
        <input
          id={id}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={placeholder}
          autoComplete="off"
          className="h-8 min-w-0 flex-1 bg-transparent px-1 text-[14px] text-ink placeholder:text-dim focus:outline-none"
        />
        <button
          type="submit"
          disabled={!value.trim()}
          className="flex size-8 shrink-0 items-center justify-center rounded-[9px] bg-invert-bg text-invert-ink transition-opacity disabled:opacity-35"
          aria-label="Send"
        >
          <ArrowUp className="size-4" strokeWidth={1.75} />
        </button>
      </div>
      {hint && <p className="px-2 pt-2 text-[11.5px] text-dim">{hint}</p>}
    </form>
  );
}
