import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export const inputCls =
  "h-9 w-full rounded-[3px] border border-line bg-surface-solid/60 px-2.5 text-[13.5px] text-ink placeholder:text-dim transition-colors focus:border-line-strong focus:outline-none disabled:opacity-50";

export const selectCls = cn(inputCls, "pr-1.5");

/** Label above a control, with an optional hint. */
export function Field({
  label,
  htmlFor,
  hint,
  className,
  children,
}: {
  label: string;
  htmlFor?: string;
  hint?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-1.5", className)}>
      <label htmlFor={htmlFor} className="text-[11.5px] text-ink-2">
        {label}
      </label>
      {children}
      {hint && <p className="text-[11px] text-dim">{hint}</p>}
    </div>
  );
}
