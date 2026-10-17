import { Panel } from "@/components/ui/Panel";
import type { KpiItem, Widget } from "@/lib/types";
import { Explainable } from "./Explain";
import { kpiExplain } from "./kpi";
import { SourceChip } from "./SourceChip";

const RADII = [70, 56, 42];
const C = (r: number) => 2 * Math.PI * r;
const STROKES = ["var(--ink)", "var(--ember)", "var(--ink-2)"];

/** Concentric rings, one per KPI (e.g. margin as booked in ink, incl. customer success in ember). */
export function GaugeRingWidget({ widget, currency }: { widget: Widget; currency?: string }) {
  const kpi = widget.evaluated.kpi;
  const items: KpiItem[] = kpi ? [kpi.primary, ...kpi.secondary].filter((k) => k.value !== null).slice(0, 3) : [];
  const lead = items[0];

  return (
    <Panel title={widget.spec.title} marks bodyClassName="flex flex-col items-center justify-center gap-4 p-4">
      <div className="relative">
        <svg viewBox="0 0 160 160" className="size-[clamp(120px,15vw,168px)] -rotate-90" aria-hidden>
          {items.map((k, i) => {
            const r = RADII[i];
            const frac = k.unit === "pct" ? Math.max(0, Math.min(1, k.value ?? 0)) : 0;
            return (
              <g key={k.id}>
                <circle cx="80" cy="80" r={r} fill="none" stroke="var(--line)" strokeWidth="1" />
                <circle
                  cx="80"
                  cy="80"
                  r={r}
                  fill="none"
                  stroke={STROKES[i]}
                  strokeWidth="1.5"
                  strokeDasharray={`${C(r) * frac} ${C(r)}`}
                  strokeLinecap="round"
                />
              </g>
            );
          })}
        </svg>
        {lead && (
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <Explainable x={kpiExplain(lead, currency)} triggerClassName="display text-[clamp(32px,3.6vw,48px)] tabular-nums">
              {lead.display}
            </Explainable>
            <span className="text-[11px] text-ink-2">{lead.label.toLowerCase()}</span>
          </div>
        )}
      </div>
      <dl className="grid w-full grid-cols-1 gap-x-3 gap-y-1.5 text-[11.5px] sm:grid-cols-2">
        {items.map((k, i) => (
          <div key={k.id} className="flex min-w-0 items-center gap-1.5">
            <span className="h-px w-3 shrink-0" style={{ background: STROKES[i] }} aria-hidden />
            <dt className="truncate text-ink-2">{k.label}</dt>
            <dd className="ml-auto tabular-nums">{k.display}</dd>
          </div>
        ))}
      </dl>
      {lead && <SourceChip x={kpiExplain(lead, currency)} className="self-start" />}
    </Panel>
  );
}
