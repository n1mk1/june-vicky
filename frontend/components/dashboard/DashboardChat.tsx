"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import { PromptBar } from "@/components/app/PromptBar";
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
  /** Send a question to the panel (Preparation). */
  onAsk: (text: string) => void;
  onUndo: (widgetId: string) => Promise<boolean>;
  onShow: (widgetId: string) => void;
  onResetRange: () => void;
  onAttach?: (file: File) => void;
  attachBusy?: boolean;
  attachError?: string | null;
}

const KEEP = 3;

function Action({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return (
    <button type="button" onClick={onClick} className="text-[12px] text-ink underline underline-offset-2 hover:text-ember">
      {children}
    </button>
  );
}

/**
 * Vicky's dashboard chat: requests are mapped to a widget or a time range by the backend's offline
 * phrase mapper; every value in a widget is computed by code. Replies show as small cards under the
 * bar: "Widget added" with Undo, the zoom with Reset, missing data with the reason and an upload link.
 */
export function DashboardChat(props: DashboardChatProps) {
  const { dashboardId, engagementId, track, onResult, onAsk, onUndo, onShow, onResetRange, onAttach, attachBusy, attachError } = props;
  const guard = useAccessGuard();
  const [log, setLog] = useState<Exchange[]>([]);
  const [busy, setBusy] = useState(false);
  const [undone, setUndone] = useState<Set<string>>(new Set());

  const send = async (text: string) => {
    const id = Date.now();
    setLog((l) => [...l.slice(-(KEEP - 1)), { id, text, result: null, error: null }]);
    setBusy(true);
    try {
      const r = await track(
        apiPost<ChatResult>(`dashboards/${encodeURIComponent(dashboardId)}/chat`, { text }).then((res) => {
          onResult(res);
          return res;
        }),
      );
      setLog((l) => l.map((x) => (x.id === id ? { ...x, result: r } : x)));
    } catch (err) {
      if (!guard(err)) setLog((l) => l.map((x) => (x.id === id ? { ...x, error: errorText(err) } : x)));
    } finally {
      setBusy(false);
    }
  };

  const undo = async (wid: string) => {
    if (await onUndo(wid)) setUndone((s) => new Set(s).add(wid));
  };

  const card = (x: Exchange) => {
    const r = x.result;
    if (x.error) return <p className="text-[12.5px] text-ember">{x.error}</p>;
    if (!r) return <p className="text-[12.5px] text-dim">Working on it…</p>;
    const title = r.spec?.title;
    switch (r.kind) {
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
      case "question":
        return (
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="text-[12.5px] text-ink-2">{r.reply}</span>
            <Action onClick={() => onAsk(x.text)}>Ask the panel</Action>
          </div>
        );
      default:
        return <p className="text-[12.5px] text-ink-2">{r.reply}</p>;
    }
  };

  return (
    // On wide screens the replies float above the bar (over the orb's lower edge) so the hero grid
    // keeps its height; on narrow screens they stack under it.
    <div className="relative flex flex-col gap-2">
      <PromptBar
        label="Ask Vicky for a chart"
        placeholder="Ask for a chart, e.g. burn excluding credits as % of revenue by quarter"
        onSubmit={(t) => void send(t)}
        onAttach={onAttach}
        busy={busy || attachBusy}
        hint={
          attachError ? (
            <span className="text-ember">{attachError}</span>
          ) : (
            "Try “gross margin by quarter”, “zoom to the last 6 months” or “reset zoom”. Questions go to the panel."
          )
        }
      />
      {log.length > 0 && (
        // The bar spans one column more than the orb above it; stay within the orb's five.
        <div className="z-20 flex flex-col gap-1.5 lg:absolute lg:bottom-full lg:left-2 lg:right-[calc(100%/6+0.5rem)] lg:mb-2">
          <button
            type="button"
            onClick={() => setLog([])}
            className="self-end rounded-full border border-line bg-surface-solid px-2 py-0.5 text-[10.5px] text-ink-2 hover:text-ink"
          >
            Clear
          </button>
          <ol aria-live="polite" aria-label="Vicky's replies" className="flex flex-col gap-1.5">
            {log.map((x) => (
              <li
                key={x.id}
                className={cn(
                  "rounded-[14px] border bg-surface-solid/95 px-3 py-2 shadow-sm",
                  x.result?.kind === "missing" ? "border-dashed border-line-strong" : "border-line",
                )}
              >
                <p className="mb-1 truncate font-mono text-[10px] uppercase tracking-[-0.04em] text-dim">You · {x.text}</p>
                {card(x)}
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
