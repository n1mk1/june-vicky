"use client";

import { ArrowLeft, ArrowRight } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useActiveEngagement } from "@/components/app/EngagementProvider";
import { CornerMarks, Panel } from "@/components/ui/Panel";
import { PillButton, PillLink } from "@/components/ui/Pill";
import { ErrorNote, Loading } from "@/components/ui/States";
import { apiPost } from "@/lib/api";
import { fmtBytes, fmtDate } from "@/lib/format";
import type { Engagement } from "@/lib/types";
import { errorText, useAccessGuard, useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";
import { CoverageList } from "./CoverageList";
import { FactsTable } from "./FactsTable";
import { MappingTable } from "./MappingTable";
import { ProfileForm } from "./ProfileForm";
import { SamplePicker } from "./SamplePicker";
import { UploadDrop } from "./UploadDrop";

const STEPS = ["Profile", "Mapping", "Facts", "Confirm"] as const;
type Step = 1 | 2 | 3 | 4;

function StepBar({ step, onStep }: { step: Step; onStep: (s: Step) => void }) {
  return (
    <nav aria-label="TruthPack steps" className="flex flex-col gap-2">
      <ol className="flex flex-wrap gap-x-5 gap-y-1">
        {STEPS.map((label, i) => {
          const n = (i + 1) as Step;
          return (
            <li key={label}>
              <button
                type="button"
                onClick={() => onStep(n)}
                aria-current={step === n ? "step" : undefined}
                className={cn(
                  "font-mono text-[10.5px] uppercase tracking-[-0.04em] transition-colors",
                  step === n ? "text-ink" : n < step ? "text-ink-2 hover:text-ink" : "text-dim hover:text-ink-2",
                )}
              >
                {String(n).padStart(2, "0")} {label}
              </button>
            </li>
          );
        })}
      </ol>
      <span className="relative block h-px w-full bg-line" aria-hidden>
        <span
          className="absolute inset-y-0 left-0 bg-ember transition-[width] duration-500 ease-[var(--ease-soft)]"
          style={{ width: `${(step / STEPS.length) * 100}%` }}
        />
      </span>
    </nav>
  );
}

/** Before an engagement exists: pick a sample or upload a file. */
function SourceStep({ onReady }: { onReady: (e: Engagement, step: Step) => void }) {
  const { engagement: active } = useActiveEngagement();
  const drafts = useApi<Engagement[]>("engagements");
  const open = (drafts.data ?? []).filter((e) => e.status === "draft").slice(0, 4);

  return (
    <div className="mx-auto flex w-full max-w-[1080px] flex-col gap-6">
      <div className="flex flex-col gap-3 pt-2">
        <span className="label">Source of truth</span>
        <h1 className="display text-[clamp(36px,4.6vw,68px)]">Load the numbers the panel will check you against.</h1>
        <p className="max-w-[60ch] text-[14px] leading-snug text-ink-2">
          Upload your financials or try a sample. You&apos;ll confirm the company profile, how each column maps, and any facts
          your files can&apos;t show. Every figure after that is computed from what you confirm.
        </p>
        {active && (
          <p className="flex flex-wrap items-center gap-2 text-[12.5px] text-ink-2">
            <span className="size-1.5 rounded-full bg-ember" aria-hidden />
            {active.profile?.name || active.name} is confirmed now. Loading new data starts a new engagement; the current one
            stays under Reports.
            <Link href="/dashboard" className="text-ink underline underline-offset-2">
              Back to the dashboard
            </Link>
          </p>
        )}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Upload" marks bodyClassName="flex flex-col gap-3 p-4">
          <UploadDrop onUploaded={(e) => onReady(e, 1)} />
          <p className="text-[11.5px] leading-snug text-dim">
            Tables (CSV, XLSX) are parsed straight away. Documents (PDF, DOCX, MD) are read for facts with page citations.
          </p>
        </Panel>
        <Panel title="Try a sample" marks bodyClassName="p-4">
          <SamplePicker onLoaded={(e) => onReady(e, 4)} />
        </Panel>
      </div>
      {open.length > 0 && (
        <Panel title="Unfinished" bodyClassName="divide-y divide-line">
          {open.map((e) => (
            <Link
              key={e.id}
              href={`/intake?e=${encodeURIComponent(e.id)}`}
              className="flex items-center justify-between gap-3 px-4 py-3 text-[13px] transition-colors hover:bg-surface-solid/40"
            >
              <span className="truncate">{e.profile?.name || e.name || "Untitled"}</span>
              <span className="flex shrink-0 items-center gap-2 text-[11.5px] text-ink-2">
                Started {fmtDate(e.created_at)} <ArrowRight className="size-3.5" strokeWidth={1.5} />
              </span>
            </Link>
          ))}
        </Panel>
      )}
    </div>
  );
}

function EngagementFlow({ id, step, setStep }: { id: string; step: Step; setStep: (s: Step) => void }) {
  const router = useRouter();
  const guard = useAccessGuard();
  const { refresh } = useActiveEngagement();
  const res = useApi<Engagement>(`engagements/${encodeURIComponent(id)}`);
  const [confirming, setConfirming] = useState(false);
  const [confirmError, setConfirmError] = useState<string | null>(null);

  if (res.loading && !res.data) return <Loading label="Loading your engagement" className="p-2" />;
  if (res.status === 404) {
    return (
      <div className="flex flex-col items-start gap-3">
        <ErrorNote message="That engagement doesn't exist any more." />
        <PillLink href="/intake" label="Start again" />
      </div>
    );
  }
  if (res.error && !res.data) return <ErrorNote message={errorText(res.error)} onRetry={res.reload} />;
  const e = res.data;
  if (!e) return null;

  const company = e.profile?.name || e.name || "Your company";
  const currency = (e.profile?.currency ?? "usd").toLowerCase();

  const confirm = async () => {
    setConfirming(true);
    setConfirmError(null);
    try {
      const next = await apiPost<Engagement>(`engagements/${e.id}/confirm`);
      res.mutate(next);
      refresh();
      router.push("/dashboard");
    } catch (err) {
      setConfirming(false);
      if (!guard(err)) setConfirmError(errorText(err));
    }
  };

  const unconfirmed = e.datasets.filter((d) => !d.mapping_confirmed).length;

  return (
    <div className="mx-auto flex w-full max-w-[1080px] flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <span className="label">Source of truth · {e.status === "active" ? "confirmed" : "draft"}</span>
          <h1 className="display truncate text-[clamp(32px,4vw,56px)]">{company}</h1>
        </div>
        <Link href="/intake" className="flex items-center gap-1 text-[12px] text-ink-2 hover:text-ink">
          <ArrowLeft className="size-3.5" strokeWidth={1.5} /> Different data
        </Link>
      </div>

      <StepBar step={step} onStep={setStep} />

      <section className="glass relative rounded-[20px] p-4 md:p-6">
        <CornerMarks />
        {step === 1 && (
          <div className="flex flex-col gap-4">
            <StepTitle n={1} title="Company profile" body="Vicky uses this for currency, benchmarks and the country rules the panel applies." />
            <ProfileForm
              key={e.id}
              engagement={e}
              onSaved={(next) => {
                res.mutate(next);
                setStep(2);
              }}
            />
          </div>
        )}

        {step === 2 && (
          <div className="flex flex-col gap-4">
            <StepTitle
              n={2}
              title="Column mapping"
              body="Check how each column maps to a standard field. Anything you keep as raw stays available to charts but isn't used for metrics."
            />
            {e.datasets.length === 0 ? (
              <p className="rounded-[14px] border border-dashed border-line-strong p-4 text-[12.5px] text-ink-2">
                No tables to map. Documents go straight to facts.
              </p>
            ) : (
              e.datasets.map((d) => <MappingTable key={d.id} dataset={d} currency={currency} onChanged={res.reload} />)
            )}
            {e.uploads.length > 0 && (
              <p className="text-[11.5px] text-dim">
                Files: {e.uploads.map((u) => `${u.filename} (${fmtBytes(u.size)}${u.status && u.status !== "parsed" ? `, ${u.status}` : ""})`).join(" · ")}
              </p>
            )}
            <UploadDrop engagementId={e.id} onUploaded={res.mutate} compact />
            <StepNav onBack={() => setStep(1)} onNext={() => setStep(3)} />
          </div>
        )}

        {step === 3 && (
          <div className="flex flex-col gap-4">
            <StepTitle
              n={3}
              title="Facts"
              body="Figures your tables can't show: cash, customers, retention from the pack or a document. Remove anything that's wrong."
            />
            <FactsTable engagement={e} onChanged={res.mutate} />
            <StepNav onBack={() => setStep(2)} onNext={() => setStep(4)} />
          </div>
        )}

        {step === 4 && (
          <div className="flex flex-col gap-5">
            <StepTitle n={4} title="Coverage" body="What the panel can check you on, and what it can't yet." />
            <CoverageList items={e.coverage} />
            {unconfirmed > 0 && (
              <p className="text-[12px] text-ink-2">
                {unconfirmed} table{unconfirmed === 1 ? "" : "s"} still use the proposed mapping. Confirming accepts{" "}
                {unconfirmed === 1 ? "it" : "them"} as shown in{" "}
                <button type="button" className="text-ink underline underline-offset-2" onClick={() => setStep(2)}>
                  step 02
                </button>
                .
              </p>
            )}
            {confirmError && <ErrorNote message={confirmError} />}
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
              <PillButton variant="ghost" label="Back" onClick={() => setStep(3)} />
              <div className="flex items-center gap-3">
                {e.status === "active" && e.confirmed_at && (
                  <span className="text-[11.5px] text-dim">Confirmed {fmtDate(e.confirmed_at, true)}</span>
                )}
                <PillButton
                  variant="solid"
                  label={confirming ? "Confirming" : e.status === "active" ? "Confirm again" : "Confirm source of truth"}
                  disabled={confirming}
                  onClick={() => void confirm()}
                />
              </div>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

function StepTitle({ n, title, body }: { n: number; title: string; body: string }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="label">Step {String(n).padStart(2, "0")}</span>
      <h2 className="font-display text-[24px] tracking-[-0.04em]">{title}</h2>
      <p className="max-w-[70ch] text-[13px] leading-snug text-ink-2">{body}</p>
    </div>
  );
}

function StepNav({ onBack, onNext }: { onBack: () => void; onNext: () => void }) {
  return (
    <div className="flex items-center justify-between gap-3 border-t border-line pt-4">
      <PillButton variant="ghost" label="Back" onClick={onBack} />
      <PillButton variant="solid" label="Continue" onClick={onNext} />
    </div>
  );
}

/** The TruthPack flow (App flow §2a–2b): source → 01 profile → 02 mapping → 03 facts → 04 confirm. */
export function IntakeView() {
  const router = useRouter();
  const params = useSearchParams();
  const id = params.get("e");
  const raw = Number(params.get("step"));
  const step = (raw >= 1 && raw <= 4 ? raw : 1) as Step;

  const go = (engagementId: string, s: Step, replace = false) => {
    const url = `/intake?e=${encodeURIComponent(engagementId)}&step=${s}`;
    if (replace) router.replace(url, { scroll: false });
    else router.push(url);
  };

  return (
    <div className="scroll-thin -mx-1 min-h-0 flex-1 overflow-y-auto px-1 pb-6">
      {id ? (
        <EngagementFlow key={id} id={id} step={step} setStep={(s) => go(id, s, true)} />
      ) : (
        <SourceStep onReady={(e, s) => go(e.id, s)} />
      )}
    </div>
  );
}
