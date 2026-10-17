"use client";

import { BarChart3, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { PromptBar } from "@/components/app/PromptBar";
import { CitedText } from "@/components/ui/Footnote";
import { apiPost } from "@/lib/api";
import type { ChatResult } from "@/lib/types";
import { errorText, useAccessGuard } from "@/lib/use-api";
import { cn } from "@/lib/utils";

interface Exchange {
  id: number;
  text: string;
  result: ChatResult | null;
  error: string | null;
}

interface DashboardChatProps {
  dashboardId: string;
  engagementId: string;
  /** Marks a request from this tab so its own realtime event isn't mistaken for another tab's. */
  track: <T>(p: Promise<T>) => Promise<T>;
  /** Apply the dashboard a request changed (widget added, time range set). */
  onResult: (r: ChatResult) => void;
  onUndo: (widgetId: string) => Promise<boolean>;
  onShow: (widgetId: string) => void;
  onResetRange: () => void;
  onAttach?: (file: File) => void;
  attachBusy?: boolean;
  attachError?: string | null;
}

/** Confirmations (a widget added, a zoom) clear themselves; answers stay until the next message. */
const CONFIRM_MS = 6000;

function Action({ onClick, children, icon }: { onClick: () => void; children: ReactNode; icon?: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1 text-[12px] text-ink underline underline-offset-2 hover:text-ember"
    >
      {icon}
      {children}
    </button>
  );
}

/**
 * "Ask Vicky" on the dashboard. Questions about the data are answered by code with a footnote on
 * every number; chart requests add a widget; "zoom to …" moves every chart. Only the latest
 * exchange is shown, docked above the bar in the page flow, so it never covers a widget: the
 * widgets give up the room instead.
 */
export function DashboardChat(props: DashboardChatProps) {
  const { dashboardId, engagementId, track, onResult, onUndo, onShow, onResetRange, onAttach, attachBusy, attachError } = props;
  const guard = useAccessGuard();
  const [current, setCurrent] = useState<Exchange | null>(null);
  const [busy, setBusy] = useState(false);
  const [undone, setUndone] = useState<Set<string>>(new Set());
  const timer = useRef<number | null>(null);

  // Confirmations fade after a few seconds; an answer stays until the next message or the close button.
  useEffect(() => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    const k = current?.result?.kind;
    if (!current || current.error || !k || k === "answer" || k === "missing" || k === "none") return;
    timer.current = window.setTimeout(() => setCurrent((c) => (c?.id === current.id ? null : c)), CONFIRM_MS);
    return () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    };
  }, [current]);

  const send = async (text: string) => {
    const id = Date.now();
    setCurrent({ id, text, result: null, error: null });
    setBusy(true);
    try {
      const r = await track(
        apiPost<ChatResult>(`dashboards/${encodeURIComponent(dashboardId)}/chat`, { text }).then((res) => {
          onResult(res);
          return res;
        }),
      );
      setCurrent((c) => (c?.id === id ? { ...c, result: r } : c));
    } catch (err) {
      if (!guard(err)) setCurrent((c) => (c?.id === id ? { ...c, error: errorText(err) } : c));
    } finally {
      setBusy(false);
    }
  };

  const undo = async (wid: string) => {
    if (await onUndo(wid)) setUndone((s) => new Set(s).add(wid));
  };

  const body = (x: Exchange) => {
    const r = x.result;
    if (x.error) return <p className="text-[13px] text-ember">{x.error}</p>;
    if (!r) return <p className="text-[13px] text-dim">Working it out from your data…</p>;
    const title = r.spec?.title;
    switch (r.kind) {
      case "answer":
        return (
          <div className="flex flex-col gap-2">
            <p className="text-[13.5px] leading-relaxed text-ink" data-testid="chat-answer">
              <CitedText text={r.reply} citations={r.citations ?? []} />
            </p>
            {(r.chart || !!r.suggestions?.length) && (
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                {r.chart && (
                  <Action onClick={() => void send(r.chart!)} icon={<BarChart3 className="size-3.5" strokeWidth={1.5} />}>
                    Chart it
                  </Action>
                )}
                {(r.suggestions ?? []).map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => void send(s)}
                    className="rounded-full border border-line px-2.5 py-0.5 text-[11.5px] text-ink-2 hover:border-line-strong hover:text-ink"
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
          </div>
        );
      case "widget_added":
        return (
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="label">{r.widget_id && undone.has(r.widget_id) ? "Widget removed" : "Widget added"}</span>
            <span className="text-[12.5px] text-ink">{title}</span>
            {r.widget_id && !undone.has(r.widget_id) && (
              <>
                <Action onClick={() => onShow(r.widget_id!)}>Show</Action>
                <Action onClick={() => void undo(r.widget_id!)}>Undo</Action>
              </>
            )}
          </div>
        );
      case "exists":
        return (
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="text-[12.5px] text-ink-2">{r.reply}</span>
            {r.widget_id && <Action onClick={() => onShow(r.widget_id!)}>Show</Action>}
          </div>
        );
      case "time_range":
        return (
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="label">{r.time_range ? "Zoomed" : "Full range"}</span>
            <span className="text-[12.5px] text-ink">{r.time_range?.label ?? "Every chart shows all periods."}</span>
            {r.time_range && <Action onClick={onResetRange}>Reset</Action>}
          </div>
        );
      case "missing":
        return (
          <div className="flex flex-col gap-1">
            <span className="label">Not in your data yet{title ? ` · ${title}` : ""}</span>
            <span className="text-[12.5px] leading-snug text-ink-2">{r.reply}</span>
            {!!r.missing?.needs?.length && (
              <span className="font-mono text-[10px] uppercase tracking-[-0.04em] text-dim">
                Needs: {r.missing.needs.join(", ").replace(/_/g, " ")}
              </span>
            )}
            <Link
              href={`/intake?e=${encodeURIComponent(engagementId)}&step=2`}
              className="self-start text-[12px] text-ink underline underline-offset-2 hover:text-ember"
            >
              Upload
            </Link>
          </div>
        );
      default:
        return <p className="text-[12.5px] text-ink-2">{r.reply}</p>;
    }
  };

  return (
    <div className="flex flex-col gap-2" data-testid="dashboard-chat">
      {current && (
        <section
          aria-live="polite"
          aria-label="Vicky's reply"
          data-testid="chat-reply"
          className={cn(
            "glass scroll-thin relative max-h-[28vh] overflow-y-auto rounded-[16px] px-4 py-3",
            current.result?.kind === "missing" && "border-dashed",
          )}
        >
          <div className="mb-1.5 flex items-start justify-between gap-3">
            <p className="truncate font-mono text-[10px] uppercase tracking-[-0.04em] text-dim">You asked · {current.text}</p>
            <button
              type="button"
              onClick={() => setCurrent(null)}
              aria-label="Close the reply"
              className="-mt-0.5 -mr-1 flex size-6 shrink-0 items-center justify-center rounded-full text-ink-2 hover:text-ink"
            >
              <X className="size-3.5" strokeWidth={1.5} />
            </button>
          </div>
          {body(current)}
        </section>
      )}
      <PromptBar
        label="Ask Vicky about your data"
        placeholder="Ask anything about your data, e.g. which month had the highest burn?"
        onSubmit={(t) => void send(t)}
        onAttach={onAttach}
        busy={busy || attachBusy}
        hint={
          attachError ? (
            <span className="text-ember">{attachError}</span>
          ) : (
            "Ask a question (“how is ARR calculated?”), ask for a chart (“show gross margin by quarter”) or zoom (“last 6 months”)."
          )
        }
      />
    </div>
  );
}
