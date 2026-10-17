"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState, useSyncExternalStore } from "react";
import { useActiveEngagement } from "@/components/app/EngagementProvider";
import { PromptBar } from "@/components/app/PromptBar";
import { MAX_PANEL, VcRoster } from "@/components/app/VcRoster";
import { Panel } from "@/components/ui/Panel";
import { PillButton, PillLink } from "@/components/ui/Pill";
import { EmptyState, ErrorNote, Loading } from "@/components/ui/States";
import { ApiError, apiGet, apiPost } from "@/lib/api";
import { useChannel } from "@/lib/socket";
import { lastSpeaker, questionCounts, sessionFeed, sessionQuestions } from "@/lib/court";
import type { PersonaSummary, Session, SessionSummary } from "@/lib/types";
import { errorText, useAccessGuard, useApi } from "@/lib/use-api";
import { ChatFeed, type FeedFilter, type FeedItem } from "./ChatFeed";
import { FeedTabs } from "./FeedTabs";
import { QuestionList } from "./QuestionList";
import { SessionSetup, type SetupValue } from "./SessionSetup";

const DEFAULT_PANEL = ["james", "alex", "mark"];
const QUESTION_KEY = "vicky-question";

// A question typed on the landing page or dashboard waits in sessionStorage until the next session starts.
const noSubscribe = () => () => {};
const readPending = () => {
  try {
    return sessionStorage.getItem(QUESTION_KEY);
  } catch {
    return null;
  }
};

