"use client";

import { ChevronLeft, ChevronRight, FileUp, Loader2, X } from "lucide-react";
import { useRef, useState } from "react";
import { ClaimChip, worstStatus } from "@/components/prep/ClaimChip";
import { CornerMarks } from "@/components/ui/Panel";
import { VcGlyph } from "@/components/ui/VcGlyph";
import type { Deck, DeckSlide, KbCheck, LedgerRow } from "@/lib/types";
import { cn } from "@/lib/utils";
import { KbChip, byVerdict } from "./KbChip";

/** A PowerPoint slide has no image (it isn't rendered on the server): its title and lines, on the dark stage. */
function TextSlide({ slide, small = false }: { slide: DeckSlide; small?: boolean }) {
  const lines = slide.bullets?.length ? slide.bullets : slide.text ? [slide.text] : [];
  if (small) {
    return (
      <span className="flex aspect-video w-full flex-col gap-[2px] overflow-hidden rounded-[2px] bg-[#16161a] p-1 text-left">
        <span className="truncate text-[6.5px] font-medium text-white">{slide.title || `Slide ${slide.n}`}</span>
        {lines.slice(0, 3).map((l, i) => (
          <span key={i} className="h-[2px] w-[80%] rounded-full bg-white/25" style={{ width: `${60 + ((i * 13) % 30)}%` }} />
        ))}
      </span>
    );
  }
  return (
    <div className="absolute inset-0 flex flex-col justify-center gap-[3%] px-[8%] py-[7%] text-left">
      {slide.title && <h2 className="font-display text-[clamp(20px,3.2vw,44px)] leading-[1.05] tracking-[-0.03em] text-white">{slide.title}</h2>}
      <ul className="flex flex-col gap-[1.2vh] text-[clamp(12px,1.55vw,20px)] leading-snug text-white/85">
        {lines.slice(0, 9).map((l, i) => (
          <li key={i} className="flex gap-2">
            <span className="mt-[0.55em] size-1.5 shrink-0 rounded-full bg-ember" aria-hidden />
            <span className="min-w-0">{l}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

const isKb = (t: LedgerRow | KbCheck): t is KbCheck => "verdict" in t;

export interface Caption {
  speaker: string;
  name: string;
  glyph: string;
  text: string;
  /** The founder's words still coming in. */
  live?: boolean;
}

interface SlideStageProps {
  deck: Deck | null;
  index: number;
  onIndex: (i: number) => void;
  /** The seated investors, Vicky first. */
  seats: { id: string; name: string; glyph: string; role: string }[];
  speaking: string | null;
  status: { label: string; tone: "live" | "paused" | "idle" };
  caption: Caption | null;
  /** The latest claim checked (against the data or the notes), shown for a few seconds. */
  toast: LedgerRow | KbCheck | null;
  /** Spoken claims, for each slide's status bar and claim line. */
  ledger: LedgerRow[];
  /** Spoken statements checked against the knowledge base. */
  kb: KbCheck[];
  /** Before the pitch starts the deck can be added or removed. */
  setup: boolean;
  uploading: boolean;
  onUpload: (file: File) => void;
  onRemove: () => void;
  onSkip?: () => void;
  level: number;
  listening: boolean;
}

function Meter({ level, on }: { level: number; on: boolean }) {
  const bars = [0.55, 0.85, 1, 0.75, 0.5];
  return (
    <span className="flex h-4 items-center gap-[3px]" aria-hidden>
      {bars.map((b, i) => (
        <span
          key={i}
          className={cn("w-[3px] rounded-full transition-[height] duration-100", on ? "bg-ember" : "bg-white/35")}
          style={{ height: `${Math.max(18, Math.min(100, (on ? level * 260 * b : 0) + 18))}%` }}
        />
      ))}
    </span>
  );
}

/** The pitch room's stage: the slide on screen (or the room, without a deck), the panel, live captions. */
export function SlideStage(props: SlideStageProps) {
  const { deck, index, onIndex, seats, speaking, status, caption, toast, ledger, kb, setup, uploading, onUpload, onRemove, onSkip, level, listening } = props;
  const file = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const slide = deck?.slides[index];
  const claimsOn = (n: number) => [...(deck?.slides[n - 1]?.claims ?? []), ...ledger.filter((r) => r.source === "spoken" && r.slide === n)];
  const kbOn = (n: number) => [...(deck?.slides[n - 1]?.kb ?? []), ...kb.filter((k) => k.source === "spoken" && k.slide === n)];
  const here = slide ? claimsOn(slide.n) : [];
  const hereKb = slide ? byVerdict(kbOn(slide.n)).filter((k) => k.verdict !== "supported") : [];
  const vc = caption && caption.speaker !== "founder";

  const pick = (f: File | undefined | null) => {
    if (f) onUpload(f);
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      {/* The stage stays 16:9 and dark, like the room's screen. */}
      <div
        className="relative mx-auto aspect-[3/4] w-full sm:aspect-video max-w-[min(100%,calc((100dvh-300px)*16/9))] overflow-hidden rounded-[4px] border border-line bg-[#0b0b0c] text-white"
        onDragOver={(e) => {
          if (!setup) return;
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          if (!setup) return;
          e.preventDefault();
          setOver(false);
          pick(e.dataTransfer.files?.[0]);
        }}
        data-testid="pitch-stage"
      >
        <CornerMarks className="[&_span]:text-white/30" />

        {slide?.image ? (
          // eslint-disable-next-line @next/next/no-img-element -- a data URL rendered from the founder's PDF
          <img src={slide.image} alt={`Slide ${slide.n}`} className="absolute inset-0 size-full object-contain" draggable={false} />
        ) : slide ? (
          <TextSlide slide={slide} />
        ) : (
          <div className={cn("absolute inset-0 flex flex-col items-center bg-[radial-gradient(ellipse_at_50%_120%,rgba(255,92,0,0.14),transparent_60%)]", setup ? "justify-end pb-[7%]" : caption ? "justify-center pb-[14%]" : "justify-center")}>
            <ul className="flex flex-wrap items-end justify-center gap-[clamp(12px,3vw,40px)] px-6">
              {seats.map((s) => {
                const on = speaking === s.id;
                return (
                  <li key={s.id} className={cn("flex flex-col items-center gap-2 transition-all duration-500", on ? "scale-110 opacity-100" : speaking ? "opacity-45" : "opacity-85")}>
                    <span className={cn("relative rounded-[14px] p-2 ring-1 transition-shadow", on ? "ring-ember shadow-[0_0_40px_-6px_rgba(255,92,0,0.7)]" : "ring-white/15")}>
                      {on && <span className="absolute inset-0 animate-ping rounded-[14px] ring-1 ring-ember/60" aria-hidden />}
                      <VcGlyph glyph={s.glyph} className={cn("size-[clamp(36px,5vw,64px)]", on ? "text-ember" : "text-white")} />
                    </span>
                    <span className="text-center text-[clamp(10px,1.1vw,13px)] leading-tight">
                      {s.name}
                      <span className="block text-white/50">{s.role}</span>
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        )}

        {/* Setup: drop a deck, or go without one. */}
        {setup && !deck && (
          <div className={cn("absolute inset-x-[12%] top-[14%] bottom-[46%] flex flex-col items-center justify-center gap-2 rounded-[6px] border border-dashed text-center transition-colors", over ? "border-ember bg-ember/10" : "border-white/25 bg-black/40")}>
            {uploading ? (
              <>
                <Loader2 className="size-5 animate-spin text-white/70" strokeWidth={1.5} />
                <span className="max-w-[44ch] text-[13px]">
                  Reading your deck: every figure against your data, every claim against your knowledge base…
                </span>
              </>
            ) : (
              <>
                <button
                  type="button"
                  onClick={() => file.current?.click()}
                  className="flex items-center gap-2 rounded-[3px] border border-white/40 px-3 py-1.5 text-[13px] hover:border-white"
                  data-testid="deck-upload"
                >
                  <FileUp className="size-4" strokeWidth={1.5} />
                  Upload your deck (PDF or PowerPoint)
                </button>
                <span className="max-w-[52ch] text-[11.5px] text-white/55">
                  Drop it here, or press Start to pitch without slides. The deck is checked against your knowledge base, never added to it.
                </span>
              </>
            )}
            <input ref={file} type="file" accept="application/pdf,.pdf,application/vnd.openxmlformats-officedocument.presentationml.presentation,.pptx" className="hidden" onChange={(e) => pick(e.target.files?.[0])} />
          </div>
        )}

        {/* Top: what the room is doing, and who's seated. */}
        <div className="pointer-events-none absolute inset-x-3 top-3 flex items-start justify-between gap-3">
          <span
            className={cn(
              "flex items-center gap-2 rounded-full px-3 py-1 font-mono text-[10.5px] uppercase tracking-[-0.02em] backdrop-blur-md",
              status.tone === "live" ? "bg-ember text-black" : status.tone === "paused" ? "bg-white text-black" : "bg-black/55 text-white/80",
            )}
            role="status"
            data-testid="pitch-status"
          >
            {status.tone === "live" && <span className="size-1.5 animate-pulse rounded-full bg-black" aria-hidden />}
            {status.label}
            {listening && <Meter level={level} on={status.tone === "live"} />}
          </span>
          <span className="flex items-center gap-2">
            {slide && (
              <ul className="flex gap-1" aria-label="Seated">
                {seats.map((s) => (
                  <li key={s.id} title={s.name} className={cn("rounded-[8px] bg-black/55 p-0.5 backdrop-blur-md transition-all", speaking === s.id ? "text-ember ring-1 ring-ember" : "text-white/70")}>
                    <VcGlyph glyph={s.glyph} className="size-6" />
                  </li>
                ))}
              </ul>
            )}
            {deck && (
              <span className="rounded-full bg-black/55 px-2.5 py-1 font-mono text-[10.5px] tabular-nums text-white/80 backdrop-blur-md">
                {index + 1} / {deck.slides.length}
              </span>
            )}
          </span>
        </div>

        {/* A claim the panel just checked. */}
        {toast && (
          <div key={toast.id} className="pointer-events-none absolute left-3 bottom-[34%] flex max-w-[70%] animate-[rise_.35s_ease-out] items-center gap-2 rounded-[4px] bg-black/70 px-2.5 py-1.5 text-[12px] backdrop-blur-md">
            {isKb(toast) ? (
              <>
                <KbChip verdict={toast.verdict} />
                <span className="truncate">“{toast.text}”</span>
                {toast.quote && toast.verdict === "contradicted" && <span className="truncate text-white/60">· notes: “{toast.quote}”</span>}
              </>
            ) : (
              <>
                <ClaimChip status={toast.status} />
                <span className="truncate">“{toast.text}”</span>
                {toast.truth && toast.status !== "matches" && <span className="shrink-0 text-white/60">· data: {toast.truth}</span>}
              </>
            )}
          </div>
        )}

        {/* Captions: whoever is speaking, word for word. */}
        {caption && (
          <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/90 via-black/70 to-transparent px-[5%] pt-12 pb-[4%]" aria-live="polite">
            <div className="mx-auto flex max-w-[860px] items-start gap-3">
              <VcGlyph glyph={caption.glyph} className={cn("mt-0.5 size-8", vc ? "text-ember" : "text-white/70")} />
              <div className="min-w-0 flex-1">
                <span className="flex items-center gap-2 font-mono text-[10.5px] uppercase tracking-[-0.02em] text-white/60">
                  {caption.name}
                  {vc && onSkip && (
                    <button type="button" onClick={onSkip} className="pointer-events-auto rounded-[3px] border border-white/25 px-1.5 normal-case text-white/70 hover:border-white hover:text-white">
                      Skip
                    </button>
                  )}
                </span>
                <p className={cn("text-[clamp(14px,1.7vw,21px)] leading-snug", caption.live ? "text-white/80" : "text-white")} data-testid="pitch-caption">
                  {caption.text || "…"}
                </p>
              </div>
            </div>
          </div>
        )}

        {setup && deck && (
          <button type="button" onClick={onRemove} className="absolute right-3 bottom-3 flex items-center gap-1 rounded-full bg-black/60 px-2.5 py-1 text-[11px] text-white/80 backdrop-blur-md hover:text-white">
            <X className="size-3" strokeWidth={1.5} /> Remove deck
          </button>
        )}
      </div>

      {deck && (
        <div className="mx-auto flex w-full max-w-[min(100%,calc((100dvh-300px)*16/9))] flex-col gap-2">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => onIndex(Math.max(0, index - 1))}
              disabled={index === 0}
              className="flex size-8 shrink-0 items-center justify-center rounded-[3px] border border-line-strong text-ink disabled:opacity-30"
              aria-label="Previous slide"
            >
              <ChevronLeft className="size-4" strokeWidth={1.5} />
            </button>
            <ol className="scroll-thin flex min-w-0 flex-1 gap-1.5 overflow-x-auto pb-1" aria-label="Slides">
              {deck.slides.map((s, i) => {
                const worst = worstStatus(claimsOn(s.n).map((c) => c.status));
                const notesOff = kbOn(s.n).some((k) => k.verdict === "contradicted");
                return (
                  <li key={s.n} className="shrink-0">
                    <button
                      type="button"
                      onClick={() => onIndex(i)}
                      aria-current={i === index ? "true" : undefined}
                      aria-label={`Slide ${s.n}`}
                      className={cn("flex w-[72px] flex-col gap-1 rounded-[3px] border p-1 transition-colors", i === index ? "border-ink" : "border-line hover:border-line-strong")}
                    >
                      {s.image ? (
                        // eslint-disable-next-line @next/next/no-img-element -- thumbnail of the same data URL
                        <img src={s.image} alt="" className="aspect-video w-full rounded-[2px] object-cover" draggable={false} />
                      ) : (
                        <TextSlide slide={s} small />
                      )}
                      <span
                        className={cn(
                          "h-[3px] rounded-full",
                          worst === "contradicts" || notesOff ? "bg-ember" : worst && worst !== "matches" ? "bg-ink-2" : "bg-line-strong",
                        )}
                      />
                    </button>
                  </li>
                );
              })}
            </ol>
            <button
              type="button"
              onClick={() => onIndex(Math.min(deck.slides.length - 1, index + 1))}
              disabled={index === deck.slides.length - 1}
              className="flex size-8 shrink-0 items-center justify-center rounded-[3px] border border-line-strong text-ink disabled:opacity-30"
              aria-label="Next slide"
            >
              <ChevronRight className="size-4" strokeWidth={1.5} />
            </button>
          </div>
          {here.length || hereKb.length ? (
            <ul className="flex flex-col gap-1">
              {here.slice(0, 3).map((c) => (
                <li key={c.id} className="flex flex-wrap items-center gap-2 text-[12.5px]">
                  <ClaimChip status={c.status} />
                  <span className="text-ink-2">“{c.text}”</span>
                  {c.truth && c.status !== "matches" && <span className="text-ink-2">Data says: {c.truth}</span>}
                </li>
              ))}
              {hereKb.slice(0, 3).map((k) => (
                <li key={k.id} className="flex flex-wrap items-center gap-2 text-[12.5px]" data-testid="slide-kb-check">
                  <KbChip verdict={k.verdict} />
                  <span className="text-ink-2">“{k.text}”</span>
                  {k.quote ? <span className="text-ink-2">Your notes: “{k.quote}”</span> : k.why && <span className="text-dim">{k.why}</span>}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[12.5px] text-dim">Nothing on this slide to check against your data or notes.</p>
          )}
        </div>
      )}
    </div>
  );
}
