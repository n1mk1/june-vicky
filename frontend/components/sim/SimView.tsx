"use client";

import { AudioLines, Mic, Square } from "lucide-react";
import { useEffect, useState } from "react";
import { PromptBar } from "@/components/app/PromptBar";
import { MAX_PANEL, VcRoster } from "@/components/app/VcRoster";
import { ChatFeed, type FeedItem } from "@/components/prep/ChatFeed";
import { CornerMarks, Panel } from "@/components/ui/Panel";
import { PillLink } from "@/components/ui/Pill";
import { Segmented } from "@/components/ui/Segmented";
import { ApiError, apiPost } from "@/lib/api";
import { PREVIEW_FEED } from "@/lib/preview";
import type { PersonaSummary } from "@/lib/types";
import { errorText, useAccessGuard, useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";
import { ScorePanel } from "./ScorePanel";
import { SlideStage } from "./SlideStage";

type View = "slides" | "feedback";
type Interrupt = "live" | "after";
type Gate = { kind: "checking" } | { kind: "ready" } | { kind: "no-truth"; detail: string } | { kind: "soon"; detail: string } | { kind: "error"; detail: string };

/** Notice laid over the stage: the TruthPack gate (409) or "voice simulation coming next" (501). */
function StageNotice({ gate }: { gate: Gate }) {
  if (gate.kind === "checking" || gate.kind === "ready") return null;
  const noTruth = gate.kind === "no-truth";
  return (
    <div className="pointer-events-none absolute inset-x-3 top-3 z-20 flex justify-center md:inset-x-5 md:top-5">
      <div className="pointer-events-auto relative flex w-full max-w-[560px] flex-col gap-2 rounded-[16px] border border-line-strong bg-surface-solid/95 p-4 shadow-[0_12px_40px_-12px_rgba(0,0,0,0.45)] backdrop-blur-md">
        <CornerMarks />
        <span className="flex items-center gap-2 label">
          <span className={cn("size-1.5 rounded-full", noTruth ? "bg-ember" : "bg-ink animate-[pulse-dot_2.4s_ease-in-out_infinite]")} aria-hidden />
          {noTruth ? "Source of truth needed" : gate.kind === "soon" ? "Coming next" : "Simulation unavailable"}
        </span>
        <p className="font-display text-[20px] leading-tight tracking-[-0.035em]">
          {noTruth ? "Confirm a source of truth first." : gate.kind === "soon" ? "Voice simulation is coming next." : "The pitch room didn't open."}
        </p>
        <p className="text-[12.5px] leading-snug text-ink-2">
          {noTruth
            ? "The panel checks every claim on your slides against your data, so it needs data to check against."
            : gate.kind === "soon"
              ? "Deck upload, live transcription and in-voice interruptions land with the voice pipeline. Below is a preview of the stage; practise the Q&A in Preparation today."
              : gate.detail}
        </p>
        <div className="flex flex-wrap gap-2 pt-1">
          {noTruth ? <PillLink href="/intake" label="Load data" variant="solid" /> : <PillLink href="/preparation" label="Go to Preparation" variant="solid" />}
        </div>
      </div>
    </div>
  );
}

export function SimView() {
  const guard = useAccessGuard();
  const personas = useApi<PersonaSummary[]>("areopagus");
  const [chosen, setChosen] = useState<string[]>(["james", "alex", "mark"]);
  const [view, setView] = useState<View>("slides");
  const [interrupt, setInterrupt] = useState<Interrupt>("live");
  const [slide, setSlide] = useState(1);
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [feed, setFeed] = useState<FeedItem[]>(PREVIEW_FEED);
  const [gate, setGate] = useState<Gate>({ kind: "checking" });

  // Ask the API for a pitch room on load: 409 without a confirmed TruthPack, 501 until voice lands.
  useEffect(() => {
    let live = true;
    apiPost("pitch/start").then(
      () => live && setGate({ kind: "ready" }),
      (err: unknown) => {
        if (!live || guard(err)) return;
        if (err instanceof ApiError && err.status === 409) setGate({ kind: "no-truth", detail: err.detail });
        else if (err instanceof ApiError && err.status === 501) setGate({ kind: "soon", detail: err.detail });
        else setGate({ kind: "error", detail: errorText(err) });
      },
    );
    return () => {
      live = false;
    };
  }, [guard]);

  useEffect(() => {
    if (!recording) return;
    const id = window.setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => window.clearInterval(id);
  }, [recording]);

  const clock = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
  const known = personas.data?.map((p) => p.id);
  const selected = chosen.filter((id) => !known || known.includes(id));
  const blocked = gate.kind !== "ready";

  return (
    <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[minmax(220px,260px)_minmax(0,1fr)_minmax(260px,320px)]">
      <VcRoster
        personas={personas.data}
        loading={personas.loading}
        error={personas.error ? errorText(personas.error) : null}
        onRetry={personas.reload}
        selected={selected}
        speaking={recording && interrupt === "live" ? selected[selected.length - 1] : undefined}
        onToggle={(id) =>
          setChosen((s) => (s.includes(id) ? s.filter((x) => x !== id) : s.length >= MAX_PANEL ? s : [...s, id]))
        }
      />

      <div className="flex min-h-[620px] min-w-0 flex-col gap-4 lg:min-h-0">
        <Panel
          title={view === "slides" ? "Slide view · preview" : "Performance feedback · preview"}
          marks
          className="relative flex-1"
          aside={
            <div className="flex flex-wrap items-center justify-end gap-2">
              <Segmented
                label="Interruptions"
                value={interrupt}
                onChange={setInterrupt}
                options={[
                  { value: "live", label: "Interrupt live" },
                  { value: "after", label: "Questions after" },
                ]}
              />
              <Segmented
                label="View"
                value={view}
                onChange={setView}
                options={[
                  { value: "slides", label: "Slides" },
                  { value: "feedback", label: "Feedback" },
                ]}
              />
            </div>
          }
          bodyClassName="relative scroll-thin overflow-y-auto"
        >
          <StageNotice gate={gate} />
          <div className={cn("transition-opacity duration-500", blocked && gate.kind !== "checking" && "opacity-45")}>
            {view === "slides" ? (
              <SlideStage index={slide} onIndex={setSlide} />
            ) : (
              <ChatFeed messages={feed} filter="all" freshFrom={PREVIEW_FEED.length} />
            )}
          </div>
        </Panel>

        <PromptBar
          label="Type what you'd say"
          placeholder={
            blocked
              ? gate.kind === "no-truth"
                ? "Confirm a source of truth to present."
                : "Voice simulation is coming next."
              : recording
                ? `Presenting · ${clock} · the panel is listening`
                : "Press the mic to present, or type a line"
          }
          disabled={blocked}
          onSubmit={(text) => {
            setFeed((f) => [...f, { id: `t${Date.now()}`, kind: "founder", text }]);
            setView("feedback");
          }}
          leading={
            <button
              type="button"
              onClick={() => setRecording((r) => !r)}
              disabled={blocked}
              aria-pressed={recording}
              aria-label={recording ? "Stop presenting" : "Start presenting"}
              className={cn(
                "flex size-8 shrink-0 items-center justify-center rounded-[9px] border transition-colors disabled:opacity-40",
                recording ? "border-ember bg-ember text-white" : "border-line text-ink-2 hover:border-line-strong hover:text-ink",
              )}
            >
              {recording ? <Square className="size-3.5" strokeWidth={2} /> : blocked ? <AudioLines className="size-4" strokeWidth={1.5} /> : <Mic className="size-4" strokeWidth={1.5} />}
            </button>
          }
          hint="Live mode lets the panel interrupt once per slide at most. Typed lines are a fallback when the microphone isn't available."
        />
      </div>

      <div className="flex min-h-[560px] lg:min-h-0 [&>*]:flex-1">
        <ScorePanel />
      </div>
    </div>
  );
}
