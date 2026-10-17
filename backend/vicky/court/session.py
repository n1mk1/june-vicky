"""Prepare court: start → (answer → score → beliefs → referee → chair → speak)* → end → report.

Stateless between requests: the court state lives in `sessions.state` and the transcript in
`turns` (append-only), so any API instance can serve the next answer and a redeploy loses
nothing. Every event is also published on `session:{id}` for other tabs.

The minds come from `vicky.llm.minds`: Claude when a key is set, the deterministic minds otherwise
(and on any LLM failure). Every model call happens before the transaction that stores the turn.
"""

import asyncio
import copy
from dataclasses import dataclass
from typing import Any

from vicky import db
from vicky.areopagus import registry
from vicky.areopagus.schema import VCPersona
from vicky.court import minds, referee
from vicky.llm import minds as agents
from vicky.model.context import TruthContext
from vicky.model.truth import check_claim
from vicky.realtime import publish
from vicky.services import engagements

DEFAULT_CAP = 8


class CourtError(Exception):
    pass


def _speaker_name(speaker: str, panel: dict[str, VCPersona]) -> str:
    if speaker == "founder":
        return "You"
    if speaker == "vicky":
        return "Vicky"
    return panel[speaker].name if speaker in panel else speaker


async def _add_turn(conn, sid: str, speaker: str, kind: str, text: str, ctx: TruthContext, *, intent: str | None = None,
                    hyp: str | None = None, quotes: list[str] | None = None, audit_text: bool = True,
                    regenerated: bool = False) -> dict:
    seq = await conn.fetchval("select coalesce(max(seq), 0) + 1 from turns where session_id = $1", sid)
    citations, audit = [], None
    if audit_text:
        res = minds.audit_text(text, ctx.available(), quotes)
        citations = [c.model_dump(mode="json") for c in res.citations]
        audit = {"passed": res.passed, "regenerated": regenerated, "findings": [f.model_dump() for f in res.findings]}
    row = await conn.fetchrow(
        """insert into turns (session_id, seq, speaker, kind, intent, hypothesis_id, text, citations, audit)
           values ($1,$2,$3,$4::turn_kind,$5,$6,$7,$8,$9) returning id::text, seq""",
        sid, seq, speaker, kind, intent, hyp, text, citations, audit)
    return {"id": row["id"], "seq": row["seq"]}


def _hyp(state: dict, hyp_id: str | None) -> tuple[str | None, dict | None]:
    for vc, s in state["vcs"].items():
        for h in s["hyps"]:
            if h["id"] == hyp_id:
                return vc, h
    return None, None


async def start(panel_ids: list[str] | None, question_cap: int | None, coaching: str | None, focus: str | None) -> str:
    eid = await engagements.require_confirmed()
    ctx = await engagements.context(eid)
    panel = await registry.panel(panel_ids)
    cap = max(4, min(20, int(question_cap or DEFAULT_CAP)))
    coaching = coaching if coaching in ("coached", "realistic") else "coached"
    memos = await agents.build_memos(panel, ctx, focus)
    state: dict[str, Any] = {"vcs": {p.id: {"hyps": memos[p.id]["hypotheses"], "last_spoke": -99, "asked": []}
                                     for p in panel},
                             "thread": None, "turn_no": 0, "asked_bank": []}
    # Opening: the referee ranks opening bids; the chair picks; that VC speaks.
    bids = []
    for p in panel:
        hs = state["vcs"][p.id]["hyps"]
        if not hs:
            continue
        top = max(hs, key=lambda h: h["severity"] * (0.5 + p.weight(h["lens"])))
        bids.append(referee.Bid(p.id, round(top["confidence"] * (0.5 + top["severity"] / 2), 3), "new_topic", top["id"],
                                lane_fit=0.4 + 0.6 * p.weight(top["lens"])))
    ranked = referee.rank(bids, answer_weak=False)
    if not ranked:
        raise CourtError("No investor found anything to ask; check the source of truth")
    line = await _next_line(state, {p.id: p for p in panel}, ctx, ranked, question_count=0, cap=cap)
    async with db.pool().acquire() as conn, conn.transaction():
        sid = await conn.fetchval(
            """insert into sessions (engagement_id, truthpack_id, mode, panel, settings, agenda, state, status)
               values ($1, $2, 'prepare', $3, $4, $5, $6, 'live') returning id::text""",
            eid, ctx.truthpack_id, [p.id for p in panel],
            {"question_cap": cap, "coaching": coaching, "focus": focus},
            [{"hypothesis_id": h["id"], "lens": h["lens"], "owner_vc": vc} for vc, m in memos.items() for h in m["hypotheses"]],
            state)
        for p in panel:
            await conn.execute(
                """insert into memos (session_id, vc_id, persona_version, truthpack_version, memo)
                   values ($1, $2, $3, $4, $5)""", sid, p.id, p.version, ctx.version, memos[p.id])
        await _add_turn(conn, sid, "vicky", "intro", minds.intro(panel, ctx, coaching, cap), ctx)
        line_turn = await _store_line(conn, sid, line, ctx, ranked, after_seq=1)
        await conn.execute("update sessions set state = $2, question_count = 1 where id = $1", sid, state)
    await _publish_line(sid, line, line_turn)
    await publish(f"session:{sid}", "vc.turn.done", {"turn": "opening"})
    return sid


