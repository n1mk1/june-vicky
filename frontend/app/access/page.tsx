import type { Metadata } from "next";
import { Suspense } from "react";
import { AccessGate } from "@/components/app/AccessGate";
import { Lockup } from "@/components/app/Lockup";
import { ThemeToggle } from "@/components/app/ThemeToggle";
import { LightStreaks } from "@/components/fx/LightStreaks";

export const metadata: Metadata = { title: "Access" };

export default function AccessPage() {
  return (
    <main className="relative isolate flex min-h-dvh flex-col overflow-hidden">
      <LightStreaks count={28} />
      <header className="relative z-10 flex flex-wrap items-center gap-3 px-4 pt-4 md:px-6">
        <Lockup />
        <ThemeToggle />
      </header>
      <section className="relative z-10 flex flex-1 items-center justify-center px-4 py-10">
        {/* The form reads ?next= from the URL, so it renders on the client inside Suspense. */}
        <Suspense fallback={<div className="glass h-[248px] w-full max-w-[380px] rounded-[20px]" />}>
          <AccessGate />
        </Suspense>
      </section>
      <p className="relative z-10 pb-6 text-center text-[11.5px] text-dim">Synthetic data. No investment advice.</p>
    </main>
  );
}
