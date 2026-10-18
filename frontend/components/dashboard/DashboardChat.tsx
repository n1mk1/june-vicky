"use client";

import { BarChart3, MessageSquare, Search, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { PromptBar } from "@/components/app/PromptBar";
import { CitedText } from "@/components/ui/Footnote";
import { ApiError, apiPost } from "@/lib/api";
import { confirmHref } from "@/lib/kb";
import type { ChatResult } from "@/lib/types";
import { errorText, useAccessGuard } from "@/lib/use-api";
import { cn } from "@/lib/utils";

interface Exchange {
  id: number;
  text: string;
  result: ChatResult | null;
  error: string | null;
  /** The user's answer to a catch-all offer on this exchange (docs/08-RAG.md §Asking permission). */
  offer?: "running" | "declined" | "done" | "gone";
  offerResult?: ChatResult | null;
  offerError?: string | null;
}

interface DashboardChatProps {
  dashboardId: string;
  engagementId: string;
  /** "?currency=usd" when the dashboard shows another currency than the reporting one, else "". */
  query?: string;
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

/** Results that change the dashboard itself: the overlay steps aside so the change can be seen. */
const CHANGES = new Set(["widget_added", "exists", "time_range"]);
const STEP_ASIDE_MS = 2500;

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
 * every number; chart requests add a widget; "zoom to …" moves every chart. Sending a message opens
 * the conversation as an overlay above the bar, over a dimmed dashboard, so the widgets never give
 * up room to it. Esc, the close button or a click on the dashboard closes it; the thread is kept.
 */
export function DashboardChat(props: DashboardChatProps) {
  const { dashboardId, engagementId, query = "", track, onResult, onUndo, onShow, onResetRange, onAttach, attachBusy, attachError } = props;
  const guard = useAccessGuard();
  const [thread, setThread] = useState<Exchange[]>([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [undone, setUndone] = useState<Set<string>>(new Set());
  const [hovered, setHovered] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);
  const seq = useRef(0);
  const latest = thread.at(-1);

  const close = () => {
    setOpen(false);
    setHovered(false);
  };

  // Esc closes the overlay.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // Keep the newest exchange in view.
  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [thread, open]);

  // A widget added or a zoom changes the dashboard: step aside after a moment and point at it,
  // unless the pointer is on the overlay (reading, or about to press Undo).
  useEffect(() => {
    const r = latest?.result;
    if (!open || !r || latest.error || !CHANGES.has(r.kind) || hovered) return;
    const t = window.setTimeout(() => {
      setOpen(false);
      if (r.widget_id && r.kind !== "time_range") onShow(r.widget_id);
    }, STEP_ASIDE_MS);
    return () => window.clearTimeout(t);
  }, [latest, open, hovered, onShow]);

  const send = async (text: string) => {
    const id = ++seq.current;
    const patch = (p: Partial<Exchange>) => setThread((t) => t.map((x) => (x.id === id ? { ...x, ...p } : x)));
    setThread((t) => [...t, { id, text, result: null, error: null }]);
    setOpen(true);
    setBusy(true);
    try {
      const r = await track(
        apiPost<ChatResult>(`dashboards/${encodeURIComponent(dashboardId)}/chat${query}`, { text }).then((res) => {
          onResult(res);
          return res;
        }),
      );
      patch({ result: r });
    } catch (err) {
      if (!guard(err)) patch({ error: errorText(err) });
    } finally {
      setBusy(false);
    }
  };

  // The catch-all (Haiku over every note) runs only when the user presses "Search all notes".
  const answerOffer = async (x: Exchange, accept: boolean) => {
    const offer = x.result?.offer;
    if (!offer) return;
    const patch = (p: Partial<Exchange>) => setThread((t) => t.map((e) => (e.id === x.id ? { ...e, ...p } : e)));
    patch({ offer: accept ? "running" : "declined", offerError: null });
    try {
      const r = await apiPost<ChatResult | undefined>(
        `dashboards/${encodeURIComponent(dashboardId)}/chat/catch-all${query}`,
        { offer_id: offer.id, accept },
      );
      if (accept) patch({ offer: "done", offerResult: r ?? null });
    } catch (err) {
      if (guard(err)) return;
      if (!accept) return; // declining can't fail in a way worth showing
      const gone = err instanceof ApiError && err.status === 410;
      patch({ offer: "gone", offerError: gone ? "That offer expired. Ask the question again." : errorText(err) });
    }
  };

  const undo = async (wid: string) => {
    if (await onUndo(wid)) setUndone((s) => new Set(s).add(wid));
  };

  const show = (wid: string) => {
    close();
    onShow(wid);
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
            {r.offer && !x.offer && (
              <div
                data-testid="catch-all-offer"
                className="flex flex-col gap-2 rounded-[4px] border border-line bg-surface-solid/60 px-3 py-2.5"
              >
                <span className="text-[12.5px] leading-snug text-ink-2">{r.offer.prompt}</span>
                <span className="flex items-center gap-3">
                  <button
                    type="button"
                    onClick={() => void answerOffer(x, true)}
                    className="inline-flex items-center gap-1.5 rounded-[3px] border border-line-strong px-2.5 py-1 text-[12px] text-ink hover:border-ember hover:text-ember"
                  >
                    <Search className="size-3.5" strokeWidth={1.5} />
                    Search all notes
                  </button>
                  <button
                    type="button"
                    onClick={() => void answerOffer(x, false)}
                    className="text-[12px] text-ink-2 underline underline-offset-2 hover:text-ink"
                  >
                    No thanks
                  </button>
                </span>
              </div>
            )}
            {x.offer === "running" && (
              <p className="text-[12.5px] text-dim" data-testid="catch-all-running">
                Reading every note in your knowledge base…
              </p>
            )}
            {x.offer === "done" && x.offerResult && (
              <div className="flex flex-col gap-1 border-l border-line pl-3" data-testid="catch-all-answer">
                <span className="label">From all your notes</span>
                <p className="text-[13.5px] leading-relaxed text-ink">
                  <CitedText text={x.offerResult.reply} citations={x.offerResult.citations ?? []} />
                </p>
              </div>
            )}
            {x.offer === "gone" && x.offerError && <p className="text-[12.5px] text-ember">{x.offerError}</p>}
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
                    className="rounded-[3px] border border-line px-2.5 py-0.5 text-[11.5px] text-ink-2 hover:border-line-strong hover:text-ink"
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
                <Action onClick={() => show(r.widget_id!)}>Show</Action>
                <Action onClick={() => void undo(r.widget_id!)}>Undo</Action>
              </>
            )}
          </div>
        );
      case "exists":
        return (
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="text-[12.5px] text-ink-2">{r.reply}</span>
            {r.widget_id && <Action onClick={() => show(r.widget_id!)}>Show</Action>}
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
              href={confirmHref(engagementId, 2)}
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
    <div className={cn("relative flex flex-col gap-2", open && "z-50")} data-testid="dashboard-chat">
      {open &&
        createPortal(
          <div aria-hidden className="fixed inset-0 z-40 bg-black/45 backdrop-blur-[3px]" data-testid="chat-backdrop" onClick={close} />,
          document.body,
        )}
      {open && thread.length > 0 && (
        <section
          aria-label="Conversation with Vicky"
          data-testid="chat-thread"
          onPointerEnter={() => setHovered(true)}
          onPointerLeave={() => setHovered(false)}
          className="glass absolute inset-x-0 bottom-full mb-2 flex bg-surface-solid/95 max-h-[min(64vh,640px)] flex-col overflow-hidden rounded-[4px] shadow-[0_24px_80px_-24px_rgba(0,0,0,0.6)]"
        >
          <header className="flex shrink-0 items-center justify-between gap-3 border-b border-line px-4 py-2.5">
            <span className="label">Ask Vicky</span>
            <span className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => {
                  setThread([]);
                  close();
                }}
                className="text-[11.5px] text-ink-2 underline underline-offset-2 hover:text-ink"
              >
                Clear
              </button>
              <button
                type="button"
                onClick={close}
                aria-label="Close the conversation"
                className="-mr-1 flex size-6 items-center justify-center rounded-full text-ink-2 hover:text-ink"
              >
                <X className="size-3.5" strokeWidth={1.5} />
              </button>
            </span>
          </header>
          <div ref={scroller} aria-live="polite" className="scroll-thin flex min-h-0 flex-col gap-5 overflow-y-auto px-4 py-4">
            {thread.map((x) => (
              <article
                key={x.id}
                data-testid={x === latest ? "chat-reply" : "chat-exchange"}
                className={cn("flex flex-col gap-2", x.result?.kind === "missing" && "rounded-[4px] border border-dashed border-line p-3")}
              >
                <p className="max-w-[85%] self-end rounded-[4px] rounded-br-[4px] border border-line bg-surface-solid/70 px-3 py-1.5 text-[12.5px] text-ink">
                  {x.text}
                </p>
                {body(x)}
              </article>
            ))}
          </div>
        </section>
      )}
      <PromptBar
        label="Ask Vicky about your data"
        placeholder="Ask anything about your data, e.g. which month had the highest burn?"
        onSubmit={(t) => void send(t)}
        maxLength={500}
        onAttach={onAttach}
        busy={busy || attachBusy}
        hint={
          attachError ? (
            <span className="text-ember">{attachError}</span>
          ) : !open && thread.length > 0 ? (
            <button
              type="button"
              onClick={() => setOpen(true)}
              className="inline-flex items-center gap-1.5 text-ink-2 underline underline-offset-2 hover:text-ink"
            >
              <MessageSquare className="size-3.5" strokeWidth={1.5} />
              Show conversation ({thread.length})
            </button>
          ) : (
            "Ask a question (“how is ARR calculated?”), ask for a chart (“show gross margin by quarter”) or zoom (“last 6 months”)."
          )
        }
      />
    </div>
  );
}
