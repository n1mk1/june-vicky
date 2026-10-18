"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useActiveEngagement } from "@/components/app/EngagementProvider";
import { CornerMarks } from "@/components/ui/Panel";
import { PillButton, PillLink } from "@/components/ui/Pill";
import { ErrorNote, Loading } from "@/components/ui/States";
import { apiPost } from "@/lib/api";
import { fmtBytes, fmtDate } from "@/lib/format";
import { confirmHref } from "@/lib/kb";
import type { Engagement } from "@/lib/types";
import { errorText, useAccessGuard, useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";
import { CoverageList } from "./CoverageList";
import { FactsTable } from "./FactsTable";
import { MappingTable } from "./MappingTable";
import { ProfileForm } from "./ProfileForm";
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
        <PillLink href="/knowledge" label="Back to the knowledge base" />
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
        <Link href="/knowledge" className="flex items-center gap-1 text-[12px] text-ink-2 hover:text-ink">
          <ArrowLeft className="size-3.5" strokeWidth={1.5} /> Knowledge base
        </Link>
      </div>

      <StepBar step={step} onStep={setStep} />

      <section className="glass relative rounded-[4px] p-4 md:p-6">
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
              <p className="rounded-[4px] border border-dashed border-line-strong p-4 text-[12.5px] text-ink-2">
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

/**
 * Checking a draft source of truth before it is confirmed: 01 profile → 02 mapping → 03 facts → 04 confirm.
 * Drafts come from the knowledge base ("Fill dashboard") or a file attached on the dashboard.
 */
export function ConfirmView() {
  const router = useRouter();
  const params = useSearchParams();
  const id = params.get("e");
  const raw = Number(params.get("step"));
  const step = (raw >= 1 && raw <= 4 ? raw : 1) as Step;

  const go = (engagementId: string, s: Step, replace = false) => {
    const url = confirmHref(engagementId, s);
    if (replace) router.replace(url, { scroll: false });
    else router.push(url);
  };

  return (
    <div className="scroll-thin -mx-1 min-h-0 flex-1 overflow-y-auto px-1 pb-6">
      {id ? (
        <EngagementFlow key={id} id={id} step={step} setStep={(s) => go(id, s, true)} />
      ) : (
        <div className="flex flex-col items-start gap-3">
          <ErrorNote message="Nothing to check. Fill the dashboard from the knowledge base to build a source of truth." />
          <PillLink href="/knowledge" label="Open the knowledge base" />
        </div>
      )}
    </div>
  );
}
