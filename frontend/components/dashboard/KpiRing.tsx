import { Panel } from "@/components/ui/Panel";
import { FIGURES } from "@/lib/tidewell";

const R_OUT = 70;
const R_IN = 56;
const C = (r: number) => 2 * Math.PI * r;

/** Two concentric rings: margin as booked, and margin once customer success is counted. */
export function KpiRing() {
  const booked = FIGURES.gmBooked;
  const withCs = FIGURES.gmWithCs;
  return (
    <Panel title="Gross margin" marks className="aspect-auto" bodyClassName="flex flex-col items-center justify-center gap-4 p-4">
      <div className="relative">
        <svg viewBox="0 0 160 160" className="size-[clamp(120px,15vw,168px)] -rotate-90" aria-hidden>
          <circle cx="80" cy="80" r={R_OUT} fill="none" stroke="var(--line)" strokeWidth="1" />
          <circle
            cx="80"
            cy="80"
            r={R_OUT}
            fill="none"
            stroke="var(--ink)"
            strokeWidth="1.5"
            strokeDasharray={`${C(R_OUT) * booked.value} ${C(R_OUT)}`}
            strokeLinecap="round"
          />
          <circle cx="80" cy="80" r={R_IN} fill="none" stroke="var(--line)" strokeWidth="1" />
          <circle
            cx="80"
            cy="80"
            r={R_IN}
            fill="none"
            stroke="var(--ember)"
            strokeWidth="1.5"
            strokeDasharray={`${C(R_IN) * withCs.value} ${C(R_IN)}`}
            strokeLinecap="round"
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="display text-[clamp(32px,3.6vw,48px)] tabular-nums">{booked.display}</span>
          <span className="text-[11px] text-ink-2">as booked</span>
        </div>
      </div>
      <dl className="grid w-full grid-cols-2 gap-x-3 text-[11.5px]">
        <div className="flex items-center gap-1.5">
          <span className="h-px w-3 bg-ink" aria-hidden />
          <dt className="text-ink-2">Booked</dt>
          <dd className="ml-auto tabular-nums">{booked.display}</dd>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="h-px w-3 bg-ember" aria-hidden />
          <dt className="text-ink-2">Incl. support</dt>
          <dd className="ml-auto tabular-nums">{withCs.display}</dd>
        </div>
      </dl>
    </Panel>
  );
}
