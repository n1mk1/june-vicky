import { cn } from "@/lib/utils";

/** Glyph ids used by the built-in Areopagus personas (`glyph:` in each YAML), plus the chair and a fallback. */
export type Glyph =
  | "squares"
  | "orbit"
  | "slash"
  | "stack"
  | "wave"
  | "ring"
  | "spark"
  | "grid"
  | "prism"
  | "cross"
  | "vicky"
  | "custom"
  | (string & {});

function Shape({ glyph }: { glyph: Glyph }) {
  switch (glyph) {
    case "squares":
      return (
        <>
          <rect x="7" y="7" width="14" height="14" rx="1" />
          <rect x="10.5" y="10.5" width="7" height="7" rx="0.5" />
        </>
      );
    case "orbit":
      return (
        <>
          <circle cx="14" cy="14" r="6.5" />
          <path d="M5 19 23 9" />
        </>
      );
    case "slash":
      return (
        <>
          <path d="M8 21 14 7l6 14" />
          <path d="M17.5 12.5 21 10" />
        </>
      );
    case "stack":
      return (
        <>
          <path d="M7 10h14M7 14h14M7 18h14" />
          <path d="M7 10v8M21 10v8" strokeOpacity="0.5" />
        </>
      );
    case "wave":
      return <path d="M6 15c2-4 4-4 6 0s4 4 6 0 3-3 4-1" />;
    case "ring":
      return (
        <>
          <circle cx="14" cy="14" r="7" />
          <circle cx="14" cy="14" r="3" />
        </>
      );
    case "spark":
      return <path d="M14 6v16M6 14h16M8.5 8.5l11 11M19.5 8.5l-11 11" strokeOpacity="0.9" />;
    case "grid":
      return (
        <>
          <path d="M7 11.5h14M7 16.5h14M11.5 7v14M16.5 7v14" />
        </>
      );
    case "prism":
      return (
        <>
          <path d="M14 6.5 21.5 20h-15z" />
          <path d="M14 6.5V20" strokeOpacity="0.5" />
        </>
      );
    case "cross":
      return <path d="M9 9l10 10M19 9 9 19" />;
    case "vicky":
      return (
        <>
          <path d="M8 8.5 14 20.5 20 8.5" />
          <path d="M11 8.5h-3M20 8.5h-3" strokeOpacity="0.5" />
        </>
      );
    default:
      return (
        <>
          <circle cx="14" cy="14" r="2" fill="currentColor" />
          <circle cx="14" cy="14" r="6.5" strokeDasharray="2 2.4" />
        </>
      );
  }
}

/** Monochrome geometric avatar for each investor persona. */
export function VcGlyph({ glyph, className }: { glyph: Glyph; className?: string }) {
  return (
    <svg viewBox="0 0 28 28" className={cn("size-7 shrink-0", className)} fill="none" stroke="currentColor" aria-hidden>
      <rect x="0.5" y="0.5" width="27" height="27" rx="8" strokeOpacity="0.35" />
      <Shape glyph={glyph} />
    </svg>
  );
}
