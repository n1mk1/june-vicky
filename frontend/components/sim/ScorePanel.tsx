import { Panel } from "@/components/ui/Panel";
import { ClaimChip } from "@/components/prep/ClaimChip";
import { DECK, SIM_SCORES, type ClaimStatus } from "@/lib/panel";
import { cn } from "@/lib/utils";

export function ScorePanel() {
  const { overall, dims, ledger, talkTime, fillers, slideSeconds } = SIM_SCORES;
  const maxSec = Math.max(...slideSeconds);
  return (
    <Panel title="Scoring & metrics" marks bodyClassName="scroll-thin flex flex-col gap-6 overflow-y-auto p-4">
      <div className="flex items-end justify-between gap-3">
        <div>
          <span className="display text-[clamp(64px,6vw,96px)] tabular-nums">{overall.toFixed(1)}</span>
          <span className="ml-1 text-[13px] text-ink-2">/ 5</span>
        </div>
        <span className="pb-3 text-right text-[11.5px] leading-tight text-ink-2">
          Overall, this run.
          <br />
          Sample session.
        </span>
      </div>

      <dl className="flex flex-col gap-3">
        {dims.map((d) => (
          <div key={d.label} className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1">
            <dt className="text-[12.5px]">{d.label}</dt>
            <dd className="font-mono text-[11px] tabular-nums text-ink-2">{d.value?.toFixed(1)}</dd>
            <dd className="col-span-2 h-[3px] overflow-hidden rounded-full bg-line">
              <span
                className={cn("block h-full rounded-full", (d.value ?? 0) < 2.5 ? "bg-ember" : "bg-ink")}
                style={{ width: `${((d.value ?? 0) / 5) * 100}%` }}
              />
            </dd>
          </div>
        ))}
      </dl>

      <section className="flex flex-col gap-2.5 border-t border-line pt-4">
        <h3 className="label">Claims ledger</h3>
        <ul className="grid grid-cols-2 gap-2">
          {(Object.entries(ledger) as [ClaimStatus, number][]).map(([status, n]) => (
            <li key={status} className="flex flex-col items-start gap-1.5 rounded-[10px] border border-line px-2.5 py-2">
              <ClaimChip status={status} />
              <span className="font-display text-[20px] tracking-[-0.04em] tabular-nums">{n}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="flex flex-col gap-2.5 border-t border-line pt-4">
        <h3 className="label">Delivery</h3>
        <dl className="grid grid-cols-2 gap-3">
          <div>
            <dt className="text-[11px] text-ink-2">Talk time</dt>
            <dd className="font-display text-[24px] tracking-[-0.04em] tabular-nums">{talkTime}</dd>
          </div>
          <div>
            <dt className="text-[11px] text-ink-2">Filler words</dt>
            <dd className="font-display text-[24px] tracking-[-0.04em] tabular-nums">{fillers}</dd>
          </div>
        </dl>
        <div className="flex h-16 items-end gap-1.5" role="img" aria-label={`Seconds per slide: ${slideSeconds.join(", ")}`}>
          {slideSeconds.map((s, i) => (
            <span key={i} className="flex flex-1 flex-col items-center gap-1">
              <span className={cn("w-full rounded-t-[3px]", i === 1 ? "bg-ember" : "bg-ink/70")} style={{ height: `${(s / maxSec) * 44}px` }} />
              <span className="text-[9.5px] tabular-nums text-dim" title={DECK[i]?.title}>
                {i + 1}
              </span>
            </span>
          ))}
        </div>
      </section>
    </Panel>
  );
}
