"use client";

import { BookOpen, FileText, LayoutTemplate } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef } from "react";
import { SourceChip } from "@/components/dashboard/SourceChip";
import { BlurText } from "@/components/ui/BlurText";
import { CitedText } from "@/components/ui/Footnote";
import { CornerMarks } from "@/components/ui/Panel";
import { VcGlyph, type Glyph } from "@/components/ui/VcGlyph";
import type { Citation, ClaimStatus, Figure, KnowledgeVerdict, LineReview, Score } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ClaimChip } from "./ClaimChip";
import { KnowledgeChip } from "./KnowledgeChip";

export type FeedFilter = "all" | "score" | "slide" | "knowledge";

export const FILTERS: { value: FeedFilter; label: string }[] = [
  { value: "all", label: "Everything" },
  { value: "score", label: "Feedback & scoring" },
  { value: "slide", label: "Slide design" },
  { value: "knowledge", label: "Knowledge" },
];

export interface Dim {
  label: string;
  value: number | null;
  /** Scale top: 5 for judge dimensions (default), 1 for accuracy (shown as a percentage). */
  max?: number;
}

function dimText(d: Dim): string {
  if (d.value === null) return "–";
  if (d.max === 1) return `${Math.round(d.value * 100)}%`;
  return Number.isInteger(d.value) ? String(d.value) : d.value.toFixed(1);
}

export interface FeedClaim {
  status: ClaimStatus;
  text: string;
  explanation?: string;
}

export type FeedItem =
  | {
      id: string;
      kind: "vc";
      name: string;
      firm?: string;
      glyph: Glyph;
      text: string;
      citations?: Citation[];
      chair?: boolean;
      /** A question testing whether the founder knows their own notes. */
      knowledgeCheck?: boolean;
      review?: LineReview | null;
    }
  | { id: string; kind: "founder"; text: string; claims?: FeedClaim[] }
  | { id: string; kind: "score"; dims: Dim[]; note?: string; claims?: FeedClaim[]; rationale?: Score["rationale"] }
  | { id: string; kind: "coach"; text: string; citations?: Citation[] }
  | { id: string; kind: "slide"; slide: number; title: string; note: string }
  | { id: string; kind: "knowledge"; verdict: KnowledgeVerdict; text: string; citations?: Citation[]; source?: string }
  | { id: string; kind: "report"; reportId: string };

const FILTER_KINDS: Record<FeedFilter, FeedItem["kind"][] | null> = {
  all: null,
  score: ["score", "coach"],
  slide: ["slide"],
  knowledge: ["knowledge"],
};

function DimBars({ dims }: { dims: Dim[] }) {
  return (
    <dl className="grid grid-cols-3 gap-2 sm:grid-cols-5">
      {dims.map((d) => {
        const max = d.max ?? 5;
        const frac = d.value === null ? 0 : Math.max(0, Math.min(max, d.value)) / max;
        return (
        <div key={d.label} className="flex flex-col gap-1">
          <dt className="truncate text-[10.5px] text-ink-2">{d.label}</dt>
          <dd className="flex items-center gap-1.5">
            <span className="relative h-[3px] flex-1 overflow-hidden rounded-full bg-line">
              {d.value !== null && (
                <span
                  className={cn("absolute inset-y-0 left-0 rounded-full", frac < 0.5 ? "bg-ember" : "bg-ink")}
                  style={{ width: `${frac * 100}%` }}
                />
              )}
            </span>
            <span className="w-8 text-right font-mono text-[10px] tabular-nums text-ink-2">{dimText(d)}</span>
          </dd>
        </div>
        );
      })}
    </dl>
  );
}

export { DimBars };

function Card({ icon, title, children, className }: { icon: React.ReactNode; title: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("relative ml-10 flex flex-col gap-2.5 rounded-[4px] border border-line bg-surface-solid/50 p-3.5", className)}>
      <span className="flex items-center gap-2 text-[11.5px] text-ink-2">
        {icon}
        {title}
      </span>
      {children}
    </div>
  );
}

function Claims({ claims }: { claims: FeedClaim[] }) {
  return (
    <ul className="flex flex-col gap-1.5">
      {claims.map((c, i) => (
        <li key={i} className="flex flex-wrap items-center gap-2 text-[12.5px]">
          <ClaimChip status={c.status} />
          <span className="text-ink-2">&ldquo;{c.text}&rdquo;</span>
          {c.explanation && <span className="text-[12px] text-ink-2">{c.explanation}</span>}
        </li>
      ))}
    </ul>
  );
}

function figureExplain(f: Figure) {
  return { label: f.label, display: f.display, value: f.value, unit: f.unit, period: f.period, formula: f.formula, source: f.source, kind: f.kind };
}

function Rationale({ r }: { r: Score["rationale"] }) {
  return (
    <div className="flex flex-col gap-2 text-[13px] leading-snug">
      {r.good && (
        <p>
          <span className="label mr-1.5">Good</span>
          <span className="text-ink-2">{r.good}</span>
        </p>
      )}
      {r.missing && (
        <p>
          <span className="label mr-1.5">Missing</span>
          <span className="text-ink-2">{r.missing}</span>
        </p>
      )}
      {r.correct_figure && (
        <p className="flex flex-wrap items-center gap-2">
          <span className="label">Correct figure</span>
          <span className="text-ink">{r.correct_figure.label}</span>
          <span className="font-display text-[16px] tracking-[-0.03em] tabular-nums">{r.correct_figure.display}</span>
          <SourceChip x={figureExplain(r.correct_figure)} />
        </p>
      )}
      {r.strong_answer && (
        <p className="border-l border-line-strong pl-3">
          <span className="label block pb-0.5">A strong answer</span>
          <span className="text-ink">{r.strong_answer}</span>
        </p>
      )}
    </div>
  );
}

