import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** "+" marks sitting just outside each corner of the parent (which must be `relative`). */
export function CornerMarks({ className }: { className?: string }) {
  const mark = "pointer-events-none absolute size-[9px] text-dim";
  const plus = (
    <svg viewBox="0 0 9 9" className="size-full" aria-hidden>
      <path d="M4.5 0v9M0 4.5h9" stroke="currentColor" strokeWidth="1" />
    </svg>
  );
  return (
    <span className={cn("pointer-events-none", className)} aria-hidden>
      <span className={cn(mark, "-top-[5px] -left-[5px]")}>{plus}</span>
      <span className={cn(mark, "-top-[5px] -right-[5px]")}>{plus}</span>
      <span className={cn(mark, "-bottom-[5px] -left-[5px]")}>{plus}</span>
      <span className={cn(mark, "-right-[5px] -bottom-[5px]")}>{plus}</span>
    </span>
  );
}

interface PanelProps {
  title?: string;
  aside?: ReactNode;
  marks?: boolean;
  className?: string;
  bodyClassName?: string;
  /**
   * For a body that scrolls: names it and puts it in the tab order, so keyboard users can scroll it
   * even when nothing inside is focusable (WCAG 2.1.1).
   */
  scrollLabel?: string;
  children: ReactNode;
}

export function Panel({ title, aside, marks, className, bodyClassName, scrollLabel, children }: PanelProps) {
  return (
    <section className={cn("glass relative flex min-h-0 flex-col rounded-[4px]", className)}>
      {marks && <CornerMarks />}
      {(title || aside) && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
          {title && (
            <h2 className="label min-w-0 truncate" title={title}>
              {title}
            </h2>
          )}
          {aside}
        </header>
      )}
      <div
        className={cn("min-h-0 flex-1", bodyClassName)}
        {...(scrollLabel ? { tabIndex: 0, role: "region", "aria-label": scrollLabel } : {})}
      >
        {children}
      </div>
    </section>
  );
}
