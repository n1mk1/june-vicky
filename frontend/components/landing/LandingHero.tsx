"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Lockup } from "@/components/app/Lockup";
import { PromptBar } from "@/components/app/PromptBar";
import { ThemeToggle } from "@/components/app/ThemeToggle";
import { LightStreaks } from "@/components/fx/LightStreaks";
import { VMarkScene } from "@/components/fx/scenes";
import { RollLabel } from "@/components/ui/RollLabel";
import { apiPost } from "@/lib/api";
import type { AnyFigure, Engagement } from "@/lib/types";
import { isMissing } from "@/lib/types";
import { errorText, useAccessGuard, useApi } from "@/lib/use-api";

const MODES = [
  { href: "/dashboard", label: "Insights" },
  { href: "/preparation", label: "Prep" },
  { href: "/simulation", label: "Sim" },
];

/** Engagement-aware hint under the prompt bar (UI doc §3.2). */
function LandingHint({ uploadError }: { uploadError: string | null }) {
  const active = useApi<Engagement>("engagements/active");
  const engagement = active.status === 404 ? null : active.data;
  const arr = useApi<AnyFigure>(engagement ? "metrics/arr" : null);

  if (uploadError) return <span className="text-ember">{uploadError}</span>;
  if (engagement) {
    const company = engagement.profile?.name || engagement.name;
    const figure = arr.data && !isMissing(arr.data) ? arr.data : null;
    return (
      <>
        {company} loaded{figure ? ` · ARR ${figure.display}` : ""}.{" "}
        <Link href="/intake" className="text-ink-2 underline underline-offset-2 hover:text-ink">
          Load different data
        </Link>
      </>
    );
  }
  if (active.loading) return <>Checking your source of truth…</>;
  return (
    <>
      Attach a CSV, XLSX, PDF, DOCX or MD file, or{" "}
      <Link href="/intake" className="text-ink underline underline-offset-2 hover:text-ember">
        try a sample
      </Link>
      . Hold anywhere on the background to scatter the lines.
    </>
  );
}

export function LandingHero() {
  const router = useRouter();
  const guard = useAccessGuard();
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  // Warm a sleeping free-tier API while the hero animates in.
  useEffect(() => {
    void fetch("/api/health", { cache: "no-store" }).catch(() => {});
  }, []);

  const attach = async (file: File) => {
    setUploading(true);
    setUploadError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const engagement = await apiPost<Engagement>("uploads", form);
      router.push(`/intake?e=${encodeURIComponent(engagement.id)}`);
    } catch (err) {
      setUploading(false);
      if (!guard(err)) setUploadError(errorText(err));
    }
  };

  return (
    <main className="relative isolate flex min-h-dvh flex-col overflow-hidden">
      <LightStreaks />

      {/* The mark is the one loud thing on the page. */}
      <div className="pointer-events-none absolute inset-x-0 top-[12%] -z-10 h-[64vh] md:top-[6%] md:right-[34%] md:h-[88vh]">
        <VMarkScene />
      </div>

      <header className="relative z-10 flex flex-wrap items-center gap-3 px-4 pt-4 md:px-6">
        <Lockup />
        <ThemeToggle />
      </header>

      <section className="relative z-10 flex flex-1 flex-col justify-between gap-10 px-4 pt-10 pb-6 md:px-6">
        <div className="flex flex-col items-start gap-5 md:ml-auto md:w-[min(46vw,640px)]">
          <h1 className="display text-[clamp(44px,6.4vw,104px)] animate-[rise_1s_var(--ease-soft)_both] [animation-delay:200ms]">
            Know your numbers before they do.
          </h1>
          <p className="max-w-[38ch] text-[15px] leading-snug text-ink-2 animate-[rise_1s_var(--ease-soft)_both] [animation-delay:350ms]">
            Vicky is an AI venture capitalist. Load your data, face a panel of investors who have read it, and
            rehearse the pitch until every figure holds.
          </p>
          <nav
            aria-label="Modes"
            className="flex items-center rounded-full border border-line-strong p-[3px] animate-[rise_1s_var(--ease-soft)_both] [animation-delay:500ms]"
          >
            {MODES.map((m, i) => (
              <Link
                key={m.href}
                href={m.href}
                className="group flex h-8 items-center gap-2 rounded-full px-4 font-display text-[12.5px] uppercase tracking-[-0.02em] text-ink-2 transition-colors hover:bg-invert-bg hover:text-invert-ink"
              >
                {i > 0 && <span aria-hidden className="-ml-4 mr-2 h-3 w-px bg-line-strong group-hover:opacity-0" />}
                <RollLabel text={m.label} />
              </Link>
            ))}
          </nav>
        </div>

        <div className="mx-auto flex w-full max-w-[640px] flex-col gap-4">
          <PromptBar
            label="Ask Vicky"
            placeholder="Ask about your numbers, e.g. how is my ARR calculated?"
            onSubmit={(text) => {
              try {
                sessionStorage.setItem("vicky-question", text);
              } catch {}
              router.push("/preparation");
            }}
            onAttach={attach}
            busy={uploading}
            hint={<LandingHint uploadError={uploadError} />}
          />
          <p className="text-center text-[11.5px] text-dim">Synthetic data. No investment advice.</p>
        </div>
      </section>
    </main>
  );
}