function Message({ msg, fresh }: { msg: FeedItem; fresh: boolean }) {
  switch (msg.kind) {
    case "vc":
      return (
        <div className="flex gap-3">
          <VcGlyph glyph={msg.glyph} className={msg.chair ? "text-ember" : undefined} />
          <div className="flex min-w-0 flex-col gap-1">
            <span className="text-[11.5px] text-ink-2">
              <span className="font-display text-[14px] tracking-[-0.03em] text-ink">{msg.name}</span>
              {msg.firm ? ` · ${msg.firm}` : ""}
              {msg.knowledgeCheck && <span className="label ml-2 align-middle">Knowledge check</span>}
            </span>
            <p
              className={cn(
                "max-w-[62ch] font-display leading-[1.2] tracking-[-0.03em]",
                msg.chair ? "text-[clamp(15px,1.25vw,18px)] text-ink-2" : "text-[clamp(17px,1.5vw,21px)]",
              )}
            >
              {fresh && !msg.citations?.length ? <BlurText text={msg.text} /> : <CitedText text={msg.text} citations={msg.citations ?? []} />}
            </p>
            {msg.review?.revised && (
              <span className="text-[11px] text-dim" data-testid="review-note">
                Vicky sent the first draft back{msg.review.note ? `: ${msg.review.note}` : ""}
              </span>
            )}
          </div>
        </div>
      );
    case "founder":
      return (
        <div className="ml-10 flex flex-col gap-1.5 border-l border-line-strong pl-3">
          <span className="text-[11.5px] text-ink-2">You</span>
          <p className="max-w-[62ch] text-[14px] leading-snug">{msg.text}</p>
          {!!msg.claims?.length && <Claims claims={msg.claims} />}
        </div>
      );
    case "score":
      return (
        <Card icon={<span className="size-1.5 rounded-full bg-ink" />} title="Feedback & scoring · Vicky">
          {!!msg.claims?.length && <Claims claims={msg.claims} />}
          <DimBars dims={msg.dims} />
          {msg.note && <p className="max-w-[64ch] text-[13px] leading-snug text-ink-2">{msg.note}</p>}
          {msg.rationale && <Rationale r={msg.rationale} />}
        </Card>
      );
    case "coach":
      return (
        <Card icon={<span className="size-1.5 rounded-full bg-ember" />} title="Time-out · Vicky" className="border-ember/50">
          <CornerMarks className="[&_span]:text-ember" />
          <p className="max-w-[64ch] text-[13.5px] leading-snug">
            <CitedText text={msg.text} citations={msg.citations ?? []} />
          </p>
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
        <Card icon={<BookOpen className="size-3.5" strokeWidth={1.5} />} title="Knowledge check · Vicky">
          <KnowledgeChip verdict={msg.verdict} className="self-start" />
          <p className="max-w-[64ch] text-[13px] leading-snug">
            <CitedText text={msg.text} citations={msg.citations ?? []} />
          </p>
          {msg.source && <span className="font-mono text-[9.5px] uppercase tracking-[-0.04em] text-dim">Checked against {msg.source}</span>}
        </Card>
      );
    case "report":
      return (
        <Card icon={<FileText className="size-3.5" strokeWidth={1.5} />} title="Report ready">
          <p className="text-[13px] leading-snug">Your debrief: verdict, every question with a stronger answer, the claims ledger and sources.</p>
          <Link
            href={`/reports/${encodeURIComponent(msg.reportId)}`}
            className="self-start rounded-[3px] bg-invert-bg px-3.5 py-1.5 font-mono text-[11px] uppercase tracking-[0.02em] text-invert-ink"
          >
            Open the report
          </Link>
        </Card>
      );
  }
}

interface ChatFeedProps {
  messages: FeedItem[];
  filter: FeedFilter;
  /** Index from which messages animate in (older ones render still). */
  freshFrom: number;
  typing?: string;
  empty?: string;
}

export function ChatFeed({ messages, filter, freshFrom, typing, empty }: ChatFeedProps) {
  const end = useRef<HTMLDivElement>(null);
  const kinds = FILTER_KINDS[filter];
  const shown = kinds ? messages.filter((m) => kinds.includes(m.kind)) : messages;

  // Follow new messages inside the panel's own scroller (never scroll the page on phones).
  useEffect(() => {
    const scroller = end.current?.closest<HTMLElement>(".overflow-y-auto");
    if (scroller && scroller.scrollHeight > scroller.clientHeight) {
      scroller.scrollTo({ top: scroller.scrollHeight, behavior: "smooth" });
    }
  }, [messages.length, typing]);

  return (
    <div className="flex flex-col gap-5 p-4 md:p-5" aria-live="polite">
      {shown.length === 0 && (
        <p className="text-[13px] text-ink-2">{empty ?? "Nothing in this view yet. Answer a question to get feedback here."}</p>
      )}
      {shown.map((m) => (
        <Message key={m.id} msg={m} fresh={messages.indexOf(m) >= freshFrom} />
      ))}
      {typing && filter === "all" && (
        <p className="ml-10 text-[12px] text-dim">
          {typing} is thinking
          <span className="animate-[pulse-dot_1s_ease-in-out_infinite]">…</span>
        </p>
      )}
      <div ref={end} />
    </div>
  );
}
