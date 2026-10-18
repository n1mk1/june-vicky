import { ClaimChip } from "@/components/prep/ClaimChip";
import { Panel } from "@/components/ui/Panel";
import type { ClaimStatus, JudgedScore, KbCheck, LedgerRow } from "@/lib/types";
import { cn } from "@/lib/utils";
import { KbChip, byVerdict } from "./KbChip";

const STATUSES: ClaimStatus[] = ["matches", "contradicts", "unsupported", "forecast_as_fact"];

interface ScorePanelProps {
  /** Every claim so far: the deck's pre-scan and what was said, each checked by code. */
  ledger: LedgerRow[];
  /** Every statement checked against the knowledge base: the deck's and what was said. */
  kb: KbCheck[];
  /** The judge's scores of each answer (live interrupts and the Q&A). */
  scores: JudgedScore[];
  /** Seconds spent presenting, per slide (index 0 = slide 1); one entry when there are no slides. */
  slideSeconds: number[];
  fillers: number | null;
  /** The slide on screen (0-based), so its bar is marked. */
  current?: number;
}

const mean = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);
const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;

/** Scoring & metrics for a pitch run: live as the run goes; "–" until there's something to show. */
export function ScorePanel({ ledger, kb, scores, slideSeconds, fillers, current }: ScorePanelProps) {
  const dim = (k: keyof JudgedScore["dims"]) =>
    mean(scores.map((s) => s.dims[k]).filter((v): v is number => typeof v === "number"));
  const accuracy = mean(scores.map((s) => s.accuracy).filter((v): v is number => typeof v === "number"));
  const dims = [
    { label: "Accuracy", value: accuracy === null ? null : accuracy * 5, shown: accuracy === null ? null : `${Math.round(accuracy * 100)}%` },
    ...(["evidence", "clarity", "composure", "investor_fit"] as const).map((k) => {
      const v = dim(k);
      return { label: k === "investor_fit" ? "Investor fit" : k[0].toUpperCase() + k.slice(1), value: v, shown: v === null ? null : v.toFixed(1) };
    }),
  ];
  const four = dims.slice(1).map((d) => d.value).filter((v): v is number => v !== null);
  const overall = mean(four);
  const counts = Object.fromEntries(STATUSES.map((s) => [s, ledger.filter((r) => r.status === s).length])) as Record<ClaimStatus, number>;
  const talk = slideSeconds.reduce((a, b) => a + b, 0);
  const worst = slideSeconds.length > 1 ? slideSeconds.indexOf(Math.max(...slideSeconds)) : -1;
  const peak = Math.max(1, ...slideSeconds);
  const recent = [...ledger].reverse().slice(0, 8);

  return (
    <Panel title="Scoring & metrics" marks bodyClassName="scroll-thin flex flex-col gap-6 overflow-y-auto p-4" scrollLabel="Scoring and metrics">
      <div className="flex items-end justify-between gap-3">
        <div>
          <span className={cn("display text-[clamp(64px,6vw,96px)] tabular-nums", overall === null && "text-dim")}>
            {overall === null ? "–" : overall.toFixed(1)}
          </span>
          <span className="ml-1 text-[13px] text-ink-2">/ 5</span>
        </div>
        <span className="pb-3 text-right text-[11.5px] leading-tight text-ink-2">
          Overall, this run.
          <br />
          {scores.length ? `${scores.length} answer${scores.length === 1 ? "" : "s"} scored.` : "Scores arrive as you answer."}
        </span>
      </div>

      <dl className="flex flex-col gap-3">
        {dims.map((d) => (
          <div key={d.label} className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1">
            <dt className="text-[12.5px]">{d.label}</dt>
            <dd className="font-mono text-[11px] tabular-nums text-ink-2">{d.shown ?? "–"}</dd>
            <dd className="col-span-2 h-[3px] overflow-hidden rounded-full bg-line">
              {d.value !== null && <span className="block h-full rounded-full bg-ink transition-[width] duration-700" style={{ width: `${(d.value / 5) * 100}%` }} />}
            </dd>
          </div>
        ))}
      </dl>

      <section className="flex flex-col gap-2.5 border-t border-line pt-4">
        <h3 className="label">Claims ledger</h3>
        <ul className="grid grid-cols-2 gap-2">
          {STATUSES.map((status) => (
            <li key={status} className="flex flex-col items-start gap-1.5 rounded-[3px] border border-line px-2.5 py-2">
              <ClaimChip status={status} />
              <span className={cn("font-display text-[20px] tracking-[-0.04em] tabular-nums", !counts[status] && "text-dim")}>
                {ledger.length ? counts[status] : "–"}
              </span>
            </li>
          ))}
        </ul>
        {recent.length > 0 && (
          <ol className="flex flex-col gap-2 pt-1" aria-label="Latest claims">
            {recent.map((r) => (
              <li key={r.id} className="flex flex-col gap-1 border-l border-line pl-2.5">
                <span className="flex items-center gap-2">
                  <ClaimChip status={r.status} />
                  <span className="font-mono text-[10px] text-dim">
                    {r.source === "deck" ? "Deck" : "Said"}
                    {r.slide ? ` · slide ${r.slide}` : ""}
                  </span>
                </span>
                <span className="text-[12px] leading-snug">“{r.text}”</span>
                {r.truth && r.status !== "matches" && (
                  <span className="text-[11.5px] leading-snug text-ink-2">
                    Data says {r.truth_label ? `${r.truth_label.toLowerCase()}: ` : ""}
                    {r.truth}
                  </span>
                )}
              </li>
            ))}
          </ol>
        )}
      </section>

      <section className="flex flex-col gap-2.5 border-t border-line pt-4" data-testid="kb-ledger">
        <h3 className="label">Against your notes</h3>
        {kb.length === 0 ? (
          <p className="text-[12px] text-dim">
            Statements on your slides and in what you say are checked against your knowledge base as you go.
          </p>
        ) : (
          <>
            <ul className="grid grid-cols-2 gap-2">
              {(["contradicted", "new", "supported", "unclear"] as const).map((v) => (
                <li key={v} className="flex flex-col items-start gap-1.5 rounded-[3px] border border-line px-2.5 py-2">
                  <KbChip verdict={v} />
                  <span className={cn("font-display text-[20px] tracking-[-0.04em] tabular-nums", !kb.some((k) => k.verdict === v) && "text-dim")}>
                    {kb.filter((k) => k.verdict === v).length}
                  </span>
                </li>
              ))}
            </ul>
            <ol className="flex flex-col gap-2 pt-1" aria-label="Statements checked against your notes">
              {byVerdict(kb)
                .filter((k) => k.verdict !== "supported")
                .slice(0, 8)
                .map((k) => (
                  <li key={k.id} className="flex flex-col gap-1 border-l border-line pl-2.5">
                    <span className="flex items-center gap-2">
                      <KbChip verdict={k.verdict} />
                      <span className="font-mono text-[10px] text-dim">
                        {k.source === "deck" ? "Deck" : "Said"}
                        {k.slide ? ` · slide ${k.slide}` : ""}
                      </span>
                    </span>
                    <span className="text-[12px] leading-snug">“{k.text}”</span>
                    {k.quote ? (
                      <span className="text-[11.5px] leading-snug text-ink-2">
                        Your notes: “{k.quote}”{k.path && <span className="text-dim"> · {k.path}</span>}
                      </span>
                    ) : (
                      k.why && <span className="text-[11.5px] leading-snug text-ink-2">{k.why}</span>
                    )}
                  </li>
                ))}
            </ol>
            {kb.some((k) => k.verdict === "contradicted" || k.verdict === "new") && (
              <p className="text-[11.5px] text-ink-2">The panel will ask you to explain each of these: a claim can be newer than your notes.</p>
            )}
          </>
        )}
      </section>

      <section className="flex flex-col gap-2.5 border-t border-line pt-4">
        <h3 className="label">Delivery</h3>
        <dl className="grid grid-cols-2 gap-3">
          <div>
            <dt className="text-[11px] text-ink-2">Talk time</dt>
            <dd className={cn("font-display text-[24px] tracking-[-0.04em] tabular-nums", !talk && "text-dim")}>{talk ? clock(talk) : "–"}</dd>
          </div>
          <div>
            <dt className="text-[11px] text-ink-2">Filler words</dt>
            <dd className={cn("font-display text-[24px] tracking-[-0.04em] tabular-nums", fillers === null && "text-dim")}>{fillers ?? "–"}</dd>
          </div>
        </dl>
        {slideSeconds.length > 1 && (
          <div className="flex h-16 items-end gap-1.5" role="img" aria-label={`Seconds per slide: ${slideSeconds.map((s, i) => `${i + 1}: ${Math.round(s)}`).join(", ")}`}>
            {slideSeconds.map((s, i) => (
              <span key={i} className="flex h-full flex-1 flex-col items-center justify-end gap-1">
                <span
                  className={cn("w-full rounded-t-[3px] transition-[height] duration-500", i === worst ? "bg-ember" : i === current ? "bg-ink" : "bg-line-strong")}
                  style={{ height: `${Math.max(4, (s / peak) * 100)}%` }}
                  title={`Slide ${i + 1}: ${Math.round(s)} s`}
                />
                <span className={cn("text-[9.5px] tabular-nums", i === current ? "text-ink" : "text-dim")}>{i + 1}</span>
              </span>
            ))}
          </div>
        )}
      </section>
    </Panel>
  );
}
