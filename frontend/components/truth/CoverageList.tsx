import { Check } from "lucide-react";
import type { CoverageItem } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Step 04: what the source of truth supports, and what would unlock the rest. */
export function CoverageList({ items }: { items: CoverageItem[] }) {
  if (!items.length) {
    return <p className="text-[12.5px] text-ink-2">Coverage appears once a table is mapped.</p>;
  }
  const groups = new Map<string, CoverageItem[]>();
  for (const it of items) groups.set(it.group, [...(groups.get(it.group) ?? []), it]);
  const available = items.filter((i) => i.available).length;

  return (
    <div className="flex flex-col gap-4">
      <p className="text-[12.5px] text-ink-2">
        <span className="font-display text-[22px] tracking-[-0.04em] text-ink tabular-nums">
          {available}/{items.length}
        </span>{" "}
        metrics can be computed from this source of truth.
      </p>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {[...groups.entries()].map(([group, rows]) => (
          <section key={group} className="rounded-[4px] border border-line p-3">
            <h4 className="label pb-2">{group}</h4>
            <ul className="flex flex-col gap-1.5">
              {rows.map((r) => (
                <li key={r.metric_id} className="flex items-start gap-2 text-[12.5px]">
                  <span
                    className={cn(
                      "mt-[3px] flex size-3.5 shrink-0 items-center justify-center rounded-[4px] border",
                      r.available ? "border-ink bg-ink text-bg" : "border-dashed border-line-strong",
                    )}
                    aria-hidden
                  >
                    {r.available && <Check className="size-2.5" strokeWidth={3} />}
                  </span>
                  <span className="min-w-0">
                    <span className={r.available ? "text-ink" : "text-ink-2"}>{r.label}</span>
                    {r.available && r.source_kind === "pack_summary" && <span className="ml-1.5 text-[10px] text-dim">summary</span>}
                    {r.available && r.kind && r.kind !== "historical" && <span className="ml-1.5 text-[10px] text-dim">{r.kind.replace("_", " ")}</span>}
                    {!r.available && (
                      <span className="block text-[11px] leading-snug text-dim">
                        {r.needs.length ? `Needs: ${r.needs.join(", ").replace(/_/g, " ")}` : r.reason}
                      </span>
                    )}
                    <span className="sr-only">{r.available ? "available" : "not available"}</span>
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
