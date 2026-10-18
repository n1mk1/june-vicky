"use client";

import Link from "next/link";
import { Field, inputCls } from "@/components/ui/Field";
import { PillButton } from "@/components/ui/Pill";
import { Segmented } from "@/components/ui/Segmented";
import { fmtDate } from "@/lib/format";
import type { SessionSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface SetupValue {
  cap: number;
  coaching: "coached" | "realistic";
  focus: string;
  /** Knowledge checks: investors test whether the founder knows their own notes. */
  knowledge: boolean;
}

interface SessionSetupProps {
  value: SetupValue;
  onChange: (v: SetupValue) => void;
  onStart: () => void;
  seated: string[];
  starting: boolean;
  recent?: SessionSummary[];
  onResume: (id: string) => void;
}

/** Before the court opens: question cap, coaching mode, knowledge checks and an optional focus (UI doc §3.5). */
export function SessionSetup({ value, onChange, onStart, seated, starting, recent, onResume }: SessionSetupProps) {
  const live = (recent ?? []).filter((s) => s.status === "live").slice(0, 3);
  const done = (recent ?? []).filter((s) => s.status !== "live" && s.report_id).slice(0, 3);
  return (
    <div className="flex flex-col gap-6 p-4 md:p-6">
      <div className="flex flex-col gap-2">
        <span className="label">New session</span>
        <h2 className="display text-[clamp(30px,3.4vw,48px)]">Face the panel.</h2>
        <p className="max-w-[56ch] text-[13.5px] leading-snug text-ink-2">
          Vicky chairs: she picks who asks next, reviews every question before it&apos;s asked and scores every answer.{" "}
          {seated.length ? seated.join(", ") : "Nobody"} {seated.length === 1 ? "has" : "have"} read your numbers and written private
          memos on where you&apos;re weakest. Every figure you say is checked against your source of truth.
        </p>
      </div>

      <div className="grid gap-5 sm:grid-cols-2">
        <Field label={`Questions · ${value.cap}`} htmlFor="cap" hint="The session ends after this many questions. 6 to 20.">
          <input
            id="cap"
            type="range"
            min={6}
            max={20}
            step={1}
            value={value.cap}
            onChange={(e) => onChange({ ...value, cap: Number(e.target.value) })}
            className="h-9 w-full accent-[var(--ember)]"
          />
        </Field>
        <Field
          label="Coaching"
          hint={value.coaching === "coached" ? "A score card after every answer, and time-outs when you miss twice." : "No scores until the report, like the real meeting."}
        >
          <Segmented
            label="Coaching"
            value={value.coaching}
            onChange={(coaching) => onChange({ ...value, coaching })}
            options={[
              { value: "coached", label: "Coached" },
              { value: "realistic", label: "Realistic" },
            ]}
            className="self-start"
          />
        </Field>
        <Field
          label="Knowledge checks"
          className="sm:col-span-2"
          hint={
            value.knowledge
              ? "Some questions test whether you know your own notes; Vicky checks each answer against them. Needs the search index from Fill dashboard."
              : "Off: every question comes from the investors' doubts about your numbers."
          }
        >
          <Segmented
            label="Knowledge checks"
            value={value.knowledge ? "on" : "off"}
            onChange={(v) => onChange({ ...value, knowledge: v === "on" })}
            options={[
              { value: "on", label: "On" },
              { value: "off", label: "Off" },
            ]}
            className="self-start"
          />
        </Field>
        <Field label="Focus (optional)" htmlFor="focus" className="sm:col-span-2" hint="A topic or question to put at the top of the agenda.">
          <textarea
            id="focus"
            rows={2}
            value={value.focus}
            onChange={(e) => onChange({ ...value, focus: e.target.value })}
            placeholder="e.g. how we calculate ARR, or why burn is falling"
            className={cn(inputCls, "h-auto resize-none py-2")}
          />
        </Field>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <PillButton variant="solid" label={starting ? "Opening the court" : "Start session"} disabled={starting || seated.length === 0} onClick={onStart} />
        {seated.length === 0 && <span className="text-[12px] text-ink-2">Pick at least one investor to start.</span>}
      </div>

      {(live.length > 0 || done.length > 0) && (
        <div className="flex flex-col gap-2 border-t border-line pt-4">
          <span className="label">Recent sessions</span>
          <ul className="flex flex-col divide-y divide-line">
            {live.map((s) => (
              <li key={s.id} className="flex items-center justify-between gap-3 py-2 text-[12.5px]">
                <span className="text-ink-2">
                  Live · {s.question_count} questions · {fmtDate(s.started_at, true)}
                </span>
                <button type="button" onClick={() => onResume(s.id)} className="text-ink underline underline-offset-2">
                  Resume
                </button>
              </li>
            ))}
            {done.map((s) => (
              <li key={s.id} className="flex items-center justify-between gap-3 py-2 text-[12.5px]">
                <span className="text-ink-2">
                  Ended · {s.question_count} questions · {fmtDate(s.started_at, true)}
                </span>
                <Link href={`/reports/${s.report_id}`} className="text-ink underline underline-offset-2">
                  Report
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
