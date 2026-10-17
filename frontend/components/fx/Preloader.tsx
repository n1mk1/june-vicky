"use client";

import { useEffect, useState, type CSSProperties } from "react";
import { CornerMarks } from "@/components/ui/Panel";
import { VickyMark } from "@/components/ui/VickyMark";
import { cn } from "@/lib/utils";

const DURATION = 1600;

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

/** First-visit intro: a framed mark draws itself while a rolling counter reaches 100. */
export function Preloader() {
  const [count, setCount] = useState(0);
  const [phase, setPhase] = useState<"run" | "leave" | "gone">("run");

  useEffect(() => {
    const html = document.documentElement;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const finish = () => {
      html.dataset.preloaded = "";
      try {
        sessionStorage.setItem("vicky-preloaded", "1");
      } catch {
        // Without storage the intro simply plays again next visit.
      }
    };
    // Already shown this session, or motion is reduced: CSS keeps the overlay hidden.
    if ("preloaded" in html.dataset || reduced) {
      finish();
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
      document.documentElement.dataset.preloaded = "";
      try {
        sessionStorage.setItem("vicky-preloaded", "1");
      } catch {}
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
      <div className="relative flex size-40 items-center justify-center border border-[#111214]/15">
        <CornerMarks className="[&_span]:text-[#111214]/60" />
        <span className="absolute -top-px left-0 h-px w-full origin-left animate-[draw-x_1.6s_var(--ease-soft)_both] bg-[#111214]" />
        <VickyMark outline className="size-16" />
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
