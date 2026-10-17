import { Panel } from "@/components/ui/Panel";
import { FIGURES } from "@/lib/tidewell";
import { SourceChip } from "./SourceChip";

export function StatCard() {
  const { arr, growth12, growth2, burn6, runway } = FIGURES;
  return (
    <Panel title="Annual recurring revenue" bodyClassName="flex flex-col justify-between gap-5 p-4">
      <div className="flex flex-col gap-2">
        <span className="display text-[clamp(48px,5.4vw,80px)] tabular-nums">{arr.display}</span>
        <SourceChip figure={arr} />
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 border-t border-line pt-3">
        {[growth12, growth2, burn6, runway].map((f) => (
          <div key={f.id} className="flex flex-col gap-0.5">
            <dt className="text-[11px] leading-tight text-ink-2">{f.label}</dt>
            <dd className="flex items-baseline gap-1.5 font-display text-[22px] tracking-[-0.04em] tabular-nums">
              {f.display}
              {f.kind === "pack_summary" && <span className="font-sans text-[10px] tracking-normal text-dim">summary</span>}
            </dd>
          </div>
        ))}
      </dl>
    </Panel>
  );
}
