import { cn } from "@/lib/utils";

/**
 * The VICKY mark: a V whose right arm is sliced on a diagonal, echoing the cut "E" in JUNE.
 * Polygons are in a 24×24 space and shared with the 3D extrusion.
 */
export const MARK_POLYS: [number, number][][] = [
  [
    [1, 2],
    [6, 2],
    [14.5, 22],
    [9.5, 22],
  ],
  [
    [18, 2],
    [23, 2],
    [20.9, 6.9],
    [16.1, 6.5],
  ],
  [
    [15.4, 8.1],
    [20.2, 8.6],
    [14.5, 22],
    [11.95, 16],
  ],
];

const toPath = (poly: [number, number][]) => `M${poly.map(([x, y]) => `${x} ${y}`).join("L")}Z`;

export function VickyMark({ className, outline }: { className?: string; outline?: boolean }) {
  return (
    <svg viewBox="0 0 24 24" className={cn("size-5", className)} aria-hidden>
      {MARK_POLYS.map((p, i) => (
        <path
          key={i}
          d={toPath(p)}
          fill={outline ? "none" : "currentColor"}
          stroke={outline ? "currentColor" : "none"}
          strokeWidth={outline ? 0.6 : 0}
          strokeLinejoin="round"
          pathLength={outline ? 1 : undefined}
          className={outline ? "[stroke-dasharray:1] [stroke-dashoffset:1] animate-[draw-stroke_1.1s_var(--ease-soft)_forwards]" : undefined}
          style={outline ? { animationDelay: `${i * 160}ms` } : undefined}
        />
      ))}
    </svg>
  );
}
