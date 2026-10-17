"use client";

import { useEffect, useState, type CSSProperties } from "react";
import { CornerMarks } from "@/components/ui/Panel";
import { cn } from "@/lib/utils";

const DURATION = 1600;

/**
 * The VICKY wordmark from brand/vicky/Vicky_Logo.svg, flattened to absolute paths
 * (the file's per-letter translates applied). Order sets the draw stagger.
 */
const WORDMARK_VIEWBOX = "0 0 677 142";
const WORDMARK_PATHS = [
  "M0 0H30L62 94.7L94 0H124L76 142H48Z", // V
  "M185 0V142H158V33Z", // I, knife-cut top
  "M349.4 29.3A71 71 0 1 0 349.4 112.7H306A44 44 0 1 1 306 29.3Z", // C
  "M385 0H412V142H385Z", // K stem
  "M471 0H509L412 98.7V60Z", // K arm
  "M443.3 81.1L462.5 61.6L522.8 142H489Z", // K leg, sliced off
  "M553 0H585L615 45.8L645 0H677L628.5 74V112L605 142H601.5V74Z", // Y, knife-cut foot
];

function Digit({ value }: { value: number }) {
  return (
    <span className="inline-block h-[1.2em] overflow-hidden align-top leading-[1.2em]">
      <span
        className="flex flex-col transition-transform duration-300 ease-[var(--ease-soft)]"
        style={{ transform: `translateY(${-value * 1.2}em)` } as CSSProperties}
      >
        {Array.from({ length: 10 }, (_, d) => (
          <span key={d}>{d}</span>
        ))}
      </span>
    </span>
  );
}

function markDone() {
  document.documentElement.dataset.preloaded = "";
  try {
    sessionStorage.setItem("vicky-preloaded", "1");
  } catch {
    // Without storage the intro simply plays again next visit.
  }
}

/** First-visit intro: the framed wordmark draws itself while a rolling counter reaches 100. */
export function Preloader() {
  const [count, setCount] = useState(0);
  const [phase, setPhase] = useState<"run" | "leave" | "gone">("run");

  useEffect(() => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    // Already shown this session, or motion is reduced: CSS keeps the overlay hidden.
    if ("preloaded" in document.documentElement.dataset || reduced) {
      markDone();
      return;
    }

    let raf = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / DURATION);
      setCount(Math.round(100 * (1 - Math.pow(1 - t, 3))));
      if (t < 1) raf = requestAnimationFrame(tick);
      else setPhase("leave");
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  useEffect(() => {
    if (phase !== "leave") return;
    const id = window.setTimeout(() => {
      markDone();
      setPhase("gone");
    }, 750);
    return () => window.clearTimeout(id);
  }, [phase]);

  if (phase === "gone") return null;

  const digits = String(count).padStart(3, "0").split("").map(Number);

  return (
    <div
      className={cn(
        "preloader fixed inset-0 z-[100] flex flex-col items-center justify-center bg-[#c8c8c8] text-[#111214] transition-[clip-path] duration-700 ease-[var(--ease-soft)]",
        phase === "leave" ? "[clip-path:inset(0_0_100%_0)]" : "[clip-path:inset(0_0_0_0)]",
      )}
      role="status"
      aria-label="Loading"
    >
      <div className="relative flex h-40 w-72 items-center justify-center border border-[#111214]/15">
        <CornerMarks className="[&_span]:text-[#111214]/60" />
        <span className="absolute -top-px left-0 h-px w-full origin-left animate-[draw-x_1.6s_var(--ease-soft)_both] bg-[#111214]" />
        <svg viewBox={WORDMARK_VIEWBOX} className="w-52 overflow-visible" aria-hidden>
          {/* Outline draws first; the fill settles in as the counter nears 100. */}
          <g
            fill="currentColor"
            stroke="currentColor"
            strokeWidth={2.5}
            strokeLinejoin="round"
            className="transition-[fill-opacity] duration-500 ease-[var(--ease-soft)]"
            style={{ fillOpacity: count >= 80 ? 1 : 0 }}
          >
            {WORDMARK_PATHS.map((d, i) => (
              <path
                key={d}
                d={d}
                pathLength={1}
                className="[stroke-dasharray:1] [stroke-dashoffset:1] animate-[draw-stroke_1.1s_var(--ease-soft)_forwards]"
                style={{ animationDelay: `${i * 90}ms` }}
              />
            ))}
          </g>
        </svg>
      </div>
      <p className="label mt-5 text-[#111214]/70">Know your numbers</p>
      <p className="absolute bottom-10 font-mono text-[11px] tabular-nums tracking-[0.1em]">
        {digits.map((d, i) => (
          <Digit key={i} value={d} />
        ))}
      </p>
    </div>
  );
}
