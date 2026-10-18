import { Info } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * What building the model left out or reinterpreted: a quarter with too few months, a currency with no
 * published rate for some periods, costs typed as negatives. The lines come from the metrics engine.
 * `compact` is the dashboard's: a chip that opens the list, so the one-screen layout keeps its height.
 */
export function ModelNotes({ notes, compact, className }: { notes?: string[]; compact?: boolean; className?: string }) {
  if (!notes?.length) return null;
  const list = (
    <ul className="flex flex-col gap-1.5">
      {notes.map((n) => (
        <li key={n} className="flex items-start gap-2 text-[12px] leading-snug text-ink-2">
          <span className="mt-[6px] size-1 shrink-0 rounded-full bg-ink-2" aria-hidden />
          <span>{n}</span>
        </li>
      ))}
    </ul>
  );
  const title = `${notes.length} data note${notes.length === 1 ? "" : "s"}`;

  if (compact) {
    return (
      <details className={cn("group relative", className)} data-testid="model-notes">
        <summary className="inline-flex h-7 cursor-pointer list-none items-center gap-1.5 rounded-[3px] border border-line px-2.5 text-[11.5px] text-ink-2 hover:text-ink [&::-webkit-details-marker]:hidden">
          <Info className="size-3.5" strokeWidth={1.75} aria-hidden />
          {title}
        </summary>
        <div className="absolute left-0 top-9 z-40 w-[min(420px,calc(100vw-32px))] rounded-[4px] border border-line bg-surface-solid p-3 shadow-lg">
          <p className="label pb-2">Left out of the figures</p>
          {list}
        </div>
      </details>
    );
  }

  return (
    <section className={cn("rounded-[4px] border border-line p-3", className)} aria-label="Data notes" data-testid="model-notes">
      <h4 className="label flex items-center gap-1.5 pb-2">
        <Info className="size-3" strokeWidth={1.75} aria-hidden />
        Left out of the figures
      </h4>
      {list}
    </section>
  );
}
