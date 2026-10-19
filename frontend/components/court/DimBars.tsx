import { cn } from "@/lib/utils";

export interface Dim {
  label: string;
  value: number | null;
  /** Scale top: 5 for judge dimensions (default), 1 for accuracy (shown as a percentage). */
  max?: number;
}

function dimText(d: Dim): string {
  if (d.value === null) return "–";
  if (d.max === 1) return `${Math.round(d.value * 100)}%`;
  return Number.isInteger(d.value) ? String(d.value) : d.value.toFixed(1);
}

/** The judge's scores as thin bars, one per dimension; anything under half the scale is ember. */
export function DimBars({ dims }: { dims: Dim[] }) {
  return (
    <dl className="grid grid-cols-3 gap-2 sm:grid-cols-5">
      {dims.map((d) => {
        const max = d.max ?? 5;
        const frac = d.value === null ? 0 : Math.max(0, Math.min(max, d.value)) / max;
        return (
          <div key={d.label} className="flex flex-col gap-1">
            <dt className="truncate text-[10.5px] text-ink-2">{d.label}</dt>
            <dd className="flex items-center gap-1.5">
              <span className="relative h-[3px] flex-1 overflow-hidden rounded-full bg-line">
                {d.value !== null && (
                  <span
                    className={cn("absolute inset-y-0 left-0 rounded-full", frac < 0.5 ? "bg-ember" : "bg-ink")}
                    style={{ width: `${frac * 100}%` }}
                  />
                )}
              </span>
              <span className="w-8 text-right font-mono text-[10px] tabular-nums text-ink-2">{dimText(d)}</span>
            </dd>
          </div>
        );
      })}
    </dl>
  );
}
