"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { RollLabel } from "@/components/ui/RollLabel";
import { cn } from "@/lib/utils";

/**
 * `flagship` tabs (the dashboard, the prep court and the simulator) are the product. In black and
 * white they stand out by contrast: a full-ink outline, a bright label and a square marker, against
 * the dim outlines of the rest. The open tab is filled, like the landing's button.
 */
export const TABS = [
  { href: "/knowledge", label: "Knowledge base", flagship: false },
  { href: "/dashboard", label: "Dashboard", flagship: true },
  { href: "/preparation", label: "Preparation", flagship: true },
  { href: "/simulation", label: "Simulation", flagship: true },
  { href: "/areopagus", label: "Areopagus", flagship: false },
  { href: "/reports", label: "Reports", flagship: false },
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
            data-flagship={tab.flagship || undefined}
            className={cn(
              "group relative inline-flex h-8 shrink-0 items-center gap-1.5 rounded-[3px] border px-3.5 font-mono text-[11px] uppercase tracking-[0.02em] transition-colors duration-300",
              active
                ? "border-invert-bg bg-invert-bg text-invert-ink"
                : tab.flagship
                  ? "border-ink text-ink hover:bg-ink/10"
                  : "border-line-strong text-dim hover:border-ink-2 hover:text-ink-2",
            )}
          >
            {tab.flagship && (
              <span aria-hidden className={cn("size-1.5 shrink-0", active ? "bg-invert-ink" : "bg-ink")} />
            )}
            <RollLabel text={tab.label} />
            {active && (
              <span
                aria-hidden
                className="absolute -bottom-[11px] left-1/2 h-px w-6 -translate-x-1/2 bg-ink"
              />
            )}
          </Link>
        );
      })}
      {/* Hairline under the whole tab group, from the wireframe */}
      <span aria-hidden className="absolute right-6 bottom-0 left-6 h-px bg-line-strong" />
    </nav>
  );
}
