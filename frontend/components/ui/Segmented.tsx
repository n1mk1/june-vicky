"use client";

import { cn } from "@/lib/utils";

interface SegmentedProps<T extends string> {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  disabled?: boolean;
  className?: string;
}

/** Small radio pill group (Coached · Realistic, Slides · Feedback). */
export function Segmented<T extends string>({ label, value, options, onChange, disabled, className }: SegmentedProps<T>) {
  return (
    <div role="radiogroup" aria-label={label} className={cn("flex shrink-0 rounded-full border border-line p-[2px]", className)}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          disabled={disabled}
          onClick={() => onChange(o.value)}
          className={cn(
            "rounded-full px-2.5 py-0.5 text-[11.5px] transition-colors disabled:opacity-50",
            value === o.value ? "bg-invert-bg text-invert-ink" : "text-ink-2 hover:text-ink",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
