/**
 * Turns a court `Session` from the API into feed items and the questions list. Pure mapping:
 * every number shown comes from the session (judge scores, claim checks, cited figures).
 */

import type { FeedClaim, FeedItem } from "@/components/prep/ChatFeed";
import { worstStatus } from "@/components/prep/ClaimChip";
import type { QA } from "@/components/prep/QuestionList";
import type { Claim, PersonaSummary, Score, Session } from "./types";

export const CHAIR = "vicky";

export function scoreDims(s: Score) {
  return [
    // The judge scores accuracy 0–1 (share of claims that hold); the other dimensions 0–5.
    { label: "Accuracy", value: s.accuracy, max: 1 },
    { label: "Evidence", value: s.dims.evidence ?? null },
    { label: "Clarity", value: s.dims.clarity ?? null },
    { label: "Composure", value: s.dims.composure ?? null },
    { label: "Investor fit", value: s.dims.investor_fit ?? null },
  ];
}

/** Mean of the judge's four 0–5 dimensions (display summary only; accuracy shows as the claim chip). */
export function scoreMean(s: Score): number | null {
  const v = [s.dims.evidence, s.dims.clarity, s.dims.composure, s.dims.investor_fit]
    .filter((x): x is number => typeof x === "number");
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
}

const toFeedClaim = (c: Claim): FeedClaim => ({ status: c.status, text: c.text, explanation: c.explanation });

export function sessionFeed(session: Session, personas: PersonaSummary[] | undefined): FeedItem[] {
  const panel = new Map([...(personas ?? []), ...session.panel].map((p) => [p.id, p]));
  const claimsBySeq = new Map<number, Claim[]>();
  for (const c of session.claims) claimsBySeq.set(c.turn_seq, [...(claimsBySeq.get(c.turn_seq) ?? []), c]);
  const scoreBySeq = new Map(session.scores.map((s) => [s.turn_seq, s]));
  const coached = session.settings.coaching === "coached";
  const out: FeedItem[] = [];

  for (const t of session.turns) {
    const id = `t${t.seq}`;
    if (t.kind === "answer" || t.speaker === "founder") {
      const claims = (claimsBySeq.get(t.seq) ?? []).map(toFeedClaim);
      out.push({ id, kind: "founder", text: t.text, claims });
      const s = scoreBySeq.get(t.seq);
      if (s && coached) out.push({ id: `${id}-score`, kind: "score", dims: scoreDims(s), rationale: s.rationale });
      continue;
    }
    if (t.kind === "coach") {
      out.push({ id, kind: "coach", text: t.text, citations: t.citations });
      continue;
    }
    const chair = t.speaker === CHAIR;
    const p = panel.get(t.speaker);
    out.push({
      id,
      kind: "vc",
      chair,
      name: t.speaker_name || p?.name || (chair ? "Vicky" : "Investor"),
      firm: chair ? "Chair" : p?.firm,
      glyph: chair ? "vicky" : (p?.glyph ?? "custom"),
      text: t.text,
      citations: t.citations,
    });
  }
  if (session.report_id) out.push({ id: `report-${session.report_id}`, kind: "report", reportId: session.report_id });
  return out;
}

export function sessionQuestions(session: Session): QA[] {
  const claimsBySeq = new Map<number, Claim[]>();
  for (const c of session.claims) claimsBySeq.set(c.turn_seq, [...(claimsBySeq.get(c.turn_seq) ?? []), c]);
  const scoreBySeq = new Map(session.scores.map((s) => [s.turn_seq, s]));
  const hide = session.settings.coaching === "realistic" && session.status === "live";
  const out: QA[] = [];
  const turns = session.turns;
  turns.forEach((t, i) => {
    if (t.kind !== "question" && t.kind !== "interject") return;
    const answer = turns.slice(i + 1).find((x) => x.kind === "answer" || x.speaker === "founder");
    const nextQ = turns.slice(i + 1).findIndex((x) => x.kind === "question" || x.kind === "interject");
    const answered = answer && (nextQ === -1 || turns.indexOf(answer) < i + 1 + nextQ);
    const s = answered ? scoreBySeq.get(answer.seq) : undefined;
    out.push({
      id: String(t.seq),
      vc: t.speaker_name,
      question: t.text,
      answer: answered ? answer.text : null,
      score: s && !hide ? scoreMean(s) : null,
      status: answered ? worstStatus((claimsBySeq.get(answer.seq) ?? []).map((c) => c.status)) : null,
    });
  });
  return out;
}

/** Questions asked per VC id. */
export function questionCounts(session: Session): Record<string, number> {
  const out: Record<string, number> = {};
  for (const t of session.turns) if (t.kind === "question" || t.kind === "interject") out[t.speaker] = (out[t.speaker] ?? 0) + 1;
  return out;
}

/** Who has the floor: the last panel speaker while the founder is answering. */
export function lastSpeaker(session: Session): string | null {
  for (let i = session.turns.length - 1; i >= 0; i--) {
    const t = session.turns[i];
    if (t.kind !== "answer" && t.speaker !== "founder") return t.speaker;
  }
  return null;
}
