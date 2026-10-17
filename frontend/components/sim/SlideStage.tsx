"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { CornerMarks } from "@/components/ui/Panel";
import { VickyMark } from "@/components/ui/VickyMark";
import { ClaimChip } from "@/components/prep/ClaimChip";
import { DECK } from "@/lib/panel";

/** A rendered stand-in for the uploaded PDF deck, with the claim on each slide checked against the data. */
export function SlideStage({ index, onIndex }: { index: number; onIndex: (i: number) => void }) {
  const slide = DECK[index];
  return (
    <div className="flex h-full flex-col gap-4 p-4 md:p-5">
      <div className="relative mx-auto aspect-video w-full max-w-[880px] overflow-hidden rounded-[14px] border border-line bg-[#f2f2f2] text-[#111214]">
        <CornerMarks className="[&_span]:text-[#111214]/40" />
        <div className="absolute inset-0 flex flex-col justify-between p-[5%]">
          <div className="flex items-center justify-between text-[clamp(9px,1vw,12px)] text-[#434343]">
            <span>{slide.title}</span>
            <span className="tabular-nums">
              {slide.n} / {DECK.length}
            </span>
          </div>
          <div>
            <p className="display text-[clamp(28px,5.4vw,72px)]">{slide.headline}</p>
            <p className="mt-2 text-[clamp(11px,1.4vw,18px)] text-[#434343]">{slide.body}</p>
          </div>
          <div className="flex items-end justify-between">
            <VickyMark className="size-[clamp(12px,1.6vw,20px)] opacity-30" />
            <span className="text-[clamp(8px,0.9vw,11px)] text-[#434343]/70">Sample deck · Tidewell Systems</span>
          </div>
        </div>
      </div>

      <div className="mx-auto flex w-full max-w-[880px] flex-wrap items-center justify-between gap-3">
        <div className="flex gap-1.5">
          <button
            type="button"
            onClick={() => onIndex(Math.max(0, index - 1))}
            disabled={index === 0}
            className="flex size-9 items-center justify-center rounded-[10px] border border-line-strong text-ink disabled:opacity-30"
            aria-label="Previous slide"
          >
            <ChevronLeft className="size-4" strokeWidth={1.5} />
          </button>
          <button
            type="button"
            onClick={() => onIndex(Math.min(DECK.length - 1, index + 1))}
            disabled={index === DECK.length - 1}
            className="flex size-9 items-center justify-center rounded-[10px] border border-line-strong text-ink disabled:opacity-30"
            aria-label="Next slide"
          >
            <ChevronRight className="size-4" strokeWidth={1.5} />
          </button>
        </div>
        {slide.claim ? (
          <p className="flex flex-wrap items-center gap-2 text-[12.5px]">
            <span className="text-ink-2">“{slide.claim.text}”</span>
            <ClaimChip status={slide.claim.status} />
            <span className="text-ink-2">Data says: {slide.claim.truth}</span>
          </p>
        ) : (
          <p className="text-[12.5px] text-dim">No figures on this slide.</p>
        )}
      </div>

      <ol className="mx-auto grid w-full max-w-[880px] grid-cols-5 gap-2" aria-label="Slides">
        {DECK.map((s, i) => (
          <li key={s.n}>
            <button
              type="button"
              onClick={() => onIndex(i)}
              aria-current={i === index ? "true" : undefined}
              className={`flex w-full flex-col gap-1 rounded-[10px] border p-2 text-left transition-colors ${
                i === index ? "border-ink" : "border-line hover:border-line-strong"
              }`}
            >
              <span className="truncate text-[11px] text-ink-2">{s.title}</span>
              <span
                className={`h-[3px] rounded-full ${
                  s.claim?.status === "contradicts" ? "bg-ember" : s.claim && s.claim.status !== "matches" ? "bg-ink-2" : "bg-line-strong"
                }`}
              />
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}
