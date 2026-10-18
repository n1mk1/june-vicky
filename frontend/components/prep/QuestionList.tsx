"use client";

import { Repeat, Target } from "lucide-react";
import { useState } from "react";
import { Panel } from "@/components/ui/Panel";
import type { Carried, ClaimStatus, DrillMark, KnowledgeVerdict } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ClaimChip } from "./ClaimChip";
import { KnowledgeChip } from "./KnowledgeChip";

const CARRIED_STATUS: Record<Carried["status"], string> = {
  asked: "Asked",
  queued: "Coming up",
  not_reached: "Not reached",
  unmatched: "Not in this data",
};

export interface QA {
  id: string;
  vc: string;
  question: string;
  answer: string | null;
  /** Judge score out of 5, or null when hidden (Realistic mode) or not scored yet. */
  score: number | null;
  status: ClaimStatus | null;
  /** Set on a knowledge check: Vicky's verdict once answered (null while waiting). */
  knowledge?: KnowledgeVerdict | null;
  /** Set when this question came back from a drill the founder marked last session. */
  drill?: DrillMark;
}

export interface DrillPick {
  seq: number;
  mark: DrillMark;
}

/** Questions asked so far; mark the ones to repeat or study, then drill them: the marks are saved and a new
 * session starts with those topics. What came back from last time is listed at the top. */
export function QuestionList({
  items,
  empty,
  carried,
  onDrill,
  drilling,
  endsSession,
}: {
  items: QA[];
  empty?: string;
  carried?: Carried[];
  onDrill?: (picks: DrillPick[]) => void;
  drilling?: boolean;
  /** The session is still live: drilling ends it first (its report is kept). */
  endsSession?: boolean;
}) {
  const [marks, setMarks] = useState<Record<string, DrillMark | undefined>>({});
  const picks: DrillPick[] = items.flatMap((q) => (marks[q.id] ? [{ seq: Number(q.id), mark: marks[q.id]! }] : []));
  const picked = picks.length;
  const drills = carried?.filter((c) => c.kind === "drill") ?? [];
  const weakSpots = carried?.filter((c) => c.kind === "weakness").length ?? 0;

  const toggle = (id: string, m: DrillMark) => setMarks((s) => ({ ...s, [id]: s[id] === m ? undefined : m }));

  return (
    <Panel title="Questions & answers" aside={<span className="label">{items.length}</span>} bodyClassName="flex min-h-0 flex-col">
      {(drills.length > 0 || weakSpots > 0) && (
        <div className="border-b border-line px-4 py-3" data-testid="carried">
          {drills.length > 0 && (
            <>
              <p className="label">
                Drilled from last session · {drills.filter((d) => d.status === "asked").length} of {drills.length} asked
              </p>
              <ul className="flex flex-col gap-1 pt-1.5">
                {drills.map((d) => (
                  <li key={d.memory_id} className="flex items-baseline justify-between gap-2 text-[12px]">
                    <span className="line-clamp-1 text-ink-2" title={d.question ?? undefined}>
                      {d.mark === "study" ? "Study" : "Repeat"}: {d.topic ?? d.question}
                    </span>
                    <span className={cn("shrink-0 text-[11px]", d.status === "asked" ? "text-ink" : "text-dim")}>
                      {CARRIED_STATUS[d.status]}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}
          {weakSpots > 0 && (
            <p className={cn("text-[11.5px] text-ink-2", drills.length > 0 && "pt-2")}>
              The panel also presses {weakSpots} weak spot{weakSpots === 1 ? "" : "s"} from your last report{weakSpots === 1 ? "" : "s"}.
            </p>
          )}
        </div>
      )}
      <ol className="scroll-thin min-h-0 flex-1 divide-y divide-line overflow-y-auto">
        {items.length === 0 && <li className="px-4 py-4 text-[12.5px] text-ink-2">{empty ?? "Questions appear here as the panel asks them."}</li>}
        {items.map((q) => {
          const mark = marks[q.id];
          return (
            <li key={q.id} className={cn("flex flex-col gap-2 px-4 py-3.5 transition-colors", mark && "bg-surface-solid/50")}>
              <div className="flex items-start justify-between gap-2">
                <span className="text-[11px] text-ink-2">
                  {q.vc}
                  {q.knowledge !== undefined && " · knowledge check"}
                  {q.drill && ` · drilled (${q.drill})`}
                </span>
                {q.answer === null ? (
                  <span className="text-[11px] text-dim">Waiting for you</span>
                ) : q.knowledge ? (
                  <KnowledgeChip verdict={q.knowledge} />
                ) : q.status ? (
                  <ClaimChip status={q.status} />
                ) : (
                  <span className="text-[11px] text-dim">No figures claimed</span>
                )}
              </div>
              <p className="line-clamp-4 font-display text-[16px] leading-tight tracking-[-0.03em]">{q.question}</p>
              {q.answer !== null && <p className="line-clamp-3 text-[12.5px] text-ink-2">{q.answer}</p>}
              <div className="flex items-center justify-between pt-0.5">
                <span className={cn("font-mono text-[10px] tabular-nums", q.score !== null && q.score < 2.5 ? "text-ember" : "text-dim")}>
                  {q.score === null ? "–" : `${q.score.toFixed(1)} / 5`}
                </span>
                <span className="flex gap-1">
                  {(
                    [
                      ["repeat", "Repeat", Repeat],
                      ["study", "Study", Target],
                    ] as const
                  ).map(([m, label, Icon]) => (
                    <button
                      key={m}
                      type="button"
                      aria-pressed={mark === m}
                      onClick={() => toggle(q.id, m)}
                      className={cn(
                        "flex items-center gap-1 rounded-[3px] border px-2 py-0.5 text-[11px] transition-colors",
                        mark === m ? "border-invert-bg bg-invert-bg text-invert-ink" : "border-line text-ink-2 hover:text-ink",
                      )}
                    >
                      <Icon className="size-3" strokeWidth={1.75} />
                      {label}
                    </button>
                  ))}
                </span>
              </div>
            </li>
          );
        })}
      </ol>
      <div className="border-t border-line p-3">
        <button
          type="button"
          disabled={picked === 0 || !onDrill || drilling}
          onClick={() => onDrill?.(picks)}
          className="group flex h-9 w-full items-center justify-center rounded-[3px] bg-invert-bg font-mono text-[11px] uppercase tracking-[0.02em] text-invert-ink disabled:opacity-35"
        >
          {drilling ? "Starting the drill" : `Drill ${picked} selected`}
        </button>
        {picked > 0 && !drilling && (
          <p className="pt-2 text-center text-[11.5px] text-ink-2">
            {endsSession ? "Ends this session (its report is kept) and starts" : "Starts"} a new one with{" "}
            {picked === 1 ? "this question" : "these questions"} first.
          </p>
        )}
      </div>
    </Panel>
  );
}
