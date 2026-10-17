import { CLAIM_LABEL, type ClaimStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const STYLE: Record<ClaimStatus, string> = {
  contradicts: "border-ember bg-ember text-white",
  forecast_as_fact: "border-ember text-ember",
  unsupported: "border-dashed border-line-strong text-ink-2",
  matches: "border-line-strong text-ink",
};

/** Claim status shown by fill and outline; only contradictions are filled. */
export function ClaimChip({ status, className, title }: { status: ClaimStatus; className?: string; title?: string }) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex h-5 items-center rounded-full border px-2 font-mono text-[9.5px] uppercase tracking-[-0.04em] whitespace-nowrap",
        STYLE[status] ?? STYLE.unsupported,
        className,
      )}
    >
      {CLAIM_LABEL[status] ?? status}
    </span>
  );
}

const RANK: Record<ClaimStatus, number> = { contradicts: 3, forecast_as_fact: 2, unsupported: 1, matches: 0 };

/** The most serious status in a set of claims. */
export function worstStatus(statuses: ClaimStatus[]): ClaimStatus | null {
  return statuses.reduce<ClaimStatus | null>((w, s) => (w === null || (RANK[s] ?? 0) > (RANK[w] ?? 0) ? s : w), null);
}
