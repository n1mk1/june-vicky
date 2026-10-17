"use client";

import { Repeat, Target } from "lucide-react";
import { useState } from "react";
import { Panel } from "@/components/ui/Panel";
import { PANEL, QUESTIONS } from "@/lib/panel";
import { cn } from "@/lib/utils";
import { ClaimChip } from "./ClaimChip";

type Mark = "repeat" | "focus";

/** Questions asked so far; mark the ones to repeat or study, then drill them. */
export function QuestionList() {
  const [marks, setMarks] = useState<Record<string, Mark | undefined>>({ q2: "repeat" });
  const [drilled, setDrilled] = useState<string | null>(null);
  const picked = Object.values(marks).filter(Boolean).length;

  const toggle = (id: string, m: Mark) => setMarks((s) => ({ ...s, [id]: s[id] === m ? undefined : m }));

  return (
    <Panel title="Questions & answers" aside={<span className="label">{QUESTIONS.length}</span>} bodyClassName="flex min-h-0 flex-col">
      <ol className="scroll-thin min-h-0 flex-1 divide-y divide-line overflow-y-auto">
        {QUESTIONS.map((q) => {
          const vc = PANEL.find((p) => p.id === q.vc);
          const mark = marks[q.id];
          return (
            <li key={q.id} className={cn("flex flex-col gap-2 px-4 py-3.5 transition-colors", mark && "bg-surface-solid/50")}>
              <div className="flex items-start justify-between gap-2">
                <span className="text-[11px] text-ink-2">{vc?.name}</span>
                {q.status === "open" ? (
                  <span className="text-[11px] text-dim">Not asked yet</span>
                ) : (
                  <ClaimChip status={q.status} />
                )}
              </div>
              <p className="font-display text-[16px] leading-tight tracking-[-0.03em]">{q.question}</p>
              <p className="text-[12.5px] text-ink-2">{q.answer}</p>
              <div className="flex items-center justify-between pt-0.5">
                <span className="font-mono text-[10px] tabular-nums text-dim">{q.score === null ? "–" : `${q.score.toFixed(1)} / 5`}</span>
                <span className="flex gap-1">
                  {(
                    [
                      ["repeat", "Repeat", Repeat],
                      ["focus", "Study", Target],
                    ] as const
                  ).map(([m, label, Icon]) => (
                    <button
                      key={m}
                      type="button"
                      aria-pressed={mark === m}
                      onClick={() => toggle(q.id, m)}
                      className={cn(
                        "flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] transition-colors",
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
          disabled={picked === 0}
          onClick={() => setDrilled(`Drill ready: ${picked} question${picked === 1 ? "" : "s"} at the top of your next session.`)}
          className="group flex h-9 w-full items-center justify-center rounded-full bg-invert-bg font-display text-[12.5px] uppercase tracking-[-0.02em] text-invert-ink disabled:opacity-35"
        >
          Drill {picked} selected
        </button>
        {drilled && (
          <p className="pt-2 text-center text-[11.5px] text-ink-2" role="status">
            {drilled}
          </p>
        )}
      </div>
    </Panel>
  );
}