@dataclass
class _Line:
    """The next VC line, decided and worded before the transaction that stores it."""
    pick: agents.ChairPick
    vc: str
    hyp: dict
    intent: str
    text: str
    regenerated: bool
    quotes: list[str]


async def _next_line(state: dict, panel: dict[str, VCPersona], ctx: TruthContext, ranked: list[referee.Candidate], *,
                     answer: str = "", checks: list[dict] | None = None, weak: bool = False, question: str = "",
                     question_count: int = 0, cap: int = DEFAULT_CAP) -> _Line:
    """Chair pick + the VC's line; updates the court state (thread, asked, discussed) in place."""
    pick = await agents.chair(ranked, state, panel, weak=weak, question_count=question_count, cap=cap)
    top = pick.candidate
    p = panel[top.vc_id]
    vs = state["vcs"][p.id]
    asked = set(state.get("asked_bank", []))
    _, hyp = _hyp(state, top.target_hyp)
    if hyp is None:
        hyp = vs["hyps"][0]
    follow_up = top.intent == "follow_up" and bool(state.get("thread"))
    spoken = await agents.speak(p, hyp, ctx, top.intent, asked, answer=answer, question=question, checks=checks,
                                follow_up=follow_up)
    if follow_up:
        state["thread"]["depth"] += 1
    else:
        state["thread"] = {"vc": p.id, "hyp": hyp["id"], "depth": 0, "weak": 0}
    hyp["asked"] += 1
    state["asked_bank"] = sorted(asked)
    discussed = state.setdefault("discussed", [])
    for key in [hyp["attack_id"], *(f"fig:{e}" for e in hyp["evidence"])]:
        if key not in discussed:
            discussed.append(key)
    vs["last_spoke"] = state["turn_no"]
    quotes = [*(hyp.get("quotes") or []), *([answer] if answer else [])]
    return _Line(pick, p.id, hyp, top.intent, spoken.text, spoken.regenerated, quotes)


async def _store_line(conn, sid: str, line: _Line, ctx: TruthContext, ranked: list[referee.Candidate],
                      after_seq: int) -> dict:
    pk = line.pick
    await conn.execute(
        """insert into chair_decisions (session_id, after_turn_seq, candidates, decision, valid, fallback, latency_ms, reason)
           values ($1, $2, $3, $4, $5, $6, $7, $8)""",
        sid, after_seq, [c.__dict__ for c in ranked], pk.decision, pk.valid, pk.fallback, pk.latency_ms, pk.reason)
    return await _add_turn(conn, sid, line.vc, "question", line.text, ctx, intent=line.intent, hyp=line.hyp["id"],
                           quotes=line.quotes or None, regenerated=line.regenerated)


async def _publish_line(sid: str, line: _Line, turn: dict) -> None:
    await publish(f"session:{sid}", "chair.decision", line.pick.decision)
    await publish(f"session:{sid}", "vc.turn.done", {"turn_seq": turn["seq"], "speaker": line.vc})


