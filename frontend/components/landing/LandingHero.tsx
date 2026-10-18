"use client";

import { ArrowRight, Globe } from "lucide-react";
import Link from "next/link";
import { useEffect, useState, type CSSProperties } from "react";
import { Lockup } from "@/components/app/Lockup";
import { ThemeToggle } from "@/components/app/ThemeToggle";
import { LightStreaks } from "@/components/fx/LightStreaks";
import { SpinningVScene } from "@/components/fx/scenes";
import { CornerMarks } from "@/components/ui/Panel";
import { RollLabel } from "@/components/ui/RollLabel";

/** The word in the headline that keeps changing: what the founder needs to know cold. */
const WORDS = ["numbers", "runway", "churn", "story", "market"];
const CYCLE_MS = 2600;

const STEPS = [
  ["01", "Dump everything into the knowledge base"],
  ["02", "Face a panel of AI investors"],
  ["03", "Know every figure cold"],
] as const;

/** One word that resolves letter by letter from blur, then gives way to the next. */
function CyclingWord() {
  const [i, setI] = useState(0);
  useEffect(() => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) return;
    const t = window.setInterval(() => setI((n) => (n + 1) % WORDS.length), CYCLE_MS);
    return () => window.clearInterval(t);
  }, []);
  const word = WORDS[i];
  return (
    <span key={word} aria-live="off" className="inline-block whitespace-nowrap">
      {[...word].map((ch, k) => (
        <span key={k} className="blur-word" style={{ "--i": k * 1.6 } as CSSProperties}>
          {ch}
        </span>
      ))}
    </span>
  );
}

/** Landing (Trionn-style intro): the spinning V, one headline, one way in. */
export function LandingHero() {
  // Warm a sleeping free-tier API while the hero animates in.
  useEffect(() => {
    void fetch("/api/health", { cache: "no-store" }).catch(() => {});
  }, []);

  return (
    <main className="relative isolate flex min-h-dvh flex-col overflow-hidden">
      <LightStreaks />

      {/* The V is the one loud thing on the page. */}
      {/* Phones: in the open space under the copy. Wider: centre stage, nudged right of the headline. */}
      <div className="pointer-events-none absolute inset-x-0 top-[44%] bottom-[20%] -z-10 animate-[rise_1.4s_var(--ease-soft)_both] [animation-delay:150ms] md:inset-y-0 md:right-0 md:left-[18%]">
        <SpinningVScene />
      </div>

      <header className="relative z-10 flex items-center justify-between gap-3 px-4 pt-4 md:px-6">
        <div className="flex items-center gap-3">
          <Lockup />
          <ThemeToggle />
        </div>
        <Link
          href="/knowledge"
          className="group hidden h-8 items-center gap-2 rounded-full border border-invert-bg bg-invert-bg px-3.5 font-display text-[12.5px] uppercase tracking-[-0.02em] text-invert-ink sm:inline-flex"
        >
          <RollLabel text="Get started" />
        </Link>
      </header>

      <section className="relative z-10 flex flex-1 flex-col justify-between gap-10 px-4 pt-8 pb-6 md:px-6 md:pt-12">
        <div className="flex max-w-[760px] flex-col items-start gap-6">
          <span className="label animate-[rise_1s_var(--ease-soft)_both] [animation-delay:200ms]">
            Your AI venture capitalist
          </span>
          <h1 className="display text-[clamp(48px,6.6vw,112px)] tracking-[-0.06em] animate-[rise_1s_var(--ease-soft)_both] [animation-delay:250ms]">
            Know your <CyclingWord />
            <br />
            before they do.
          </h1>
          <Link
            href="/knowledge"
            className="group inline-flex h-12 items-center gap-3 rounded-full border border-invert-bg bg-invert-bg pr-2 pl-6 font-display text-[15px] uppercase tracking-[-0.02em] text-invert-ink transition-[gap] duration-300 hover:gap-4 animate-[rise_1s_var(--ease-soft)_both] [animation-delay:450ms]"
          >
            <RollLabel text="Get started" />
            <span className="grid size-8 place-items-center rounded-full bg-ember text-white">
              <ArrowRight className="size-4 transition-transform duration-300 group-hover:translate-x-0.5" strokeWidth={1.75} />
            </span>
          </Link>
          <ol className="flex flex-col gap-1.5 animate-[rise_1s_var(--ease-soft)_both] [animation-delay:600ms]">
            {STEPS.map(([n, text]) => (
              <li key={n} className="flex items-center gap-3 font-mono text-[10.5px] uppercase tracking-[-0.04em] text-ink-2">
                <span className="text-ember">{n}</span>
                {text}
              </li>
            ))}
          </ol>
        </div>

        <div className="flex flex-col items-stretch gap-6 md:flex-row md:items-end md:justify-between">
          <p className="order-2 text-[11.5px] text-dim md:order-1 md:w-[220px]">Synthetic data. No investment advice.</p>
          <p className="order-3 hidden text-center font-mono text-[10.5px] uppercase tracking-[-0.04em] text-ink-2 md:order-2 md:block">
            Hold anywhere to scatter the lines
          </p>
          <div className="order-1 flex flex-col gap-3 md:order-3 md:w-[260px]">
            <div className="relative">
              <CornerMarks />
              <div className="glass grid grid-cols-2 text-[10px] uppercase">
              <span className="flex flex-col items-center gap-1.5 border-r border-line px-3 py-3 font-mono tracking-[-0.04em] text-ink-2">
                <Globe className="size-4 text-ink" strokeWidth={1.25} aria-hidden />
                Est. 2026
              </span>
              <span className="flex items-center px-3 py-3 font-mono leading-snug tracking-[-0.04em] text-ink-2">
                Built for founders before the room
              </span>
              </div>
            </div>
            <p className="text-[13px] leading-snug text-ink-2">
              Drop in your data, face investors who have read it, and rehearse until every figure holds.
            </p>
          </div>
        </div>
      </section>
    </main>
  );
}
