import type { KpiItem } from "@/lib/types";
import type { Explanation } from "./Explain";

/** Explain-card content for one KPI item from the evaluator. */
export function kpiExplain(k: KpiItem, currency?: string | null): Explanation {
  return {
    label: k.label,
    display: k.display,
    value: k.value,
    unit: k.unit,
    currency,
    period: k.period,
    formula: k.formula,
    inputs: k.inputs,
    source: k.source,
    kind: k.kind,
  };
}

/** "summary", "forecast", "you said": the badge for any non-historical number (UI doc §5). */
export function kpiBadge(k: Pick<KpiItem, "kind" | "source">): string | null {
  if (k.source?.kind === "pack_summary") return "summary";
  if (k.source?.kind === "founder_stated" || k.kind === "founder_claim") return "you said";
  if (k.kind && k.kind !== "historical") return k.kind.replace("_", " ");
  return null;
}
