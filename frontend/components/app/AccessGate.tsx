"use client";

import { ArrowRight } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { CornerMarks } from "@/components/ui/Panel";
import { RollLabel } from "@/components/ui/RollLabel";
import { ApiError, enterAccessCode } from "@/lib/api";
import { errorText } from "@/lib/use-api";
import { cn } from "@/lib/utils";

/** Only same-site paths are allowed as the return target; without one, start in the knowledge base. */
function safeNext(raw: string | null): string {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//") || raw.startsWith("/access") || raw === "/") return "/knowledge";
  return raw;
}

/** FR-14: one shared code in, signed cookie out, back to where the user was going. */
export function AccessGate() {
  const router = useRouter();
  const next = safeNext(useSearchParams().get("next"));
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [shakes, setShakes] = useState(0);

  const submit = async () => {
    const value = code.trim();
    if (!value || busy) return;
    setBusy(true);
    setError(null);
    try {
      await enterAccessCode(value);
      router.replace(next);
      router.refresh();
    } catch (err) {
      setBusy(false);
      setShakes((n) => n + 1);
      if (err instanceof ApiError && err.status === 401) setError("That code didn't work.");
      else if (err instanceof ApiError && err.status === 429) setError("Too many tries. Wait a minute and try again.");
      else setError(errorText(err));
    }
  };

  return (
    <form
      key={shakes}
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
      className={cn(
        "glass relative flex w-full max-w-[380px] flex-col gap-5 rounded-[4px] p-6",
        shakes > 0 && "animate-[shake_0.42s_var(--ease-soft)]",
      )}
    >
      <CornerMarks />
      <div className="flex flex-col gap-2">
        <span className="label">Access</span>
        <h1 className="display text-[clamp(32px,4vw,44px)]">Enter the access code.</h1>
        <p className="text-[13px] leading-snug text-ink-2">The code was shared with your team. It keeps this workspace private.</p>
      </div>
      <div className="flex flex-col gap-2">
        <label htmlFor="access-code" className="sr-only">
          Access code
        </label>
        <div className="flex items-center gap-2 rounded-[4px] border border-line bg-surface-solid/60 p-1.5 focus-within:border-line-strong">
          <input
            id="access-code"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            type="password"
            autoComplete="current-password"
            autoFocus
            placeholder="Access code"
            aria-invalid={!!error}
            aria-describedby={error ? "access-error" : undefined}
            className="h-8 min-w-0 flex-1 bg-transparent px-2 text-[14px] text-ink placeholder:text-dim focus:outline-none focus-visible:outline-none"
          />
          <button
            type="submit"
            disabled={!code.trim() || busy}
            className="group inline-flex h-8 shrink-0 items-center gap-1.5 rounded-[3px] bg-invert-bg px-3.5 font-mono text-[11px] uppercase tracking-[0.02em] text-invert-ink transition-opacity disabled:opacity-40"
          >
            <RollLabel text={busy ? "Checking" : "Enter"} />
            <ArrowRight className="size-3.5" strokeWidth={1.75} />
          </button>
        </div>
        <p id="access-error" role="alert" className="min-h-[18px] text-[12px] text-ember">
          {error}
        </p>
      </div>
    </form>
  );
}
