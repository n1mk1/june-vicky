"use client";

import { Loader2, Maximize2, Mic, Minimize2, RotateCcw, Square } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MAX_PANEL, VcRoster } from "@/components/app/VcRoster";
import { CornerMarks, Panel } from "@/components/ui/Panel";
import { PillButton, PillLink } from "@/components/ui/Pill";
import { Segmented } from "@/components/ui/Segmented";
import { ErrorNote } from "@/components/ui/States";
import { ApiError, apiPost } from "@/lib/api";
import { CHAIR } from "@/lib/court";
import type { Deck, JudgedScore, KbCheck, LedgerRow, PersonaSummary, Pitch, PitchInterrupt, Session, SpokenLine, Turn } from "@/lib/types";
import { errorText, useAccessGuard, useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";
import { type Mic as MicSession, micSupported, openMic, speak } from "@/lib/voice";
import { ScorePanel } from "./ScorePanel";
import { type Caption, SlideStage } from "./SlideStage";

type Mode = "live" | "after";
type Gate =
  | { kind: "checking" }
  | { kind: "ready"; voice: boolean; mic: boolean }
  | { kind: "no-truth"; detail: string }
  | { kind: "error"; detail: string };
/**
 * setup → opening (Vik) → presenting ⇄ [live: asking → answering → handing] → End →
 *   live: closing → done;  after: conferring → qa-speaking ⇄ qa-listening → qa-thinking … → done.
 */
type Phase =
  | "setup"
  | "opening"
  | "presenting"
  | "asking"
  | "answering"
  | "handing"
  | "conferring"
  | "qa-speaking"
  | "qa-listening"
  | "qa-thinking"
  | "closing"
  | "done";

const SPOKEN: Turn["kind"][] = ["intro", "question", "interject", "coach", "debrief"];
const PRESENTING: Phase[] = ["opening", "presenting", "asking", "answering", "handing"];
const QA: Phase[] = ["conferring", "qa-speaking", "qa-listening", "qa-thinking"];
// A pause this long while presenting closes a segment (its claims get checked); this long after an answer
// ends the answer. Answers get longer: people pause to think.
const SEGMENT_PAUSE_MS = 900;
const ANSWER_PAUSE_MS = 1800;
const CONFER_LINE = "Thank you. Give the panel a moment to compare notes.";
const DEFAULT_PANEL = ["aristotle", "thales", "socrates"];

/** Notice laid over the stage: the TruthPack gate (409) or a pitch room that didn't open. */
function StageNotice({ gate, onRetry }: { gate: Gate; onRetry: () => void }) {
  if (gate.kind === "checking" || gate.kind === "ready") return null;
  const noTruth = gate.kind === "no-truth";
  return (
    <div className="pointer-events-none absolute inset-x-3 top-3 z-20 flex justify-center md:inset-x-5 md:top-5">
      <div className="pointer-events-auto relative flex w-full max-w-[560px] flex-col gap-2 rounded-[4px] border border-line-strong bg-surface-solid/95 p-4 shadow-[0_12px_40px_-12px_rgba(0,0,0,0.45)] backdrop-blur-md">
        <CornerMarks />
        <span className="flex items-center gap-2 label">
          <span className="size-1.5 rounded-full bg-ember" aria-hidden />
          {noTruth ? "Source of truth needed" : "Simulation unavailable"}
        </span>
        <p className="font-display text-[20px] leading-tight tracking-[-0.035em]">
          {noTruth ? "Confirm a source of truth first." : "The pitch room didn't open."}
        </p>
        <p className="text-[12.5px] leading-snug text-ink-2">
          {noTruth ? "The panel checks every claim on your slides against your data, so it needs data to check against." : gate.detail}
        </p>
        <div className="flex flex-wrap gap-2 pt-1">
          {noTruth ? <PillLink href="/knowledge" label="Open the knowledge base" variant="solid" /> : <PillButton label="Try again" variant="solid" onClick={onRetry} />}
        </div>
      </div>
    </div>
  );
}

/** Reading time for a line when there's no voice to play it. */
function readFor(text: string, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const t = window.setTimeout(resolve, Math.max(2200, text.length * 55));
    signal.addEventListener("abort", () => {
      window.clearTimeout(t);
      resolve();
    });
  });
}

