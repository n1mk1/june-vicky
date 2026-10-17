import { CLAIM_LABEL, type ClaimStatus } from "@/lib/panel";
import { cn } from "@/lib/utils";

const STYLE: Record<ClaimStatus, string> = {
  contradicts: "border-ember bg-ember text-white",
  forecast_as_fact: "border-ember text-ember",
  unsupported: "border-dashed border-line-strong text-ink-2",
  matches: "border-line-strong text-ink",
};

/** Claim status shown by fill and outline; only contradictions are filled. */
export function ClaimChip({ status, className }: { status: ClaimStatus; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center rounded-full border px-2 font-mono text-[9.5px] uppercase tracking-[-0.04em] whitespace-nowrap",
        STYLE[status],
        className,
      )}
    >
      {CLAIM_LABEL[status]}
    </span>
  );
}