async def answer(sid: str, text: str) -> None:
    text = (text or "").strip()
    if not text:
        raise CourtError("Type an answer first")
    sess = await db.fetchrow("select * from sessions where id::text = $1", sid)
    if sess is None:
        raise engagements.NotFound("session")
    if sess["status"] != "live":
        raise CourtError("This session has ended")
    ctx = await engagements.context(str(sess["engagement_id"]))
    panel = {p.id: p for p in await registry.panel(sess["panel"])}
    state = sess["state"]
    settings = sess["settings"]
    thread = state.get("thread") or {}
    cur_vc, hyp = _hyp(state, thread.get("hyp"))
    last_q = await db.fetchrow("select * from turns where session_id = $1 and kind = 'question' order by seq desc limit 1",
                               sess["id"])

    question = last_q["text"] if last_q else ""

    claims = await agents.extract_claims(text)
    checks = []
    for c in claims:
        r = check_claim(c["metric"], c["value"], c["unit"], ctx.figures, period=c.get("period"),
                        is_forecast=c.get("is_forecast", False), facts=ctx.facts)
        checks.append({**r.model_dump(mode="json"), "text": c["text"]})
    # The judge and every VC's belief update run in parallel; the VCs get code's weak/adequate call.
    weak_hint = minds.is_weak(minds.judge(text, hyp, checks, ctx, question))
    state["turn_no"] += 1
    discussed = set(state.get("discussed", []))
    results = await asyncio.gather(
        agents.judge(text, hyp, checks, ctx, question),
        *(agents.update_and_bid(p, state["vcs"][vid], checks, weak_hint, cur_vc, thread.get("hyp"),
                                state["turn_no"] - state["vcs"][vid]["last_spoke"], discussed, ctx=ctx, answer=text,
                                question=question)
          for vid, p in panel.items()))
    score, upds = results[0], dict(zip(panel, results[1:], strict=True))
    weak = minds.is_weak(score)
    if hyp is not None and weak:
        hyp["weak_answers"] += 1
        thread["weak"] = thread.get("weak", 0) + 1

    bids, belief_rows = [], []
    for vid, p in panel.items():
        vs, upd = state["vcs"][vid], upds[vid]
        belief_rows.append((vid, {"hypotheses": copy.deepcopy(vs["hyps"]), "deltas": upd["deltas"]}, upd))
        bids.append(referee.Bid(vid, upd["bid"], upd["intent"], upd["target_hyp"], lane_fit=upd["lane_fit"],
                                turns_since_spoke=state["turn_no"] - vs["last_spoke"], is_current=vid == cur_vc,
                                depth=thread.get("depth", 0), max_depth=p.style.follow_up_depth))

    count = sess["question_count"]
    cap = settings.get("question_cap", DEFAULT_CAP)
    ended, coach, line, ranked = count >= cap, None, None, []
    if not ended:
        ranked = referee.rank(bids, answer_weak=weak)
        if settings.get("coaching") == "coached" and hyp is not None and thread.get("weak", 0) >= 2:
            coach = minds.coach_card(hyp, ctx)
            for s_ in state["vcs"].values():  # the chair closed this topic for everyone
                for h_ in s_["hyps"]:
                    if h_["attack_id"] == hyp["attack_id"]:
                        h_["status"] = "confirmed"
            state["thread"] = None
            ranked = [c for c in referee.rank([b for b in bids if b.target_hyp != hyp["id"]], answer_weak=False)
                      if c.intent != "follow_up"]
        if not ranked:
            ended = True
        else:
            line = await _next_line(state, panel, ctx, ranked, answer=text, checks=checks, weak=weak, question=question,
                                    question_count=count, cap=cap)

    async with db.pool().acquire() as conn, conn.transaction():
        turn = await _add_turn(conn, sid, "founder", "answer", text, ctx, audit_text=False)
        for c in checks:
            await conn.execute(
                """insert into claims (session_id, turn_id, text, metric, value, unit, period, is_forecast, status, figure_id,
                     figure, severity) values ($1,$2,$3,$4,$5,$6,$7,$8,$9::claim_status,$10,$11,$12)""",
                sess["id"], turn["id"], c["text"], c["metric"], c["value"], c["unit"], None, False, c["status"],
                c.get("figure_id"), c.get("figure"), 0.85 if c["status"] == "contradicts" else 0.3)
        await conn.execute(
            "insert into scores (turn_id, question_turn_id, accuracy, dims, rationale) values ($1, $2, $3, $4, $5)",
            turn["id"], last_q["id"] if last_q else None, score["accuracy"], score["dims"], score["rationale"])
        for vid, snapshot, upd in belief_rows:
            await conn.execute(
                """insert into beliefs (session_id, vc_id, turn_seq, state, bid, intent, target_hyp)
                   values ($1, $2, $3, $4, $5, $6, $7) on conflict do nothing""",
                sess["id"], vid, turn["seq"], snapshot, upd["bid"], upd["intent"], upd["target_hyp"])
        if coach:
            await _add_turn(conn, sid, "vicky", "coach", coach, ctx)
        line_turn = None
        if line is not None:
            line_turn = await _store_line(conn, sid, line, ctx, ranked, after_seq=turn["seq"])
            await conn.execute("update sessions set state = $2, question_count = question_count + 1 where id = $1",
                               sess["id"], state)
        else:
            await conn.execute("update sessions set state = $2 where id = $1", sess["id"], state)
    if settings.get("coaching") == "coached":
        await publish(f"session:{sid}", "score.ready", {"turn_seq": turn["seq"]})
    if coach and hyp is not None:
        await publish(f"session:{sid}", "coach.timeout", {"hypothesis_id": hyp["id"]})
    if line is not None and line_turn is not None:
        await _publish_line(sid, line, line_turn)
    if ended:
        await end(sid)