const lastSeq = (s: Session | null) => (s?.turns.length ? s.turns[s.turns.length - 1].seq : 0);
const clock = (ms: number) => {
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

export function SimView() {
  const guard = useAccessGuard();
  const router = useRouter();
  const params = useSearchParams();
  const personas = useApi<PersonaSummary[]>("areopagus");
  // Back from the Areopagus builder: `?panel=` carries the seats (new investor included), `?added=` who was built.
  // The page's state survives navigation (cacheComponents keeps it), so take each new hand-off as it arrives.
  const panelParam = () => params.get("panel")?.split(",").filter(Boolean).slice(0, MAX_PANEL) ?? null;
  const handoff = params.get("added");
  const [chosen, setChosen] = useState<string[]>(() => panelParam() ?? DEFAULT_PANEL);
  const [added, setAdded] = useState(handoff);
  const [taken, setTaken] = useState(handoff);
  if (handoff && handoff !== taken) {
    setTaken(handoff);
    setAdded(handoff);
    setChosen(panelParam() ?? DEFAULT_PANEL);
  }
  const [mode, setMode] = useState<Mode>("after");
  const [gate, setGate] = useState<Gate>({ kind: "checking" });
  const [attempt, setAttempt] = useState(0);
  const [deck, setDeck] = useState<Deck | null>(null);
  const [uploading, setUploading] = useState(false);
  const [slide, setSlide] = useState(0);
  const [phase, setPhaseState] = useState<Phase>("setup");
  const [pitch, setPitch] = useState<Pitch | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [caption, setCaption] = useState<Caption | null>(null);
  const [speaking, setSpeaking] = useState<string | null>(null);
  const [toast, setToast] = useState<LedgerRow | KbCheck | null>(null);
  const [scores, setScores] = useState<JudgedScore[]>([]);
  const [slideMs, setSlideMs] = useState<number[]>([]);
  const [elapsed, setElapsed] = useState(0);
  const [level, setLevel] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [typed, setTyped] = useState("");
  const [full, setFull] = useState(false);
  const [typing, setTyping] = useState(false);

  const mic = useRef<MicSession | null>(null);
  const hush = useRef<AbortController | null>(null);
  const run = useRef(0); // bumps on End / New, so a flow still in flight stops where it is
  const phaseRef = useRef<Phase>("setup");
  const pitchRef = useRef<Pitch | null>(null);
  const sessionRef = useRef<Session | null>(null);
  const slideRef = useRef(0);
  const startedAt = useRef(0);
  const slideSince = useRef(0);
  const taking = useRef(false);
  const room = useRef<HTMLDivElement>(null);

  const setPhase = useCallback((p: Phase) => {
    phaseRef.current = p;
    setPhaseState(p);
  }, []);
  const keepPitch = useCallback((p: Pitch) => {
    pitchRef.current = p;
    setPitch(p);
  }, []);
  const keepSession = useCallback((s: Session) => {
    sessionRef.current = s;
    setSession(s);
  }, []);

  // Drop the builder's hand-off params once they're in state, so a reload starts clean.
  useEffect(() => {
    if (params.has("panel") || params.has("added")) router.replace("/simulation", { scroll: false });
  }, [params, router]);

  // May the room open? 409 without a confirmed TruthPack; `voice` says whether ElevenLabs is on.
  // `attempt` bumps on Try again.
  useEffect(() => {
    let live = true;
    apiPost<{ voice: boolean }>("pitch/start").then(
      (r) => live && setGate({ kind: "ready", voice: !!r?.voice, mic: micSupported() }),
      (err: unknown) => {
        if (!live || guard(err)) return;
        if (err instanceof ApiError && err.status === 409) setGate({ kind: "no-truth", detail: err.detail });
        else setGate({ kind: "error", detail: errorText(err) });
      },
    );
    return () => {
      live = false;
    };
  }, [guard, attempt]);

  // Leaving the page closes the mic and silences the room.
  useEffect(
    () => () => {
      run.current++;
      mic.current?.close();
      hush.current?.abort();
    },
    [],
  );

  useEffect(() => {
    const onFs = () => setFull(document.fullscreenElement === room.current);
    document.addEventListener("fullscreenchange", onFs);
    return () => document.removeEventListener("fullscreenchange", onFs);
  }, []);

  // The panel speaks whenever ElevenLabs is on; the founder speaks too when this browser can stream the mic.
  const voiceOn = gate.kind === "ready" && gate.voice;
  const micOn = voiceOn && gate.mic;
  const byId = useMemo(() => new Map((personas.data ?? []).map((p) => [p.id, p])), [personas.data]);
  const known = personas.data?.map((p) => p.id);
  const seated = pitch ? pitch.panel : chosen.filter((id) => !known || known.includes(id)).slice(0, MAX_PANEL);
  const addedName = added ? byId.get(added)?.name : undefined;
  const nameOf = useCallback((id: string) => (id === CHAIR ? "Vik" : id === "founder" ? "You" : (byId.get(id)?.name ?? id)), [byId]);
  const glyphOf = (id: string) => (id === CHAIR ? "vik" : id === "founder" ? "custom" : (byId.get(id)?.glyph ?? "custom"));

  const fail = useCallback(
    (err: unknown) => {
      if (guard(err)) return;
      setError(errorText(err));
    },
    [guard],
  );

  // ---------------------------------------------------------------- slide timing

  /** Adds the time on the current slide to its total and restarts the slide's clock. */
  const banking = useCallback(() => {
    if (!slideSince.current) return;
    const now = Date.now();
    const i = slideRef.current;
    const add = now - slideSince.current;
    slideSince.current = now;
    setSlideMs((xs) => {
      const next = [...xs];
      while (next.length <= i) next.push(0);
      next[i] += add;
      return next;
    });
  }, []);

  const goTo = useCallback(
    (i: number) => {
      if (PRESENTING.includes(phaseRef.current)) banking();
      slideRef.current = i;
      setSlide(i);
    },
    [banking],
  );

  // ---------------------------------------------------------------- the room speaking

  /** Plays lines one after another in each speaker's voice, mic paused. Resolves when done or cut. */
  const play = useCallback(
    async (lines: SpokenLine[]) => {
      mic.current?.pause();
      const ctl = new AbortController();
      hush.current = ctl;
      try {
        for (const l of lines) {
          if (ctl.signal.aborted) break;
          setSpeaking(l.speaker);
          setCaption({ speaker: l.speaker, name: nameOf(l.speaker), glyph: l.speaker === CHAIR ? "vik" : (byId.get(l.speaker)?.glyph ?? "custom"), text: l.text });
          if (voiceOn) {
            try {
              await speak(l.text, l.speaker, ctl.signal, pitchRef.current?.voices?.[l.speaker]);
            } catch (err) {
              setError(err instanceof Error ? err.message : "The panel's voice didn't play.");
              await readFor(l.text, ctl.signal);
            }
          } else await readFor(l.text, ctl.signal);
        }
      } finally {
        if (hush.current === ctl) hush.current = null;
        setSpeaking(null);
      }
    },
    [voiceOn, nameOf, byId],
  );

  /** Opens the floor to the founder: mic on, captions follow their words. */
  const listen = useCallback(
    async (next: Phase) => {
      setPhase(next);
      setCaption({ speaker: "founder", name: "You", glyph: "custom", text: "", live: true });
      try {
        await mic.current?.resume();
      } catch (err) {
        fail(err);
      }
    },
    [setPhase, fail],
  );

  // The toast shows the most serious check of a segment: notes contradicted, a figure off, then anything else.
  const flash = useCallback((rows: LedgerRow[], kb: KbCheck[] = []) => {
    const worst =
      kb.find((k) => k.verdict === "contradicted") ??
      rows.find((r) => r.status !== "matches") ??
      kb.find((k) => k.verdict === "new") ??
      rows[0];
    if (!worst) return;
    setToast(worst);
    window.setTimeout(() => setToast((t) => (t?.id === worst.id ? null : t)), 6000);
  }, []);

  // ---------------------------------------------------------------- presenting (and live interrupts)

  const onInterrupt = useCallback(
    async (it: PitchInterrupt, r: number) => {
      setPhase("asking");
      mic.current?.pause();
      // Whatever was said since the claim is still checked; it can't bring a second interrupt.
      const rest = (await mic.current?.commit()) ?? "";
      const p = pitchRef.current;
      if (rest && p) void apiPost<{ pitch: Pitch }>(`pitch/${p.id}/segment`, { text: rest, slide: deck ? slideRef.current + 1 : null, t_ms: Date.now() - startedAt.current }).catch(() => {});
      await play([{ speaker: it.speaker, text: it.text }]);
      if (r !== run.current) return;
      await listen("answering");
    },
    [deck, play, listen, setPhase],
  );

  const sendSegment = useCallback(
    async (text: string) => {
      const p = pitchRef.current;
      if (!p || !text) return;
      const r = run.current;
      try {
        const out = await apiPost<{ claims: LedgerRow[]; kb?: KbCheck[]; interrupt: PitchInterrupt | null; pitch: Pitch }>(`pitch/${p.id}/segment`, {
          text: text.slice(0, 4000),
          slide: deck ? slideRef.current + 1 : null,
          t_ms: Date.now() - startedAt.current,
        });
        if (r !== run.current) return;
        keepPitch(out.pitch);
        flash(out.claims, out.kb ?? []);
        if (out.interrupt && phaseRef.current === "presenting") await onInterrupt(out.interrupt, r);
      } catch (err) {
        if (r === run.current && !(err instanceof ApiError && err.status === 409)) fail(err);
      }
    },
    [deck, onInterrupt, fail, keepPitch, flash],
  );

  /** The founder's answer to a live interrupt; the investor hands the floor back. */
  const sendReply = useCallback(
    async (text: string) => {
      const p = pitchRef.current;
      if (!p) return;
      const r = run.current;
      mic.current?.pause();
      setPhase("handing");
      setCaption({ speaker: "founder", name: "You", glyph: "custom", text });
      try {
        const out = await apiPost<{ say: SpokenLine[]; score: JudgedScore; pitch: Pitch }>(`pitch/${p.id}/reply`, { text: text.slice(0, 4000) });
        if (r !== run.current) return;
        keepPitch(out.pitch);
        setScores((s) => [...s, out.score]);
        await play(out.say);
      } catch (err) {
        if (r === run.current) fail(err);
      }
      if (r !== run.current) return;
      await listen("presenting");
    },
    [play, listen, setPhase, fail, keepPitch],
  );

  // ---------------------------------------------------------------- Q&A after the pitch

  const runQa = useCallback(
    async (s: Session, after: number, r: number) => {
      keepSession(s);
      setScores(s.scores.map((x) => ({ accuracy: x.accuracy, dims: x.dims })));
      const lines = s.turns
        .filter((t) => t.seq > after && t.speaker !== "founder" && SPOKEN.includes(t.kind))
        .map((t) => ({ speaker: t.speaker, text: t.text }));
      setPhase("qa-speaking");
      await play(lines);
      if (r !== run.current) return;
      if (s.status === "ended") {
        mic.current?.close();
        mic.current = null;
        setPhase("done");
        return;
      }
      await listen("qa-listening");
    },
    [play, listen, setPhase, keepSession],
  );

  const sendAnswer = useCallback(
    async (text: string) => {
      const s = sessionRef.current;
      if (!s) return;
      const r = run.current;
      mic.current?.pause();
      setPhase("qa-thinking");
      setCaption({ speaker: "founder", name: "You", glyph: "custom", text });
      try {
        const next = await apiPost<Session>(`court/${s.id}/answer`, { text: text.slice(0, 4000) });
        if (r !== run.current) return;
        await runQa(next, lastSeq(s), r);
      } catch (err) {
        if (r !== run.current) return;
        fail(err);
        await listen("qa-listening");
      }
    },
    [runQa, listen, setPhase, fail],
  );

  // ---------------------------------------------------------------- turn-taking: pauses end turns

  const takeTurn = useCallback(async () => {
    const m = mic.current;
    const ph = phaseRef.current;
    if (!m || taking.current) return;
    taking.current = true;
    try {
      const text = await m.commit();
      if (ph === "presenting") {
        setCaption((c) => (c?.speaker === "founder" ? { ...c, text: "" } : c));
        if (text) await sendSegment(text);
      } else if (!text) {
        return; // a pause with nothing transcribed: keep listening
      } else if (ph === "answering") await sendReply(text);
      else if (ph === "qa-listening") await sendAnswer(text);
    } finally {
      taking.current = false;
    }
  }, [sendSegment, sendReply, sendAnswer]);

  useEffect(() => {
    if (!["presenting", "answering", "qa-listening"].includes(phase)) return;
    const id = window.setInterval(() => {
      const m = mic.current;
      if (startedAt.current && PRESENTING.includes(phaseRef.current)) setElapsed(Date.now() - startedAt.current);
      if (!m) return;
      setLevel(m.level());
      const ph = phaseRef.current;
      const wait = ph === "presenting" ? SEGMENT_PAUSE_MS : ANSWER_PAUSE_MS;
      if (m.spoke() && m.silenceMs() >= wait && !taking.current) void takeTurn();
    }, 120);
    return () => window.clearInterval(id);
  }, [phase, takeTurn]);

  // ---------------------------------------------------------------- Start / End

  const start = async () => {
    const r = ++run.current;
    setError(null);
    setScores([]);
    setSlideMs([]);
    setElapsed(0);
    setSession(null);
    sessionRef.current = null;
    setPhase("opening");
    try {
      setTyping(!micOn);
      if (micOn) {
        try {
          mic.current = await openMic({
            onPartial: (t) => setCaption((c) => (c?.speaker === "founder" ? { ...c, text: t } : c)),
            onError: (m) => {
              setError(`${m} Type what you'd say instead.`);
              setTyping(true);
            },
          });
        } catch (err) {
          // No mic (blocked, missing, busy): the panel still speaks, and the founder types.
          mic.current = null;
          setTyping(true);
          setError(
            err instanceof DOMException && err.name === "NotAllowedError"
              ? "The microphone is blocked, so type what you'd say. Allow it for this site to pitch out loud."
              : "The microphone didn't open, so type what you'd say.",
          );
        }
      }
      const out = await apiPost<{ pitch: Pitch }>("pitch/start", { mode, panel: seated, deck_id: deck?.id ?? null });
      if (r !== run.current) return;
      keepPitch(out.pitch);
      await play(out.pitch.say);
      if (r !== run.current) return;
      startedAt.current = Date.now();
      slideSince.current = Date.now();
      await listen("presenting");
    } catch (err) {
      mic.current?.close();
      mic.current = null;
      setPhase("setup");
      setCaption(null);
      if (err instanceof ApiError && err.status === 409) setGate({ kind: "no-truth", detail: err.detail });
      else fail(err);
    }
  };

  /** One click ends the presentation (live: wrap-up; after: the Q&A opens). In the Q&A it ends the session. */
  const end = async () => {
    const ph = phaseRef.current;
    const r = ++run.current;
    hush.current?.abort();
    setError(null);
    if (PRESENTING.includes(ph)) {
      banking();
      slideSince.current = 0;
      mic.current?.pause();
      const p = pitchRef.current;
      setPhase(mode === "after" ? "conferring" : "closing");
      setCaption(null);
      if (!p) {
        mic.current?.close();
        mic.current = null;
        return setPhase("setup");
      }
      try {
        const tail = (await mic.current?.commit()) ?? "";
        if (tail) await apiPost(`pitch/${p.id}/segment`, { text: tail.slice(0, 4000), slide: deck ? slideRef.current + 1 : null, t_ms: Date.now() - startedAt.current }).catch(() => {});
        const confer = p.mode === "after" ? play([{ speaker: CHAIR, text: CONFER_LINE }]) : Promise.resolve();
        const out = await apiPost<{ pitch: Pitch; court: Session | null }>(`pitch/${p.id}/end`);
        if (r !== run.current) return;
        keepPitch(out.pitch);
        await confer;
        if (r !== run.current) return;
        if (out.court) return await runQa(out.court, 0, r);
        await play(out.pitch.say);
      } catch (err) {
        fail(err);
      }
      if (r !== run.current) return;
      mic.current?.close();
      mic.current = null;
      setPhase("done");
    } else if (QA.includes(ph)) {
      mic.current?.pause();
      const s = sessionRef.current;
      setPhase("qa-thinking");
      if (s) {
        try {
          const ended = await apiPost<Session>(`court/${s.id}/end`);
          if (r !== run.current) return;
          return await runQa(ended, lastSeq(s), r);
        } catch (err) {
          fail(err);
        }
      }
      mic.current?.close();
      mic.current = null;
      setPhase("done");
    }
  };

  const fresh = () => {
    run.current++;
    hush.current?.abort();
    mic.current?.close();
    mic.current = null;
    pitchRef.current = null;
    sessionRef.current = null;
    setPitch(null);
    setSession(null);
    setCaption(null);
    setToast(null);
    setError(null);
    setScores([]);
    setSlideMs([]);
    setElapsed(0);
    goTo(0);
    setPhase("setup");
  };

  const upload = async (file: File) => {
    if (!/\.(pdf|pptx)$/i.test(file.name) && file.type !== "application/pdf")
      return setError("Upload the deck as a PDF or a PowerPoint (.pptx); export Keynote or Slides to either.");
    setUploading(true);
    setError(null);
    const form = new FormData();
    form.append("file", file);
    try {
      const d = await apiPost<Deck>("pitch/deck", form);
      setDeck(d);
      goTo(0);
    } catch (err) {
      fail(err);
    } finally {
      setUploading(false);
    }
  };

  // Typing stands in for the mic when there's no voice on this server (or the mic failed).
  const sendTyped = () => {
    const t = typed.trim();
    if (!t) return;
    setTyped("");
    const ph = phaseRef.current;
    if (ph === "presenting") void sendSegment(t);
    else if (ph === "answering") void sendReply(t);
    else if (ph === "qa-listening") void sendAnswer(t);
  };

  // ← / → move through the slides (not while typing).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!deck || (e.target instanceof HTMLElement && e.target.closest("input, textarea, [contenteditable]"))) return;
      if (e.key === "ArrowRight" || e.key === "PageDown") goTo(Math.min(deck.slides.length - 1, slideRef.current + 1));
      else if (e.key === "ArrowLeft" || e.key === "PageUp") goTo(Math.max(0, slideRef.current - 1));
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [deck, goTo]);

  // ---------------------------------------------------------------- what the room shows

  const blocked = gate.kind !== "ready";
  const presenting = PRESENTING.includes(phase);
  const inQa = QA.includes(phase);
  const running = presenting || inQa || phase === "closing";
  const listening = phase === "presenting" || phase === "answering" || phase === "qa-listening";
  const asker = pitch?.interrupts.find((i) => i.id === pitch.pending)?.speaker ?? speaking;
  const nextName = session?.next_speaker ? nameOf(session.next_speaker) : "The panel";
  const qn = session ? `${Math.min(session.question_count, session.settings.question_cap)} of ${session.settings.question_cap}` : "";
  const status: { label: string; tone: "live" | "paused" | "idle" } = (() => {
    switch (phase) {
      case "setup":
        return { label: blocked ? (gate.kind === "checking" ? "Opening the room" : "Room closed") : mode === "live" ? "Ready · interruptions on" : "Ready · questions after", tone: "idle" };
      case "opening":
        return { label: "Vik is opening", tone: "paused" };
      case "presenting":
        return { label: `Presenting · ${clock(elapsed)}`, tone: "live" };
      case "asking":
        return { label: `Paused · ${nameOf(asker ?? CHAIR)} is asking`, tone: "paused" };
      case "answering":
        return { label: `Your answer · ${nameOf(asker ?? CHAIR)} is listening`, tone: "live" };
      case "handing":
        return { label: `${nameOf(asker ?? CHAIR)} is responding`, tone: "paused" };
      case "conferring":
        return { label: "The panel is conferring", tone: "paused" };
      case "qa-speaking":
        return { label: `Q&A · question ${qn}`, tone: "paused" };
      case "qa-listening":
        return { label: `Q&A · your answer`, tone: "live" };
      case "qa-thinking":
        return { label: `${nextName} is thinking`, tone: "paused" };
      case "closing":
        return { label: "Wrapping up", tone: "paused" };
      case "done":
        return { label: "Finished", tone: "idle" };
    }
  })();

  const seats = [{ id: CHAIR, name: "Vik", glyph: "vik", role: "Chair" }, ...seated.map((id) => ({ id, name: nameOf(id), glyph: glyphOf(id), role: byId.get(id)?.firm ?? "" }))];
  const spoken = pitch?.ledger ?? deck?.slides.flatMap((s) => s.claims) ?? [];
  const ledger = session ? [...spoken, ...session.claims.map((c, i): LedgerRow => ({ id: `qa-${i}-${c.turn_seq}`, slide: null, source: "spoken", t_ms: null, text: c.text, metric: c.metric, value: c.value, unit: c.unit, status: c.status, explanation: c.explanation, figure_id: c.figure_id, truth: null, truth_label: null }))] : spoken;
  const kbRows = pitch?.kb ?? deck?.slides.flatMap((s) => s.kb ?? []) ?? [];
  const slideSeconds = (deck ? Array.from({ length: deck.slides.length }, (_, i) => slideMs[i] ?? 0) : [slideMs.reduce((a, b) => a + b, 0)]).map((ms) => ms / 1000);
  const busy = ["opening", "asking", "handing", "conferring", "qa-speaking", "qa-thinking", "closing"].includes(phase);

  const mainLabel = phase === "setup" ? "Start" : phase === "done" ? "New pitch" : inQa ? "End Q&A" : "End";
  const mainHint =
    phase === "setup"
      ? mode === "live"
        ? "Start, then present. An investor stops you when a claim doesn't match your data or your own notes."
        : "Start, then present. Press End when you finish; the Q&A follows, with every gap between your pitch and your notes."
      : presenting
        ? mode === "live"
          ? "Speak naturally. Answer a question out loud and carry on; press End to finish."
          : "The panel is listening. Press End when you've finished the pitch."
        : inQa
          ? "Answer out loud; a pause ends your answer. End Q&A finishes early."
          : phase === "done"
            ? session?.report_id
              ? "The report has every question, how each answer scored and what to fix."
              : "The ledger on the right has every claim and what the data says."
            : "";
  const mainDisabled = phase === "setup" ? blocked || seated.length === 0 || uploading : phase === "closing";

  return (
    <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[minmax(220px,260px)_minmax(0,1fr)_minmax(260px,320px)]">
      <VcRoster
        personas={personas.data}
        loading={personas.loading}
        error={personas.error ? errorText(personas.error) : null}
        onRetry={personas.reload}
        selected={seated}
        locked={phase !== "setup"}
        speaking={speaking ?? undefined}
        onToggle={(id) =>
          setChosen((cur) => {
            // Ids the Areopagus no longer has (an old link, a deleted custom investor) don't hold a seat.
            const s = cur.filter((x) => !known || known.includes(x));
            if (s.includes(id)) return s.filter((x) => x !== id);
            return s.length >= MAX_PANEL ? s : [...s, id];
          })
        }
      />

      <div ref={room} className={cn("flex min-h-[620px] min-w-0 flex-col gap-3 lg:min-h-0", full && "bg-bg p-4")}>
        <Panel
          title={mode === "live" ? "Pitch room · interrupt live" : "Pitch room · questions after"}
          marks
          className="relative flex-1"
          aside={
            <div className="flex flex-wrap items-center justify-end gap-2">
              <Segmented
                label="Interruptions"
                value={mode}
                onChange={setMode}
                disabled={phase !== "setup"}
                options={[
                  { value: "live", label: "Interrupt live" },
                  { value: "after", label: "Questions after" },
                ]}
              />
              <button
                type="button"
                onClick={() => (full ? void document.exitFullscreen() : void room.current?.requestFullscreen?.())}
                className="flex size-7 items-center justify-center rounded-[3px] border border-line text-ink-2 hover:border-line-strong hover:text-ink"
                aria-label={full ? "Leave full screen" : "Full screen"}
                title={full ? "Leave full screen" : "Full screen"}
              >
                {full ? <Minimize2 className="size-3.5" strokeWidth={1.5} /> : <Maximize2 className="size-3.5" strokeWidth={1.5} />}
              </button>
            </div>
          }
          bodyClassName="relative flex min-h-0 flex-col p-3 md:p-4"
        >
          <StageNotice
            gate={gate}
            onRetry={() => {
              setGate({ kind: "checking" });
              setAttempt((n) => n + 1);
            }}
          />
          <div className={cn("flex min-h-0 flex-1 flex-col transition-opacity duration-500", blocked && gate.kind !== "checking" && "opacity-45")}>
            <SlideStage
              deck={deck}
              index={slide}
              onIndex={goTo}
              seats={seats}
              speaking={speaking}
              status={status}
              caption={caption}
              toast={toast}
              ledger={pitch?.ledger ?? []}
              kb={pitch?.kb ?? []}
              setup={phase === "setup" && !blocked}
              uploading={uploading}
              onUpload={(f) => void upload(f)}
              onRemove={() => {
                setDeck(null);
                goTo(0);
              }}
              onSkip={running ? () => hush.current?.abort() : undefined}
              level={level}
              listening={listening && !typing}
            />

            {phase === "done" && (
              <div className="mx-auto mt-3 flex w-full max-w-[860px] flex-wrap items-center justify-between gap-3 rounded-[4px] border border-line px-4 py-3">
                <p className="text-[13px] text-ink-2">
                  {session ? "Q&A finished." : "Pitch finished."} {pitch?.interrupts.length ? `Interrupted ${pitch.interrupts.length}×. ` : ""}
                  {pitch?.stats ? `${pitch.stats.words} words spoken.` : ""}
                </p>
                {session?.report_id && <PillLink href={`/reports/${encodeURIComponent(session.report_id)}`} label="Open the report" variant="solid" />}
              </div>
            )}
          </div>
        </Panel>

        {addedName && phase === "setup" && (
          <p role="status" className="flex items-center justify-between gap-3 px-2 text-[12px] text-ink-2" data-testid="added-note">
            <span>
              {seated.includes(added!) ? `Built ${addedName} and seated them on the panel.` : `Built ${addedName}. The panel is full; swap someone out to seat them.`}
            </span>
            <button type="button" onClick={() => setAdded(null)} className="text-ink underline underline-offset-2 hover:text-ember">
              Dismiss
            </button>
          </p>
        )}
        {error && <ErrorNote message={error} className="px-2" />}

        {/* One button runs the room: Start, then End. */}
        <div className="glass relative flex flex-wrap items-center gap-4 rounded-[4px] px-4 py-3">
          <CornerMarks />
          <button
            type="button"
            onClick={() => void (phase === "setup" ? start() : phase === "done" ? fresh() : end())}
            disabled={mainDisabled}
            aria-label={mainLabel}
            data-testid="sim-mic"
            className={cn(
              "group flex h-12 shrink-0 items-center gap-2.5 rounded-full pr-5 pl-1.5 text-[14px] font-medium transition-all disabled:opacity-40",
              running ? "bg-ember text-black hover:brightness-110" : "bg-invert-bg text-invert-ink hover:opacity-90",
            )}
          >
            <span className={cn("relative flex size-9 items-center justify-center rounded-full", running ? "bg-black/15" : "bg-white/10")}>
              {listening && <span className="absolute inset-0 animate-ping rounded-full bg-black/20" aria-hidden />}
              {phase === "setup" ? (
                <Mic className="size-4" strokeWidth={1.75} />
              ) : phase === "done" ? (
                <RotateCcw className="size-4" strokeWidth={1.75} />
              ) : phase === "closing" || phase === "conferring" ? (
                <Loader2 className="size-4 animate-spin" strokeWidth={1.75} />
              ) : (
                <Square className="size-3.5 fill-current" strokeWidth={1.75} />
              )}
            </span>
            {mainLabel}
          </button>

          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <p className="text-[12.5px] leading-snug text-ink-2">{mainHint || (busy ? "…" : "")}</p>
            {running && typing && phase !== "closing" && (
              <form
                className="flex gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  sendTyped();
                }}
              >
                <input
                  value={typed}
                  onChange={(e) => setTyped(e.target.value)}
                  maxLength={4000}
                  disabled={!listening}
                  placeholder={listening ? "Type what you'd say, then Enter." : "Wait for the panel…"}
                  aria-label="Type what you'd say"
                  className="h-8 min-w-0 flex-1 rounded-[3px] border border-line bg-transparent px-2.5 text-[13px] outline-none focus:border-line-strong disabled:opacity-50"
                />
              </form>
            )}
          </div>

          {!typing && (phase === "answering" || phase === "qa-listening") && (
            <PillButton label="Done answering" variant="outline" onClick={() => void takeTurn()} className="h-8" />
          )}
          {phase === "setup" && gate.kind === "ready" && !voiceOn && (
            <span className="text-[11.5px] text-dim">Voice is off on this server (no ElevenLabs key), so the panel&apos;s lines show as captions and you type.</span>
          )}
          {phase === "setup" && voiceOn && !micOn && (
            <span className="text-[11.5px] text-dim">This browser can&apos;t stream the microphone, so the panel speaks and you type.</span>
          )}
        </div>
      </div>

      <div className="flex min-h-[560px] lg:min-h-0 [&>*]:flex-1">
        <ScorePanel ledger={ledger} kb={kbRows} scores={scores} slideSeconds={slideSeconds} fillers={pitch?.stats?.fillers ?? null} current={deck ? slide : undefined} />
      </div>
    </div>
  );
}
