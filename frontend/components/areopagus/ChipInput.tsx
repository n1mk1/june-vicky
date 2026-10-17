"use client";

import { X } from "lucide-react";
import { useState } from "react";
import { inputCls } from "@/components/ui/Field";
import { cn } from "@/lib/utils";

/** A list of short texts: type and press Enter to add, ✕ to remove. Duplicates and blanks are ignored. */
export function ChipInput({
  id,
  label,
  values,
  onChange,
  max,
  placeholder,
}: {
  id: string;
  label: string;
  values: string[];
  onChange: (v: string[]) => void;
  max: number;
  placeholder: string;
}) {
  const [draft, setDraft] = useState("");
  const full = values.length >= max;
  const add = () => {
    const t = draft.trim().slice(0, 300);
    if (t && !full && !values.includes(t)) onChange([...values, t]);
    setDraft("");
  };
  return (
    <div className="flex flex-col gap-2">
      {values.length > 0 && (
        <ul className="flex flex-col gap-1.5" aria-label={label}>
          {values.map((v) => (
            <li key={v} className="flex items-start gap-2 rounded-[10px] border border-line px-2.5 py-1.5 text-[12.5px] leading-snug text-ink">
              <span className="min-w-0 flex-1">{v}</span>
              <button
                type="button"
                onClick={() => onChange(values.filter((x) => x !== v))}
                aria-label={`Remove “${v}”`}
                className="-mr-1 flex size-5 shrink-0 items-center justify-center rounded-full text-ink-2 hover:text-ink"
              >
                <X className="size-3" strokeWidth={1.5} />
              </button>
            </li>
          ))}
        </ul>
      )}
      <input
        id={id}
        value={draft}
        disabled={full}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            add();
          }
        }}
        onBlur={add}
        placeholder={full ? `${max} is the most` : placeholder}
        className={cn(inputCls)}
      />
    </div>
  );
}
