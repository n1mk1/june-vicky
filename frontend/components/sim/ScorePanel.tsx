import { Panel } from "@/components/ui/Panel";
import { ClaimChip } from "@/components/prep/ClaimChip";
import { PREVIEW_DECK, PREVIEW_LEDGER } from "@/lib/preview";
import type { ClaimStatus } from "@/lib/types";

const DIMS = ["Accuracy", "Evidence", "Clarity", "Composure", "Investor fit"];

/** Scoring & metrics for a pitch run. Values stay at "–" until a run produces them. */
export function ScorePanel() {
  return (
    <Panel title="Scoring & metrics" marks bodyClassName="scroll-thin flex flex-col gap-6 overflow-y-auto p-4">
      <div className="flex items-end justify-between gap-3">
        <div>
          <span className="display text-[clamp(64px,6vw,96px)] tabular-nums text-dim">–</span>
          <span className="ml-1 text-[13px] text-ink-2">/ 5</span>
        </div>
        <span className="pb-3 text-right text-[11.5px] leading-tight text-ink-2">
          Overall, this run.
          <br />
          Scores arrive with the report.
        </span>
      </div>

      <dl className="flex flex-col gap-3">
        {DIMS.map((d) => (
          <div key={d} className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1">
            <dt className="text-[12.5px]">{d}</dt>
            <dd className="font-mono text-[11px] tabular-nums text-ink-2">–</dd>
            <dd className="col-span-2 h-[3px] overflow-hidden rounded-full bg-line" />
          </div>
        ))}
      </dl>

      <section className="flex flex-col gap-2.5 border-t border-line pt-4">
        <h3 className="label">Claims ledger</h3>
        <ul className="grid grid-cols-2 gap-2">
          {(Object.entries(PREVIEW_LEDGER) as [ClaimStatus, number | null][]).map(([status, n]) => (
            <li key={status} className="flex flex-col items-start gap-1.5 rounded-[3px] border border-line px-2.5 py-2">
              <ClaimChip status={status} />
              <span className="font-display text-[20px] tracking-[-0.04em] tabular-nums text-dim">{n ?? "–"}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="flex flex-col gap-2.5 border-t border-line pt-4">
        <h3 className="label">Delivery</h3>
        <dl className="grid grid-cols-2 gap-3">
          <div>
            <dt className="text-[11px] text-ink-2">Talk time</dt>
            <dd className="font-display text-[24px] tracking-[-0.04em] tabular-nums text-dim">–</dd>
          </div>
          <div>
            <dt className="text-[11px] text-ink-2">Filler words</dt>
            <dd className="font-display text-[24px] tracking-[-0.04em] tabular-nums text-dim">–</dd>
          </div>
        </dl>
        <div className="flex h-16 items-end gap-1.5" role="img" aria-label="Seconds per slide: no run yet">
          {PREVIEW_DECK.map((s) => (
            <span key={s.n} className="flex flex-1 flex-col items-center gap-1">
              <span className="h-1 w-full rounded-t-[3px] bg-line-strong" />
              <span className="text-[9.5px] tabular-nums text-dim" title={s.title}>
                {s.n}
              </span>
            </span>
          ))}
        </div>
      </section>
    </Panel>
  );
}
