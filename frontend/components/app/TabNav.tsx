"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { RollLabel } from "@/components/ui/RollLabel";
import { cn } from "@/lib/utils";

export const TABS = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/preparation", label: "Preparation" },
  { href: "/simulation", label: "Simulation" },
  { href: "/areopagus", label: "Areopagus" },
  { href: "/reports", label: "Reports" },
] as const;

/** Tabs with the current one marked. Reads the URL, so the header renders it inside Suspense. */
export function TabNav() {
  return <Tabs pathname={usePathname()} />;
}

/** Static shell used while the pathname streams in (no tab marked). */
export function TabNavFallback() {
  return <Tabs pathname="" />;
}

function Tabs({ pathname }: { pathname: string }) {
  return (
    <nav aria-label="Sections" className="relative flex w-max items-center gap-1.5 pb-2.5 md:mx-auto">
      {TABS.map((tab) => {
        const active = pathname.startsWith(tab.href);
        return (
          <Link
            key={tab.href}
            href={tab.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "group relative inline-flex h-8 shrink-0 items-center rounded-full border px-3.5 font-display text-[12.5px] uppercase tracking-[-0.02em] transition-colors duration-300",
              active ? "border-invert-bg bg-invert-bg text-invert-ink" : "border-line-strong text-ink-2 hover:border-ink hover:text-ink",
            )}
          >
            <RollLabel text={tab.label} />
            {active && <span aria-hidden className="absolute -bottom-[11px] left-1/2 h-px w-6 -translate-x-1/2 bg-ember" />}
          </Link>
        );
      })}
      {/* Hairline under the whole tab group, from the wireframe */}
      <span aria-hidden className="absolute right-6 bottom-0 left-6 h-px bg-line-strong" />
    </nav>
  );
}
