import type { Glyph } from "@/lib/panel";
import { cn } from "@/lib/utils";

/** Monochrome geometric avatar for each investor persona. */
export function VcGlyph({ glyph, className }: { glyph: Glyph; className?: string }) {
  return (
    <svg viewBox="0 0 28 28" className={cn("size-7 shrink-0", className)} fill="none" stroke="currentColor" aria-hidden>
      <rect x="0.5" y="0.5" width="27" height="27" rx="8" strokeOpacity="0.35" />
      {glyph === "squares" && (
        <>
          <rect x="7" y="7" width="14" height="14" rx="1" />
          <rect x="10.5" y="10.5" width="7" height="7" rx="0.5" />
        </>
      )}
      {glyph === "orbit" && (
        <>
          <circle cx="14" cy="14" r="6.5" />
          <path d="M5 19 23 9" />
        </>
      )}
      {glyph === "slash" && (
        <>
          <path d="M8 21 14 7l6 14" />
          <path d="M17.5 12.5 21 10" />
        </>
      )}
      {glyph === "custom" && (
        <>
          <circle cx="14" cy="14" r="2" fill="currentColor" />
          <circle cx="14" cy="14" r="6.5" strokeDasharray="2 2.4" />
        </>
      )}
    </svg>
  );
}
