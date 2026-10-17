"use client";

import Link from "next/link";
import { errorText } from "@/lib/use-api";
import { cn } from "@/lib/utils";
import { useActiveEngagement } from "./EngagementProvider";

/** Header pill: which company's source of truth every tab is using (UI doc §2). */
export function StatusPill({ className }: { className?: string }) {
  const { engagement, loading, error } = useActiveEngagement();
  const base = "inline-flex h-8 max-w-full items-center gap-2 rounded-full border px-3.5 text-[12px] transition-colors";

  if (engagement === undefined && error && !loading) {
    return (
      <span className={cn(base, "border-dashed border-line-strong text-ink-2", className)} title={errorText(error)}>
        <span className="size-1.5 rounded-full bg-ember" aria-hidden />
        API unreachable
      </span>
    );
  }

  if (engagement === undefined) {
    return (
      <span className={cn(base, "border-line text-dim", className)}>
        <span className="size-1.5 rounded-full bg-dim animate-[pulse-dot_1.2s_ease-in-out_infinite]" aria-hidden />
        Checking source of truth
      </span>
    );
  }

  if (!engagement) {
    return (
      <Link href="/intake" className={cn(base, "border-invert-bg bg-invert-bg text-invert-ink hover:opacity-90", className)}>
        <span className="size-1.5 rounded-full bg-ember" aria-hidden />
        No source of truth · Load data
      </Link>
    );
  }

  const company = engagement.profile?.name || engagement.name;
  return (
    <Link
      href="/intake"
      title="Source of truth. Open to load different data."
      className={cn(base, "border-line text-ink-2 hover:border-line-strong hover:text-ink", className)}
    >
      <span className="size-1.5 shrink-0 rounded-full bg-ember animate-[pulse-dot_2.4s_ease-in-out_infinite]" aria-hidden />
      <span className="truncate">
        <span className="text-ink">{company}</span> · confirmed
      </span>
    </Link>
  );
}
