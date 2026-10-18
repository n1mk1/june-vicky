import type { KnowledgeVerdict } from "@/lib/types";
import { cn } from "@/lib/utils";

export const KNOWLEDGE_LABEL: Record<KnowledgeVerdict, string> = {
  knows: "Knew it",
  partial: "Partly",
  contradicts: "Contradicts notes",
  missed: "Missed",
  unverified: "Not checked",
};

// Same language as ClaimChip: only a contradiction is filled; a miss is outlined in ember.
const STYLE: Record<KnowledgeVerdict, string> = {
  contradicts: "border-ember bg-ember text-invert-ink",
  missed: "border-ember text-ember",
  partial: "border-dashed border-line-strong text-ink-2",
  unverified: "border-dashed border-line text-dim",
  knows: "border-line-strong text-ink",
};

/** Vicky's verdict on a knowledge answer, checked against the founder's own notes. */
export function KnowledgeChip({ verdict, className }: { verdict: KnowledgeVerdict; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center rounded-[3px] border px-2 font-mono text-[9.5px] uppercase tracking-[-0.04em] whitespace-nowrap",
        STYLE[verdict] ?? STYLE.unverified,
        className,
      )}
    >
      {KNOWLEDGE_LABEL[verdict] ?? verdict}
    </span>
  );
}
