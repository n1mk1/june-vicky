import { Panel } from "@/components/ui/Panel";
import type { Widget } from "@/lib/types";
import { Explainable } from "./Explain";
import { kpiBadge, kpiExplain } from "./kpi";
import { SourceChip } from "./SourceChip";

/** Big number with its source chip, plus a 2×2 of secondaries; every value explains itself on click. */
export function KpiWidget({ widget, currency }: { widget: Widget; currency?: string }) {
  const kpi = widget.evaluated.kpi;
  if (!kpi) return null;
  const { primary, secondary } = kpi;
  const badge = kpiBadge(primary);

  return (
    <Panel title={widget.spec.title} bodyClassName="scroll-thin flex flex-col justify-between gap-2 overflow-y-auto p-3.5">
      <div className="flex flex-col items-start gap-2">
        {primary.missing ? (
          <p className="text-[12.5px] text-ink-2">{primary.missing.reason}</p>
        ) : (
          <>
            <span className="flex items-baseline gap-2">
              <Explainable x={kpiExplain(primary, currency)} triggerClassName="display text-[clamp(32px,min(5.4vw,6.5vh),80px)] tabular-nums">
                {primary.display}
              </Explainable>
              {badge && <span className="text-[10px] text-dim">{badge}</span>}
            </span>
            <SourceChip x={kpiExplain(primary, currency)} />
          </>
        )}
      </div>
      {secondary.length > 0 && (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 border-t border-line pt-2.5">
          {secondary.map((k, i) => {
            const b = kpiBadge(k);
            return (
              <div key={`${k.id}-${i}`} className="flex min-w-0 flex-col gap-0.5">
                <dt className="text-[11px] leading-tight text-ink-2">{k.label}</dt>
                <dd className="flex items-baseline gap-1.5 font-display text-[clamp(16px,2.6vh,20px)] tracking-[-0.04em] tabular-nums">
                  {k.missing || k.value === null ? (
                    <span
                      className="rounded-full border border-dashed border-line-strong px-2 py-0.5 font-sans text-[10.5px] tracking-normal text-dim"
                      title={k.missing?.reason}
                    >
                      {k.missing?.needs?.length ? `Needs ${k.missing.needs.join(", ").replace(/_/g, " ")}` : "Not available"}
                    </span>
                  ) : (
                    <>
                      <Explainable x={kpiExplain(k, currency)} align={i % 2 ? "right" : "left"}>
                        {k.display}
                      </Explainable>
                      {b && <span className="font-sans text-[10px] tracking-normal text-dim">{b}</span>}
                    </>
                  )}
                </dd>
              </div>
            );
          })}
        </dl>
      )}
    </Panel>
  );
}
