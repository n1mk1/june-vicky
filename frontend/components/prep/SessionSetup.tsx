"use client";

import Link from "next/link";
import { useState } from "react";
import { Field } from "@/components/ui/Field";
import { PillButton } from "@/components/ui/Pill";
import { Segmented } from "@/components/ui/Segmented";
import { fmtDate } from "@/lib/format";
import type { SessionSummary } from "@/lib/types";

export interface SetupValue {
  cap: number;
  coaching: "coached" | "realistic";
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

/** Before the court opens: question cap, coaching mode and knowledge checks; past sessions sit behind a button (UI doc §3.5). */
export function SessionSetup({ value, onChange, onStart, seated, starting, recent, onResume }: SessionSetupProps) {
  const [showRecent, setShowRecent] = useState(false);
  const live = (recent ?? []).filter((s) => s.status === "live");
  const done = (recent ?? []).filter((s) => s.status !== "live" && s.report_id);
  const hasRecent = live.length > 0 || done.length > 0;

  if (showRecent && hasRecent) {
    return (
      <div className="flex flex-col gap-4 p-4 md:p-6">
        <div className="flex items-center justify-between gap-3">
          <span className="label">Recent sessions</span>
          <PillButton label="Back" variant="outline" onClick={() => setShowRecent(false)} className="h-7" />
        </div>
        <ul className="flex flex-col divide-y divide-line" data-testid="recent-sessions">
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
    );
  }

  return (
    <div className="flex flex-col gap-6 p-4 md:p-6">
      <div className="flex flex-col gap-2">
        <span className="label">New session</span>
        <h2 className="display text-[clamp(30px,3.4vw,48px)]">Prepare.</h2>
      </div>

      <div className="grid gap-5 sm:grid-cols-2">
        <Field label={`Questions · ${value.cap}`} htmlFor="cap">
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
        <Field label="Coaching">
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
        <Field label="Knowledge checks" className="sm:col-span-2">
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
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <PillButton variant="solid" label={starting ? "Opening the court" : "Start session"} disabled={starting || seated.length === 0} onClick={onStart} />
        {hasRecent && (
          <PillButton variant="outline" label={`Recent sessions · ${live.length + done.length}`} onClick={() => setShowRecent(true)} />
        )}
        {seated.length === 0 && <span className="text-[12px] text-ink-2">Pick at least one investor to start.</span>}
      </div>
    </div>
  );
}
