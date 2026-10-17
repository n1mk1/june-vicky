"use client";

import { BookOpen, LayoutTemplate } from "lucide-react";
import { useEffect, useRef } from "react";
import { BlurText } from "@/components/ui/BlurText";
import { VcGlyph } from "@/components/ui/VcGlyph";
import { PANEL, type Dim, type Msg } from "@/lib/panel";
import { cn } from "@/lib/utils";
import { ClaimChip } from "./ClaimChip";

export type FeedFilter = "all" | "score" | "slide" | "knowledge";

export const FILTERS: { value: FeedFilter; label: string }[] = [
  { value: "all", label: "Everything" },
  { value: "score", label: "Feedback & scoring" },
  { value: "slide", label: "Slide design" },
  { value: "knowledge", label: "Knowledge" },
];

function DimBars({ dims }: { dims: Dim[] }) {
  return (
    <dl className="grid grid-cols-5 gap-2">
      {dims.map((d) => (
        <div key={d.label} className="flex flex-col gap-1">
          <dt className="truncate text-[10.5px] text-ink-2">{d.label}</dt>
          <dd className="flex items-center gap-1.5">
            <span className="relative h-[3px] flex-1 overflow-hidden rounded-full bg-line">
              {d.value !== null && (
                <span
                  className={cn("absolute inset-y-0 left-0 rounded-full", d.value < 2.5 ? "bg-ember" : "bg-ink")}
                  style={{ width: `${(d.value / 5) * 100}%` }}
                />
              )}
            </span>
            <span className="w-6 text-right font-mono text-[10px] tabular-nums text-ink-2">{d.value ?? "–"}</span>
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Card({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div className="ml-10 flex flex-col gap-2.5 rounded-[14px] border border-line bg-surface-solid/50 p-3.5">
      <span className="flex items-center gap-2 text-[11.5px] text-ink-2">
        {icon}
        {title}
      </span>
      {children}
    </div>
  );
}

function Message({ msg, fresh }: { msg: Msg; fresh: boolean }) {
  switch (msg.kind) {
    case "vc": {
      const vc = PANEL.find((p) => p.id === msg.vc);
      return (
        <div className="flex gap-3">
          <VcGlyph glyph={vc?.glyph ?? "custom"} />
          <div className="flex min-w-0 flex-col gap-1">
            <span className="text-[11.5px] text-ink-2">
              <span className="font-display text-[14px] tracking-[-0.03em] text-ink">{vc?.name ?? "Investor"}</span> · {vc?.firm}
            </span>
            <p className="max-w-[62ch] font-display text-[clamp(17px,1.5vw,21px)] leading-[1.2] tracking-[-0.03em]">
              {fresh ? <BlurText text={msg.text} /> : msg.text}
            </p>
          </div>
        </div>
      );
    }
    case "founder":
      return (
        <div className="ml-10 flex flex-col gap-1 border-l border-line-strong pl-3">
          <span className="text-[11.5px] text-ink-2">You</span>
          <p className="max-w-[62ch] text-[14px] leading-snug">{msg.text}</p>
        </div>
      );
    case "score":
      return (
        <Card icon={<span className="size-1.5 rounded-full bg-ink" />} title="Feedback & scoring">
          {msg.claim && (
            <span className="flex flex-wrap items-center gap-2 text-[12.5px]">
              <ClaimChip status={msg.claim.status} />
              <span className="text-ink-2">{msg.claim.text}</span>
            </span>
          )}
          <DimBars dims={msg.dims} />
          <p className="max-w-[64ch] text-[13px] leading-snug text-ink-2">{msg.note}</p>
        </Card>
      );
    case "slide":
      return (
        <Card icon={<LayoutTemplate className="size-3.5" strokeWidth={1.5} />} title={`Slide ${msg.slide} · ${msg.title}`}>
          <p className="max-w-[64ch] text-[13px] leading-snug">{msg.note}</p>
        </Card>
      );
    case "knowledge":
      return (
        <Card icon={<BookOpen className="size-3.5" strokeWidth={1.5} />} title={`Knowledge · ${msg.term}`}>
          <p className="max-w-[64ch] text-[13px] leading-snug">{msg.text}</p>
          <span className="font-mono text-[9.5px] uppercase tracking-[-0.04em] text-dim">{msg.source}</span>
        </Card>
      );
  }
}

interface ChatFeedProps {
  messages: Msg[];
  filter: FeedFilter;
  freshFrom: number;
  typing?: string;
}

export function ChatFeed({ messages, filter, freshFrom, typing }: ChatFeedProps) {
  const end = useRef<HTMLDivElement>(null);
  const mounted = useRef(false);
  const shown = filter === "all" ? messages : messages.filter((m) => m.kind === filter);

  // Follow new messages, but open at the top of the thread.
  useEffect(() => {
    if (!mounted.current) {
      mounted.current = true;
      return;
    }
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, typing]);

  return (
    <div className="flex flex-col gap-5 p-4 md:p-5" aria-live="polite">
      {shown.length === 0 && <p className="text-[13px] text-ink-2">Nothing in this view yet. Answer a question to get feedback here.</p>}
      {shown.map((m) => (
        <Message key={m.id} msg={m} fresh={messages.indexOf(m) >= freshFrom} />
      ))}
      {typing && filter === "all" && (
        <p className="ml-10 text-[12px] text-dim">
          {PANEL.find((p) => p.id === typing)?.name} is thinking
          <span className="animate-[pulse-dot_1s_ease-in-out_infinite]">…</span>
        </p>
      )}
      <div ref={end} />
    </div>
  );
}