export function PrepView() {
  const router = useRouter();
  const params = useSearchParams();
  const sid = params.get("s");
  const guard = useAccessGuard();
  const { engagement } = useActiveEngagement();

  const personas = useApi<PersonaSummary[]>("areopagus");
  const fetched = useApi<Session>(sid ? `court/${encodeURIComponent(sid)}` : null);
  const recent = useApi<SessionSummary[]>(sid ? null : "sessions");
  const [live, setLive] = useState<Session | null>(null);
  const session = live && live.id === sid ? live : fetched.data && fetched.data.id === sid ? fetched.data : null;

  const pending = useSyncExternalStore(noSubscribe, readPending, () => null);
  const [chosen, setChosen] = useState<string[] | null>(null);
  const [setup, setSetup] = useState<Omit<SetupValue, "focus"> & { focus: string | null }>({ cap: 8, coaching: "coached", focus: null });
  const [filter, setFilter] = useState<FeedFilter>("all");
  const [busy, setBusy] = useState<"start" | "answer" | "end" | null>(null);
  const [draft, setDraft] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [gate, setGate] = useState<string | null>(null);
  const [freshFrom, setFreshFrom] = useState(Number.POSITIVE_INFINITY);

  const known = personas.data?.map((p) => p.id);
  const selected = session
    ? session.panel.map((p) => p.id)
    : (chosen ?? DEFAULT_PANEL).filter((id) => !known || known.includes(id));
  const seatedNames = selected.map((id) => personas.data?.find((p) => p.id === id)?.name ?? id);

  const feed: FeedItem[] = useMemo(() => {
    if (!session) return [];
    const items = sessionFeed(session, personas.data);
    if (draft) items.push({ id: "draft", kind: "founder", text: draft });
    return items;
  }, [session, personas.data, draft]);
  const questions = useMemo(() => (session ? sessionQuestions(session) : []), [session]);
  const counts = useMemo(() => (session ? questionCounts(session) : undefined), [session]);

  const fail = (err: unknown) => {
    if (guard(err)) return;
    if (err instanceof ApiError && err.status === 409) setGate(err.detail || "Confirm a source of truth first.");
    else setError(errorText(err));
  };

  const start = async (focusOverride?: string) => {
    setBusy("start");
    setError(null);
    setGate(null);
    const focus = (focusOverride ?? setup.focus ?? pending ?? "").trim();
    try {
      const s = await apiPost<Session>("court/start", {
        panel: selected.slice(0, MAX_PANEL),
        question_cap: setup.cap,
        coaching: setup.coaching,
        ...(focus ? { focus } : {}),
      });
      try {
        sessionStorage.removeItem(QUESTION_KEY);
      } catch {}
      setFreshFrom(0);
      setLive(s);
      router.replace(`/preparation?s=${encodeURIComponent(s.id)}`, { scroll: false });
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  };

  const answer = async (text: string) => {
    if (!session) {
      void start(text);
      return;
    }
    setBusy("answer");
    setError(null);
    setDraft(text);
    setFreshFrom(feed.length + 1);
    try {
      setLive(await apiPost<Session>(`court/${session.id}/answer`, { text }));
    } catch (err) {
      fail(err);
    } finally {
      setDraft(null);
      setBusy(null);
    }
  };

  const end = async () => {
    if (!session) return;
    setBusy("end");
    setError(null);
    setFreshFrom(feed.length);
    try {
      setLive(await apiPost<Session>(`court/${session.id}/end`));
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  };

  // Live session: other tabs' turns arrive as events, and after a reconnect (a redeploy, a dropped
  // connection) the session is re-read from the API, which keeps every turn in Postgres.
  const resync = () => {
    if (!sid || busy) return;
    apiGet<Session>(`court/${encodeURIComponent(sid)}`).then(
      (s) => setLive((cur) => (cur && cur.id === s.id && cur.turns.length > s.turns.length ? cur : s)),
      (err: unknown) => guard(err),
    );
  };
  useChannel(sid ? `session:${sid}` : null, resync, resync);

  const fresh = () => {
    setLive(null);
    setFreshFrom(Number.POSITIVE_INFINITY);
    router.replace("/preparation", { scroll: false });
  };

  const awaitingFounder = session?.status === "live" && session.awaiting !== "panel";
  const typingName =
    busy === "answer" || busy === "start"
      ? (personas.data?.find((p) => p.id === session?.next_speaker)?.name ?? "The panel")
      : undefined;
  const speaking = busy === "answer" ? session?.next_speaker : session?.status === "live" ? lastSpeaker(session) : null;

  // ---- centre panel body
  let body: React.ReactNode;
  if (sid && !session) {
    body =
      fetched.status === 404 ? (
        <EmptyState label="Court" title="That session is gone." body="Start a new one; your reports stay under Reports.">
          <PillButton variant="solid" label="New session" onClick={fresh} />
        </EmptyState>
      ) : fetched.error ? (
        <div className="p-4">
          <ErrorNote message={errorText(fetched.error)} onRetry={fetched.reload} />
        </div>
      ) : (
        <Loading label="Opening the court" className="p-4" />
      );
  } else if (!session && (gate || engagement === null)) {
    body = (
      <EmptyState
        label="Court"
        title="Confirm a source of truth first."
        body={gate && gate !== "Confirm a source of truth first." ? gate : "The panel checks every number you say against your data, so it needs data to check against."}
      >
        <PillLink href="/intake" label="Load data" variant="solid" />
      </EmptyState>
    );
  } else if (!session) {
    body = (
      <SessionSetup
        value={{ cap: setup.cap, coaching: setup.coaching, focus: setup.focus ?? pending ?? "" }}
        onChange={(v) => setSetup(v)}
        onStart={() => void start()}
        seated={seatedNames}
        starting={busy === "start"}
        recent={recent.data}
        onResume={(id) => router.replace(`/preparation?s=${encodeURIComponent(id)}`, { scroll: false })}
      />
    );
  } else {
    body = <ChatFeed messages={feed} filter={filter} freshFrom={freshFrom} typing={typingName} />;
  }

  const ended = session?.status === "ended";
  const placeholder = !session
    ? selected.length
      ? "Press Start, or tell Vicky what to focus on."
      : "Pick at least one investor to start."
    : ended
      ? "Session ended."
      : "Answer the panel. Cite where each number comes from.";

  return (
    <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[minmax(220px,260px)_minmax(0,1fr)_minmax(260px,320px)]">
      <VcRoster
        personas={personas.data}
        loading={personas.loading}
        error={personas.error ? errorText(personas.error) : null}
        onRetry={personas.reload}
        selected={selected}
        locked={!!session}
        counts={counts}
        speaking={speaking}
        onToggle={(id) =>
          setChosen((cur) => {
            const s = cur ?? selected;
            if (s.includes(id)) return s.filter((x) => x !== id);
            return s.length >= MAX_PANEL ? s : [...s, id];
          })
        }
      />

      <div className="flex min-h-[520px] min-w-0 flex-col gap-4 lg:min-h-0">
        <Panel
          title={session ? `Court · question ${Math.min(session.question_count, session.settings.question_cap)} of ${session.settings.question_cap}` : "Court"}
          marks
          aside={
            session ? (
              <div className="flex min-w-0 items-center gap-2">
                <FeedTabs value={filter} onChange={setFilter} />
                {!ended ? (
                  <PillButton label={busy === "end" ? "Ending" : "End"} variant="outline" disabled={!!busy} onClick={() => void end()} className="h-7" />
                ) : !session.report_id ? (
                  <PillButton label={busy === "end" ? "Writing" : "Get report"} variant="solid" disabled={!!busy} onClick={() => void end()} className="h-7" />
                ) : (
                  <PillButton label="New" variant="outline" onClick={fresh} className="h-7" />
                )}
              </div>
            ) : null
          }
          className="flex-1"
          bodyClassName="scroll-thin overflow-y-auto"
        >
          {body}
        </Panel>
        {error && <ErrorNote message={error} className="px-2" />}
        <PromptBar
          label="Your answer"
          placeholder={placeholder}
          onSubmit={(text) => void answer(text)}
          disabled={!!busy || ended || (!session && selected.length === 0) || (!!session && !awaitingFounder)}
          busy={busy === "answer" || busy === "start"}
          hint={
            session?.settings.coaching === "realistic"
              ? "Realistic mode: scores arrive with the report."
              : "Scores are written by an independent judge after each answer."
          }
        />
      </div>

      <div className="flex min-h-[420px] lg:min-h-0 [&>*]:flex-1">
        <QuestionList key={session?.id ?? "none"} items={questions} empty={session ? undefined : "Start a session and the panel's questions collect here."} />
      </div>
    </div>
  );
}
