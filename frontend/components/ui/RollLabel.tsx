import type { CSSProperties } from "react";

/** Label whose letters roll upward on hover of the nearest `.group` parent. */
export function RollLabel({ text }: { text: string }) {
  return (
    <span className="inline-flex">
      <span className="sr-only">{text}</span>
      <span aria-hidden className="inline-flex">
        {Array.from(text).map((ch, i) => (
          <span key={i} className="roll-char" style={{ "--i": i } as CSSProperties}>
            <span>{ch}</span>
            <span>{ch}</span>
          </span>
        ))}
      </span>
    </span>
  );
}
