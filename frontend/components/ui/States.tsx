import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Mono label with a pulse dot: the one loading treatment (UI doc §5). */
export function Loading({ label = "Loading", className }: { label?: string; className?: string }) {
  return (
    <p role="status" className={cn("flex items-center gap-2 label", className)}>
      <span className="size-1.5 rounded-full bg-ink animate-[pulse-dot_1.2s_ease-in-out_infinite]" aria-hidden />
      {label}
    </p>
  );
}

/** Error line with an optional retry. */
export function ErrorNote({ message, onRetry, className }: { message: string; onRetry?: () => void; className?: string }) {
  return (
    <div role="alert" className={cn("flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-ink-2", className)}>
      <span className="size-1.5 shrink-0 rounded-full bg-ember" aria-hidden />
      <span>{message}</span>
      {onRetry && (
        <button type="button" onClick={onRetry} className="text-ink underline underline-offset-2 hover:text-ember">
          Try again
        </button>
      )}
    </div>
  );
}

/** Centred empty state inside a panel or page. */
export function EmptyState({
  label,
  title,
  body,
  children,
  className,
}: {
  label?: string;
  title: string;
  body?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-3 p-6 text-center", className)}>
      {label && <span className="label">{label}</span>}
      <p className="display max-w-[18ch] text-[clamp(28px,3.4vw,44px)]">{title}</p>
      {body && <p className="max-w-[46ch] text-[13.5px] leading-snug text-ink-2">{body}</p>}
      {children && <div className="mt-2 flex flex-wrap items-center justify-center gap-2">{children}</div>}
    </div>
  );
}
