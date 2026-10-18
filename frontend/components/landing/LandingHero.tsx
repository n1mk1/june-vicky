"use client";

import Image from "next/image";
import Link from "next/link";
import { useEffect } from "react";
import { AsciiV } from "@/components/fx/AsciiV";

/**
 * Landing: black and white whatever the app theme. A small tag, the JUNE × VICKY logo as the
 * title, one line under it, a big flickering V drawn in digits, and one way in.
 */
export function LandingHero() {
  // Warm a sleeping free-tier API while the page loads.
  useEffect(() => {
    void fetch("/api/health", { cache: "no-store" }).catch(() => {});
  }, []);

  return (
    <main data-theme="dark" className="relative isolate flex min-h-dvh flex-col items-center bg-black px-4 pt-6 pb-8 text-white md:pt-8">
      <p className="flex items-center gap-2 font-mono text-[10.5px] uppercase tracking-[-0.02em] animate-[rise_0.9s_var(--ease-soft)_both]">
        <span aria-hidden className="size-1.5 bg-ember" />
        <span className="text-white">Vicky</span>
        <span className="border border-white/25 bg-white/10 px-2 py-0.5 text-white/70">AI venture capitalist</span>
      </p>

      <h1 className="mt-5 animate-[rise_0.9s_var(--ease-soft)_both] [animation-delay:120ms]">
        <span className="sr-only">JUNE × VICKY</span>
        <Image
          src="/brand/June_x_Vicky_white.svg"
          alt=""
          width={1454}
          height={248}
          unoptimized
          priority
          className="h-[clamp(34px,6vw,76px)] w-auto"
        />
      </h1>
      <p className="mt-4 text-center text-[clamp(14px,1.5vw,18px)] tracking-[-0.01em] text-white/70 animate-[rise_0.9s_var(--ease-soft)_both] [animation-delay:220ms]">
        Know Your Numbers Before They Do
      </p>

      <div className="relative my-3 min-h-[320px] w-full max-w-[900px] flex-1 animate-[rise_1.2s_var(--ease-soft)_both] [animation-delay:320ms]">
        <AsciiV className="absolute inset-0" />
      </div>

      <Link
        href="/knowledge"
        className="inline-flex h-11 items-center justify-center rounded-[3px] border border-white bg-white px-7 font-mono text-[12.5px] uppercase tracking-[0.02em] text-black transition-colors duration-200 hover:border-ember hover:bg-ember hover:text-black animate-[rise_0.9s_var(--ease-soft)_both] [animation-delay:450ms]"
      >
        Get started
      </Link>
      <p className="mt-5 text-[11px] text-white/50">No investment advice.</p>
    </main>
  );
}
