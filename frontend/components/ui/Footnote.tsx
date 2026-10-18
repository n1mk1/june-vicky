"use client";

import { useId, useState } from "react";
import { sourceLabel } from "@/lib/format";
import type { Citation } from "@/lib/types";
import { cn } from "@/lib/utils";

const SUP = ["⁰", "¹", "²", "³", "⁴", "⁵", "⁶", "⁷", "⁸", "⁹"];
const sup = (n: number) =>
  String(n)
    .split("")
    .map((d) => SUP[Number(d)] ?? d)
    .join("");

/** Superscript marker on a number in a message; hover or focus shows where the number comes from. */
export function Footnote({ citation, className }: { citation: Citation; className?: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span
      className={cn("relative inline-block align-super", className)}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        aria-describedby={open ? id : undefined}
        aria-label={`Source ${citation.marker}: ${citation.label}`}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={() => setOpen((v) => !v)}
        className="px-[1px] font-sans text-[0.62em] leading-none text-ember tabular-nums hover:underline"
      >
        {sup(citation.marker)}
      </button>
      {open && (
        <span
          id={id}
          role="tooltip"
          className="absolute bottom-full left-1/2 z-40 border border-line-strong bg-surface-solid/95 shadow-[0_12px_40px_-12px_rgba(0,0,0,0.45)] backdrop-blur-md mb-2 flex w-64 -translate-x-1/2 flex-col gap-1.5 rounded-[4px] p-3 text-left font-sans text-[12px] leading-snug tracking-normal text-ink-2 normal-case"
        >
          <span className="flex items-baseline justify-between gap-2">
            <span className="text-ink">{citation.label}</span>
            {citation.display && <span className="font-display text-[15px] tracking-[-0.03em] text-ink tabular-nums">{citation.display}</span>}
          </span>
          {citation.formula && <span>{citation.formula}</span>}
          <span className="font-mono text-[9.5px] uppercase tracking-[-0.04em] text-dim">{sourceLabel(citation.source)}</span>
          {citation.url && (
            <a href={citation.url} target="_blank" rel="noreferrer" className="text-[11.5px] text-ink underline underline-offset-2">
              Open source
            </a>
          )}
        </span>
      )}
    </span>
  );
}

/**
 * Text with footnotes. Citations with `start`/`end` offsets get their marker right after the cited
 * span; markers written inline as `[1]` or `¹` are replaced in place; anything left is appended at
 * the end so no figure goes unsourced.
 */
export function CitedText({ text, citations }: { text: string; citations: Citation[] }) {
  if (!citations?.length) return <>{text}</>;
  const used = new Set<number>();
  // 1. Offsets from the API (checked against the text so a stale offset never splits a word).
  const anchored = citations
    .filter((c) => typeof c.end === "number" && c.end! > 0 && c.end! <= text.length && (!c.text || text.slice(c.start ?? 0, c.end).includes(c.text)))
    .sort((a, b) => a.end! - b.end!);
  const parts: (string | { c: Citation })[] = [];
  let last = 0;
  for (const c of anchored) {
    if (c.end! < last) continue;
    parts.push(text.slice(last, c.end), { c });
    used.add(c.marker);
    last = c.end!;
  }
  // 2. Inline markers in the remaining text.
  const tail = text.slice(last);
  const byMarker = new Map(citations.filter((c) => !used.has(c.marker)).map((c) => [c.marker, c]));
  const re = /\[(\d{1,2})\]|([⁰¹²³⁴⁵⁶⁷⁸⁹]+)/g;
  let pos = 0;
  for (let m = re.exec(tail); m; m = re.exec(tail)) {
    const n = m[1] ? Number(m[1]) : Number(m[2].split("").map((ch) => SUP.indexOf(ch)).join(""));
    const c = byMarker.get(n);
    if (!c) continue;
    parts.push(tail.slice(pos, m.index).replace(/\s+$/, ""), { c });
    used.add(n);
    pos = m.index + m[0].length;
  }
  parts.push(tail.slice(pos));
  const rest = citations.filter((c) => !used.has(c.marker));
  return (
    <>
      {parts.map((p, i) => (typeof p === "string" ? <span key={i}>{p}</span> : <Footnote key={i} citation={p.c} />))}
      {rest.map((c) => (
        <Footnote key={`r${c.marker}`} citation={c} />
      ))}
    </>
  );
}
