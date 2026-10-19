import type { Metadata } from "next";
import Image from "next/image";
import { Suspense } from "react";
import { AccessGate } from "@/components/app/AccessGate";

export const metadata: Metadata = { title: "Access" };

export default function AccessPage() {
  return (
    // Same black and white as the landing, whatever the app theme: data-theme pins the tokens.
    <main data-theme="dark" className="relative isolate flex min-h-dvh flex-col items-center bg-black px-4 pt-6 pb-8 text-white md:pt-8">
      <p className="flex items-center gap-2 font-mono text-[10.5px] uppercase tracking-[-0.02em]">
        <span aria-hidden className="size-1.5 bg-ember" />
        <span>Vik</span>
        <span className="border border-white/25 bg-white/10 px-2 py-0.5 text-white/70">AI venture capitalist</span>
      </p>
      <Image
        src="/brand/Vik_Logo_white.svg"
        alt="VIK"
        width={459}
        height={248}
        unoptimized
        priority
        className="mt-5 h-[clamp(36px,5vw,64px)] w-auto"
      />
      <section className="flex w-full flex-1 items-center justify-center py-10">
        {/* The form reads ?next= from the URL, so it renders on the client inside Suspense. */}
        <Suspense fallback={<div className="glass h-[248px] w-full max-w-[380px] rounded-[4px]" />}>
          <AccessGate />
        </Suspense>
      </section>
      <p className="text-[11px] text-white/50">No investment advice.</p>
    </main>
  );
}
