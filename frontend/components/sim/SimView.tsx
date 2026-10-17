"use client";

import { Mic, Square } from "lucide-react";
import { useEffect, useState } from "react";
import { PromptBar } from "@/components/app/PromptBar";
import { VcRoster } from "@/components/app/VcRoster";
import { ChatFeed } from "@/components/prep/ChatFeed";
import { Panel } from "@/components/ui/Panel";
import { PANEL, SIM_FEED, type Msg } from "@/lib/panel";
import { cn } from "@/lib/utils";
import { ScorePanel } from "./ScorePanel";
import { SlideStage } from "./SlideStage";

type View = "slides" | "feedback";
type Interrupt = "live" | "after";

function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="flex rounded-full border border-line p-[2px]">
      {options.map((o) => (
        <button
          key={o.value}
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            "rounded-full px-2.5 py-0.5 text-[11.5px] transition-colors",
            value === o.value ? "bg-invert-bg text-invert-ink" : "text-ink-2 hover:text-ink",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function SimView() {
  const [selected, setSelected] = useState(PANEL.map((p) => p.id));
  const [view, setView] = useState<View>("slides");
  const [interrupt, setInterrupt] = useState<Interrupt>("live");
  const [slide, setSlide] = useState(1);
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [feed, setFeed] = useState<Msg[]>(SIM_FEED);

  useEffect(() => {
    if (!recording) return;
    const id = window.setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => window.clearInterval(id);
  }, [recording]);

  const clock = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

  return (
    <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[minmax(220px,260px)_minmax(0,1fr)_minmax(260px,320px)]">
      <VcRoster
        selected={selected}
        speaking={recording && interrupt === "live" ? "skeptic" : undefined}
        onToggle={(id) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]))}
      />

      <div className="flex min-h-[620px] min-w-0 flex-col gap-4 lg:min-h-0">
        <Panel
          title={view === "slides" ? "Slide view" : "Performance feedback"}
          marks
          className="flex-1"
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
          bodyClassName="scroll-thin overflow-y-auto"
        >
          {view === "slides" ? (
            <SlideStage index={slide} onIndex={setSlide} />
          ) : (
            <ChatFeed messages={feed} filter="all" freshFrom={SIM_FEED.length} />
          )}
        </Panel>

        <PromptBar
          label="Type what you'd say"
          placeholder={recording ? `Presenting · ${clock} · the panel is listening` : "Press the mic to present, or type a line"}
          onSubmit={(text) => {
            setFeed((f) => [...f, { id: `t${Date.now()}`, kind: "founder", text }]);
            setView("feedback");
          }}
          leading={
            <button
              type="button"
              onClick={() => setRecording((r) => !r)}
              aria-pressed={recording}
              aria-label={recording ? "Stop presenting" : "Start presenting"}
              className={cn(
                "flex size-8 shrink-0 items-center justify-center rounded-[9px] border transition-colors",
                recording ? "border-ember bg-ember text-white" : "border-line text-ink-2 hover:border-line-strong hover:text-ink",
              )}
            >
              {recording ? <Square className="size-3.5" strokeWidth={2} /> : <Mic className="size-4" strokeWidth={1.5} />}
            </button>
          }
          hint="Microphone capture is simulated in this preview. Live mode lets the panel interrupt once per slide at most."
        />
      </div>

      <div className="flex min-h-[560px] lg:min-h-0 [&>*]:flex-1">
        <ScorePanel />
      </div>
    </div>
  );
}
