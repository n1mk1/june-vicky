import type { KbVerdict } from "@/lib/types";
import { cn } from "@/lib/utils";

export const KB_LABEL: Record<KbVerdict, string> = {
  contradicted: "Notes differ",
  new: "Not in notes",
  supported: "In notes",
  unclear: "Notes unclear",
};

const STYLE: Record<KbVerdict, string> = {
  contradicted: "border-ember bg-ember text-invert-ink",
  new: "border-dashed border-ember text-ember",
  supported: "border-line-strong text-ink",
  unclear: "border-dashed border-line-strong text-ink-2",
};

/** How a pitch statement stands against the founder's own knowledge base; only contradictions are filled. */
export function KbChip({ verdict, className, title }: { verdict: KbVerdict; className?: string; title?: string }) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex h-5 items-center rounded-[3px] border px-2 font-mono text-[9.5px] uppercase tracking-[-0.04em] whitespace-nowrap",
        STYLE[verdict] ?? STYLE.unclear,
        className,
      )}
    >
      {KB_LABEL[verdict] ?? verdict}
    </span>
  );
}

const RANK: Record<KbVerdict, number> = { contradicted: 3, new: 2, unclear: 1, supported: 0 };

/** The most serious verdicts first. */
export function byVerdict<T extends { verdict: KbVerdict }>(rows: T[]): T[] {
  return [...rows].sort((a, b) => (RANK[b.verdict] ?? 0) - (RANK[a.verdict] ?? 0));
}
