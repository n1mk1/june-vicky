import Link from "next/link";
import { confirmHref } from "@/lib/kb";
import type { Widget } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Dashed tile for a metric the data can't support yet; names the upload that unlocks it. */
export function MissingTile({ widget, engagementId, className }: { widget: Widget; engagementId?: string; className?: string }) {
  const ev = widget.evaluated;
  const missing = ev.missing ?? ev.kpi?.primary.missing ?? ev.missing_series[0] ?? null;
  const error = widget.status === "error";
  return (
    <section
      className={cn(
        "relative flex min-h-[160px] flex-col justify-between gap-3 rounded-[4px] border border-dashed p-4",
        error ? "border-ember/60" : "border-line-strong",
        className,
      )}
    >
      <div className="flex flex-col gap-1.5">
        <h2 className="label">{widget.spec.title}</h2>
        <p className="text-[13px] leading-snug text-ink-2">
          {error ? (ev.error ?? "This widget couldn't be computed.") : (missing?.reason ?? "Not enough data for this metric yet.")}
        </p>
        {!error && !!missing?.needs?.length && (
          <p className="font-mono text-[10px] uppercase tracking-[-0.04em] text-dim">Needs: {missing.needs.join(", ").replace(/_/g, " ")}</p>
        )}
      </div>
      {!error && (
        <Link
          href={engagementId ? confirmHref(engagementId, 2) : "/knowledge"}
          className="self-start text-[12px] text-ink underline underline-offset-2 hover:text-ember"
        >
          Upload
        </Link>
      )}
    </section>
  );
}