async def end(sid: str) -> str:
    from vicky import report

    sess = await db.fetchrow("select * from sessions where id::text = $1", sid)
    if sess is None:
        raise engagements.NotFound("session")
    existing = await db.fetchval("select id::text from reports where session_id = $1", sess["id"])
    if existing:
        return existing
    ctx = await engagements.context(str(sess["engagement_id"]))
    panel = {p.id: p for p in await registry.panel(sess["panel"], strict=False)}
    async with db.pool().acquire() as conn, conn.transaction():
        await _add_turn(conn, sid, "vicky", "debrief",
                        "That's time. Your report is ready: every question, how each answer scored, the strong answer "
                        "with its sources, and what to drill next.", ctx)
        await conn.execute("update sessions set status = 'ended', ended_at = now() where id = $1", sess["id"])
    rid = await report.build(sid, ctx, panel)
    await publish(f"session:{sid}", "session.ended", {"report_id": rid})
    return rid


async def view(sid: str) -> dict:
    sess = await db.fetchrow("select * from sessions where id::text = $1", sid)
    if sess is None:
        raise engagements.NotFound("session")
    panel_list = await registry.panel(sess["panel"], strict=False)
    panel = {p.id: p for p in panel_list}
    turns = await db.fetch("select * from turns where session_id = $1 order by seq", sess["id"])
    seq_of = {str(t["id"]): t["seq"] for t in turns}
    scores = await db.fetch("select s.* from scores s join turns t on t.id = s.turn_id where s.turn_id = any($1::uuid[]) "
                            "order by t.seq", [t["id"] for t in turns])
    claims = await db.fetch("select * from claims where session_id = $1 order by created_at", sess["id"])
    lens_of = {h["id"]: h["lens"] for s in sess["state"]["vcs"].values() for h in s["hyps"]}
    rid = await db.fetchval("select id::text from reports where session_id = $1", sess["id"])
    out_turns = [{"seq": t["seq"], "speaker": t["speaker"], "speaker_name": _speaker_name(t["speaker"], panel),
                  "kind": t["kind"], "text": t["text"], "lens": lens_of.get(t["hypothesis_id"] or ""),
                  "hypothesis_id": t["hypothesis_id"], "intent": t["intent"], "citations": t["citations"] or [],
                  "created_at": t["created_at"]} for t in turns]
    last = turns[-1] if turns else None
    awaiting = None if sess["status"] != "live" else ("founder" if last and last["kind"] in ("question", "coach", "intro") else "panel")
    return {"id": str(sess["id"]), "status": "ended" if sess["status"] == "ended" else "live", "mode": sess["mode"],
            "panel": [p.summary() for p in panel_list], "settings": sess["settings"], "turns": out_turns,
            "scores": [{"turn_seq": seq_of.get(str(s["turn_id"])), "accuracy": float(s["accuracy"]) if s["accuracy"] is not None else None,
                        "dims": s["dims"], "rationale": s["rationale"]} for s in scores],
            "claims": [{"turn_seq": seq_of.get(str(c["turn_id"])), "text": c["text"], "metric": c["metric"],
                        "value": float(c["value"]) if c["value"] is not None else None, "unit": c["unit"],
                        "status": c["status"], "explanation": _claim_note(c),
                        "figure_id": c["figure_id"]} for c in claims],
            "question_count": sess["question_count"], "awaiting": awaiting,
            "next_speaker": None, "report_id": rid, "started_at": sess["started_at"]}


def _claim_note(c: dict) -> str:
    f = c["figure"] or {}
    if c["status"] == "matches":
        return f"Matches {f.get('label', 'the data')} ({f.get('display', '')})."
    if f:
        return f"The data says {f.get('label', '').lower()} is {f.get('display', '')}."
    return "No figure in the data backs this."


async def list_sessions() -> list[dict]:
    rows = await db.fetch(
        """select s.id::text, s.mode::text, s.status::text, s.started_at, s.question_count, r.id::text as report_id
           from sessions s left join reports r on r.session_id = s.id order by s.started_at desc limit 30""")
    return rows
