"use client";

import { useEffect, useRef, useState } from "react";
import { PromptBar } from "@/components/app/PromptBar";
import { VcRoster } from "@/components/app/VcRoster";
import { Panel } from "@/components/ui/Panel";
import { FOLLOW_UPS, PANEL, PREP_THREAD, type Msg } from "@/lib/panel";
import { ChatFeed, type FeedFilter } from "./ChatFeed";
import { FeedTabs } from "./FeedTabs";
import { QuestionList } from "./QuestionList";

export function PrepView() {
  const [selected, setSelected] = useState(PANEL.map((p) => p.id));
  const [messages, setMessages] = useState<Msg[]>(PREP_THREAD);
  const [filter, setFilter] = useState<FeedFilter>("all");
  const [typing, setTyping] = useState<string>();
  const turn = useRef(0);
  const timer = useRef<number>(undefined);

  const answer = (text: string) => {
    const speakers = FOLLOW_UPS.filter((f) => selected.includes(f.vc));
    const next = speakers[turn.current % Math.max(1, speakers.length)];
    turn.current += 1;
    setMessages((m) => [...m, { id: `f${Date.now()}`, kind: "founder", text }]);
    if (!next) return;
    setTyping(next.vc);
    // Scripted reply for the static preview; the real court picks a speaker by bid.
    timer.current = window.setTimeout(() => {
      setTyping(undefined);
      setMessages((m) => [...m, { id: `v${Date.now()}`, kind: "vc", vc: next.vc, text: next.text }]);
    }, 1100);
  };

  // A question typed on the landing page or dashboard arrives here.
  useEffect(() => {
    let q: string | null = null;
    try {
      q = sessionStorage.getItem("vicky-question");
      sessionStorage.removeItem("vicky-question");
    } catch {}
    if (q) timer.current = window.setTimeout(() => answer(q), 400);
    return () => window.clearTimeout(timer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[minmax(220px,260px)_minmax(0,1fr)_minmax(260px,320px)]">
      <VcRoster
        selected={selected}
        speaking={typing}
        onToggle={(id) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]))}
      />

      <div className="flex min-h-[520px] min-w-0 flex-col gap-4 lg:min-h-0">
        <Panel title="Court · round 1" marks aside={<FeedTabs value={filter} onChange={setFilter} />} className="flex-1" bodyClassName="scroll-thin overflow-y-auto">
          <ChatFeed messages={messages} filter={filter} freshFrom={PREP_THREAD.length} typing={typing} />
        </Panel>
        <PromptBar
          label="Your answer"
          placeholder={selected.length ? "Answer the panel. Cite where each number comes from." : "Pick at least one investor to start."}
          onSubmit={answer}
          hint="Scores are written by an independent judge after each answer."
        />
      </div>

      <div className="flex min-h-[420px] lg:min-h-0 [&>*]:flex-1">
        <QuestionList />
      </div>
    </div>
  );
}
