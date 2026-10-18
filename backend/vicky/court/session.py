"""Prepare court: start → (answer → score → beliefs → referee → chair → speak)* → end → report.

Stateless between requests: the court state lives in `sessions.state` and the transcript in
`turns` (append-only), so any API instance can serve the next answer and a redeploy loses
nothing. Every event is also published on `session:{id}` for other tabs.

The minds come from `vicky.llm.minds`: Claude when a key is set, the deterministic minds otherwise
(and on any LLM failure). Every model call happens before the transaction that stores the turn.

Once Fill dashboard has built the knowledge-base index, the court reads the founder's notes through retrieval
only (docs/08-RAG.md §Live court): passages per hypothesis at session start, and per answer in parallel with
claim extraction, so a turn takes no longer. The judge, the belief updates and the speaker get them; a line may
quote a note word for word and the audit checks it. A turn whose retrieval isn't confident gets no notes.

Vicky chairs. She picks who speaks (from the referee's ranked list), reviews every drafted line before it is
spoken (a line she sends back is rewritten once), scores every answer, and schedules knowledge checks:
questions written from the founder's own notes at session start, whose answers she verifies against the note
and a fresh retrieval over the answer (`vicky.court.knowledge`).

Founder memory shapes the start (`vicky.memory`): the questions the founder marked to drill go to the top of the
agenda (Vicky offers each as the top candidate until it's asked), and the weak spots of the last reports start
with a higher severity. The referee and the chair still decide; no doubt is lowered.
"""

import asyncio
import copy
import logging
from dataclasses import dataclass, field
from typing import Any

from vicky import db, memory
from vicky.areopagus import registry
from vicky.areopagus.schema import VCPersona
from vicky.audit import audit_text
from vicky.court import knowledge, minds, referee
from vicky.court import review as code_review
from vicky.llm import minds as agents
from vicky.model.context import TruthContext
from vicky.model.truth import check_claim
from vicky.realtime import publish
from vicky.services import engagements

DEFAULT_CAP = 8
log = logging.getLogger(__name__)
KB_KEYS = ("id", "note_id", "path", "title", "heading", "text", "cite")


async def _court_kb(query: str, k: int | None = None) -> tuple[list[dict], str | None]:
    """(passages, build id) for a court turn: the first retrieval pass only, and only when confident."""
    from vicky.config import get_settings
    from vicky.kb import rag

    try:
        r = await rag.retrieve(query, mode="court", k=k)
    except Exception as e:  # search must never break a turn
        log.info("court retrieval failed: %s", e)
        return [], None
    if not r.chunks or r.confidence < get_settings().rag_conf_min:
        return [], r.build_id
    log.info("court retrieval: %d passages, confidence %.2f, %d ms", len(r.chunks), r.confidence, r.ms)
    return [{k_: c[k_] for k_ in KB_KEYS} for c in r.chunks], r.build_id


async def _notes_for(kb: list[dict]) -> dict[str, dict] | None:
    """The notes behind `kb`, with their current content, for the audit."""
    if not kb:
        return None
    from vicky.kb.tools import Vault

    v = Vault()
    await v.keep_ids([c["note_id"] for c in kb])
    return v.notes() or None


async def _check_kb(query: str) -> tuple[list[dict], dict]:
    """Retrieval for verifying a knowledge answer: passages when confident, and what the search returned."""
    from vicky.config import get_settings
    from vicky.kb import rag

    try:
        r = await rag.retrieve(query, mode="court", k=4)
    except Exception as e:  # search must never break a turn
        log.info("knowledge retrieval failed: %s", e)
        return [], {"confidence": None, "build_id": None, "passages": 0}
    ok = bool(r.chunks) and r.confidence >= get_settings().rag_conf_min
    kb = [{k_: c[k_] for k_ in KB_KEYS} for c in r.chunks] if ok else []
    return kb, {"confidence": round(r.confidence, 3), "build_id": r.build_id, "passages": len(kb), "ms": r.ms}


def _expected_passage(pr: dict) -> dict:
    e = pr["expected"]
    return {"id": e.get("chunk_id"), "note_id": e.get("note_id"), "path": e.get("path"), "title": e.get("title"),
            "heading": e.get("heading"), "text": e.get("text") or e.get("quote") or "", "cite": e.get("cite")}


async def _no_probes() -> list[dict]:
    return []


async def _prose_notes(note_ids: list[str]) -> set[str]:
    """The founder's own writing among these notes: notes and documents. Tables and the organizer's hub
    notes are left out of knowledge checks (a hub's text is generated, a table has no sentence to recall)."""
    ids = sorted({i for i in note_ids if i})
    if not ids:
        return set()
    rows = await db.fetch("select id::text from kb_notes where id::text = any($1::text[]) and kind in ('note', 'document')",
                          ids)
    return {r["id"] for r in rows}


def _merge_kb(*lists: list[dict] | None) -> list[dict]:
    out: dict[str, dict] = {}
    for lst in lists:
        for c in lst or []:
            out.setdefault(c["id"], c)
    return list(out.values())[:6]


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
                    regenerated: bool = False, notes: dict[str, dict] | None = None,
                    review: dict | None = None) -> dict:
    seq = await conn.fetchval("select coalesce(max(seq), 0) + 1 from turns where session_id = $1", sid)
    citations, audit = [], None
    if audit_text:
        res = minds.audit_text(text, ctx.available(), quotes, notes=notes)
        citations = [c.model_dump(mode="json") for c in res.citations]
        audit = {"passed": res.passed, "regenerated": regenerated, "findings": [f.model_dump() for f in res.findings]}
    if review:
        audit = {**(audit or {}), "review": review}  # Vicky's review of the drafted line
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


async def start(panel_ids: list[str] | None, question_cap: int | None, coaching: str | None, focus: str | None,
                knowledge_on: bool = True, drills: list[str] | None = None) -> str:
    eid = await engagements.require_confirmed()
    ctx = await engagements.context(eid)
    panel = await registry.panel(panel_ids)
    cap = max(4, min(20, int(question_cap or DEFAULT_CAP)))
    coaching = coaching if coaching in ("coached", "realistic") else "coached"
    from vicky.kb.index import active_build_id

    build = await active_build_id()
    # Passages for knowledge checks (by each investor's lenses) are searched while the memos are written.
    lens_q = [(p.id, lens, q) for p in panel for lens, q in knowledge.lens_queries(p)] if build and knowledge_on else []
    memos, lens_found, remembered = await asyncio.gather(agents.build_memos(panel, ctx, focus),
                                                         asyncio.gather(*(_court_kb(q, k=3) for _, _, q in lens_q)),
                                                         memory.recall(eid, drills))
    carried, drill_agenda = memory.carry_over(memos, panel, ctx, remembered, cap)
    state: dict[str, Any] = {"vcs": {p.id: {"hyps": memos[p.id]["hypotheses"], "last_spoke": -99, "asked": []}
                                     for p in panel},
                             "thread": None, "turn_no": 0, "asked_bank": [], "asked_lines": [], "probes": [],
                             "knowledge_on": knowledge_on, "carried": carried, "drill_agenda": drill_agenda}
    passages: dict[str, list[tuple[str, dict]]] = {p.id: [] for p in panel}
    prose = await _prose_notes([c["note_id"] for kb, _b in lens_found for c in kb])
    for (vc, lens, _q), (kb, _b) in zip(lens_q, lens_found, strict=True):
        passages[vc] += [(lens, {**c, "text": c["text"][:800]}) for c in kb if c["note_id"] in prose]
    if build:
        # The founder's notes behind each doubt, fetched once before the first line; the knowledge
        # questions are drafted at the same time.
        hyps = [h for vs in state["vcs"].values() for h in vs["hyps"]]
        found, probes = await asyncio.gather(
            asyncio.gather(*(_court_kb(f"{h['claim']} {h.get('detail') or ''}", k=3) for h in hyps)),
            agents.build_probes(panel, passages, ctx) if any(passages.values()) else _no_probes())
        for h, (kb, _b) in zip(hyps, found, strict=True):
            h["kb"] = [{**c, "text": c["text"][:800]} for c in kb]  # a prefix is still a quotable span
        state["kb_build"] = build
        state["probes"] = probes
        memory.carry_probes(carried, probes)
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
    if (dc := memory.agenda_candidate(state, ranked, weak=False)) is not None:  # a drilled question opens
        ranked.insert(0, dc)
    line = await _next_line(state, {p.id: p for p in panel}, ctx, ranked, question_count=0, cap=cap, build=build)
    async with db.pool().acquire() as conn, conn.transaction():
        sid = await conn.fetchval(
            """insert into sessions (engagement_id, truthpack_id, mode, panel, settings, agenda, state, status)
               values ($1, $2, 'prepare', $3, $4, $5, $6, 'live') returning id::text""",
            eid, ctx.truthpack_id, [p.id for p in panel],
            {"question_cap": cap, "coaching": coaching, "focus": focus, "knowledge": knowledge_on},
            _agenda(memos, drill_agenda), state)
        for p in panel:
            await conn.execute(
                """insert into memos (session_id, vc_id, persona_version, truthpack_version, memo)
                   values ($1, $2, $3, $4, $5)""", sid, p.id, p.version, ctx.version, memos[p.id])
        await _add_turn(conn, sid, "vicky", "intro", minds.intro(panel, ctx, coaching, cap, bool(state["probes"])), ctx)
        line_turn = await _store_line(conn, sid, line, ctx, ranked, after_seq=1)
        await conn.execute("update sessions set state = $2, question_count = 1 where id = $1", sid, state)
    await memory.mark_used([r["id"] for r in remembered["drills"]], sid)
    await _publish_line(sid, line, line_turn)
    await publish(f"session:{sid}", "vc.turn.done", {"turn": "opening"})
    return sid


def _agenda(memos: dict[str, dict], drill_agenda: list[str]) -> list[dict]:
    """`sessions.agenda`: drilled topics first (in drill order), then every other doubt; each says what it
    carries over from founder memory."""
    rows = [{"hypothesis_id": h["id"], "lens": h["lens"], "owner_vc": vc, "severity": h["severity"],
             "carried": "drill_" + h["drill"] if h.get("drill") else h.get("carried")}
            for vc, m in memos.items() for h in m["hypotheses"]]
    return sorted(rows, key=lambda r: (r["hypothesis_id"] not in drill_agenda,
                                       drill_agenda.index(r["hypothesis_id"]) if r["hypothesis_id"] in drill_agenda else 0,
                                       r["carried"] is None))


@dataclass
class _Line:
    """The next VC line, decided and worded before the transaction that stores it."""
    pick: agents.ChairPick
    vc: str
    hyp: dict | None
    intent: str
    text: str
    regenerated: bool
    quotes: list[str]
    notes: dict[str, dict] | None = field(default=None)
    review: dict | None = field(default=None)
    target: str | None = field(default=None)  # hypothesis id, or probe id for a knowledge check


def _reviewed(first: dict, final: dict | None, revised: bool) -> dict:
    """What the turn records of Vicky's review: her first verdict, and whether the line was rewritten."""
    out = {k: first.get(k) for k in ("verdict", "issues", "note", "source")}
    out["revised"] = revised
    if final is not None:
        out["final"] = final.get("verdict")
    return out


async def _knowledge_line(state: dict, p: VCPersona, pick: agents.ChairPick, ctx: TruthContext,
                          question_count: int) -> _Line:
    pr = knowledge.probe(state, pick.candidate.target_hyp)
    if pr is None:  # the candidate came from this state, so this only happens on a corrupt state
        raise CourtError("That knowledge check is no longer available")
    prior = [q["text"] for q in state.get("asked_lines", []) if q.get("intent") != "knowledge"]
    spoken = await agents.ask_knowledge(p, pr, ctx)
    first = await agents.review_line(p, spoken.text, intent="knowledge", about=f"knowledge check on {pr['topic']}",
                                     asked=prior, answer_key=pr["expected"].get("quote"))
    text, revised, final = spoken.text, False, None
    if first["verdict"] == "revise" and spoken.source == "llm":
        again = await agents.ask_knowledge(p, pr, ctx, review={**first, "draft": spoken.text})
        final = code_review.review(again.text, asked=prior, intent="knowledge", answer_key=pr["expected"].get("quote"))
        # A rewrite that still fails code's checks gives way to the probe's own question, which passed them.
        text, revised = (again.text, True) if final["verdict"] == "approve" else (pr["question"], True)
    pr["asked"] = True
    state["last_knowledge_q"] = question_count
    state["thread"] = {"vc": p.id, "hyp": None, "probe": pr["id"], "depth": 0, "weak": 0}
    state["vcs"][p.id]["last_spoke"] = state["turn_no"]
    state.setdefault("asked_lines", []).append({"text": text, "intent": "knowledge"})
    return _Line(pick, p.id, None, "knowledge", text, revised, [], None, _reviewed(first, final, revised), pr["id"])


async def _next_line(state: dict, panel: dict[str, VCPersona], ctx: TruthContext, ranked: list[referee.Candidate], *,
                     answer: str = "", checks: list[dict] | None = None, weak: bool = False, question: str = "",
                     question_count: int = 0, cap: int = DEFAULT_CAP, kb: list[dict] | None = None,
                     build: str | None = None) -> _Line:
    """Vicky's pick, the VC's line and her review of it; updates the court state (thread, asked,
    discussed) in place."""
    pick = await agents.chair(ranked, state, panel, weak=weak, question_count=question_count, cap=cap)
    top = pick.candidate
    p = panel[top.vc_id]
    if top.intent == "knowledge":
        return await _knowledge_line(state, p, pick, ctx, question_count)
    vs = state["vcs"][p.id]
    asked = set(state.get("asked_bank", []))
    _, hyp = _hyp(state, top.target_hyp)
    if hyp is None:
        hyp = vs["hyps"][0]
    follow_up = top.intent == "follow_up" and bool((state.get("thread") or {}).get("hyp"))
    # The hypothesis's own passages count only while the build they came from is still the active one.
    hyp_kb = hyp.get("kb") if build and state.get("kb_build") == build else None
    line_kb = _merge_kb(kb, hyp_kb)
    notes = await _notes_for(line_kb)
    spoken = await agents.speak(p, hyp, ctx, top.intent, asked, answer=answer, question=question, checks=checks,
                                follow_up=follow_up, kb=line_kb, notes=notes)
    prior = [q["text"] for q in state.get("asked_lines", [])]
    first = await agents.review_line(p, spoken.text, intent=top.intent, about=hyp["claim"], asked=prior)
    revised, final = False, None
    if first["verdict"] == "revise" and spoken.source == "llm":
        again = await agents.speak(p, hyp, ctx, top.intent, asked, answer=answer, question=question, checks=checks,
                                   follow_up=follow_up, kb=line_kb, notes=notes, review={**first, "draft": spoken.text})
        final = code_review.review(again.text, asked=prior, intent=top.intent)
        # Keep the rewrite unless it fails code's checks where the first draft didn't.
        if final["verdict"] == "approve" or code_review.review(spoken.text, asked=prior, intent=top.intent)["issues"]:
            spoken, revised = again, True
    state.setdefault("asked_lines", []).append({"text": spoken.text, "intent": top.intent})
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
    return _Line(pick, p.id, hyp, top.intent, spoken.text, spoken.regenerated or revised, quotes, notes,
                 _reviewed(first, final, revised), hyp["id"])


async def _store_line(conn, sid: str, line: _Line, ctx: TruthContext, ranked: list[referee.Candidate],
                      after_seq: int) -> dict:
    pk = line.pick
    await conn.execute(
        """insert into chair_decisions (session_id, after_turn_seq, candidates, decision, valid, fallback, latency_ms, reason)
           values ($1, $2, $3, $4, $5, $6, $7, $8)""",
        sid, after_seq, [c.__dict__ for c in ranked], pk.decision, pk.valid, pk.fallback, pk.latency_ms, pk.reason)
    return await _add_turn(conn, sid, line.vc, "question", line.text, ctx, intent=line.intent, hyp=line.target,
                           quotes=line.quotes or None, regenerated=line.regenerated, notes=line.notes,
                           review=line.review)


async def _publish_line(sid: str, line: _Line, turn: dict) -> None:
    await publish(f"session:{sid}", "chair.decision", line.pick.decision)
    await publish(f"session:{sid}", "vc.turn.done", {"turn_seq": turn["seq"], "speaker": line.vc})


def _checked(kc: dict, pr: dict, answer_text: str, ctx: TruthContext, notes: dict[str, dict] | None) -> dict:
    """The verdict as stored: its explanation audited against the notes (citations kept). A note edited since
    the index was built can't be quoted any more, so the check is then recorded as not checked."""
    res = audit_text(kc["explanation"], ctx.available(), [answer_text], notes=notes)
    if res.passed:
        return {**kc, "citations": [c.model_dump(mode="json") for c in res.citations]}
    log.info("knowledge check %s: explanation failed the audit (%s)", pr["id"], res.feedback())
    return {**kc, "verdict": "unverified", "citations": [],
            "explanation": "Your notes changed after the search index was built, so this answer couldn't be checked. "
                           "Press Fill dashboard to rebuild it."}


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
    panel = {p.id: p for p in await registry.panel(sess["panel"], strict=False)}
    if set(panel) != set(sess["state"]["vcs"]):  # an investor was removed (or renamed) since the session started
        raise CourtError("An investor on this panel no longer exists. Start a new session.")
    state = sess["state"]
    settings = sess["settings"]
    thread = state.get("thread") or {}
    cur_vc, hyp = _hyp(state, thread.get("hyp"))
    pr = knowledge.probe(state, thread.get("probe"))  # the question was a knowledge check
    if pr is not None:
        cur_vc = thread.get("vc")
    last_q = await db.fetchrow("select * from turns where session_id = $1 and kind = 'question' order by seq desc limit 1",
                               sess["id"])

    question = last_q["text"] if last_q else ""

    # Retrieval runs alongside claim extraction (an LLM call), so it adds no time to the turn. On a knowledge
    # check, Vicky's own search over the answer is what she verifies it with, beside the note it was written from.
    kmeta: dict | None = None
    if pr is not None:
        claims, (found, kmeta) = await asyncio.gather(agents.extract_claims(text),
                                                      _check_kb(f"{pr['question']} {text}"))
        turn_kb, kb_build = _merge_kb([_expected_passage(pr)], found), kmeta.get("build_id")
    else:
        claims, (turn_kb, kb_build) = await asyncio.gather(
            agents.extract_claims(text), _court_kb(f"{text} {(hyp or {}).get('claim') or ''}"))
    turn_notes = await _notes_for(turn_kb)
    checks = []
    for c in claims:
        r = check_claim(c["metric"], c["value"], c["unit"], ctx.figures, period=c.get("period"),
                        is_forecast=c.get("is_forecast", False), facts=ctx.facts)
        checks.append({**r.model_dump(mode="json"), "text": c["text"]})
    # Vicky's score and every VC's belief update run in parallel; the VCs get code's weak/adequate call.
    weak_hint = minds.is_weak(minds.judge(text, hyp, checks, ctx, question))
    state["turn_no"] += 1
    discussed = set(state.get("discussed", []))

    async def scored() -> tuple[dict | None, dict]:
        kc = None
        if pr is not None:
            kc = await agents.verify_knowledge(pr, question, text, turn_kb, ctx, turn_notes)
            kc = _checked(kc, pr, text, ctx, turn_notes)
        return kc, await agents.judge(text, hyp, checks, ctx, question, kb=turn_kb, notes=turn_notes, check=kc)

    results = await asyncio.gather(
        scored(),
        *(agents.update_and_bid(p, state["vcs"][vid], checks, weak_hint, cur_vc, thread.get("hyp"),
                                state["turn_no"] - state["vcs"][vid]["last_spoke"], discussed, ctx=ctx, answer=text,
                                question=question, kb=turn_kb)
          for vid, p in panel.items()))
    (kcheck, score), upds = results[0], dict(zip(panel, results[1:], strict=True))
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
        # Vicky's orchestration: a knowledge check goes to the top of the list when one is due.
        if (kc := knowledge.candidate(state, ranked, question_count=count, cap=cap, weak=weak)) is not None:
            ranked.insert(0, kc)
        # ...but the questions the founder asked to drill come first, while any is left.
        if (dc := memory.agenda_candidate(state, ranked, weak=weak)) is not None:
            ranked.insert(0, dc)
        if not ranked:
            ended = True
        else:
            line = await _next_line(state, panel, ctx, ranked, answer=text, checks=checks, weak=weak, question=question,
                                    question_count=count, cap=cap, kb=turn_kb, build=kb_build)

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
        if kcheck is not None and pr is not None:
            exp = {k: pr["expected"].get(k) for k in ("cite", "path", "heading", "title", "quote")}
            await conn.execute(
                """insert into knowledge_checks (session_id, turn_id, question_turn_id, probe_id, vc_id, lens, verdict,
                     explanation, expected, citations, retrieval, source) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)""",
                sess["id"], turn["id"], last_q["id"] if last_q else None, pr["id"], pr["vc"], pr.get("lens"),
                kcheck["verdict"], kcheck["explanation"], exp, kcheck.get("citations") or [], kmeta,
                kcheck.get("source") or "offline")
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
    if kcheck is not None:
        await publish(f"session:{sid}", "knowledge.checked", {"turn_seq": turn["seq"], "verdict": kcheck["verdict"]})
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
    state = sess["state"]
    lens_of = {h["id"]: h["lens"] for s in state["vcs"].values() for h in s["hyps"]}
    lens_of |= {p["id"]: p.get("lens") for p in state.get("probes") or []}
    rid = await db.fetchval("select id::text from reports where session_id = $1", sess["id"])
    checks = await db.fetch("select * from knowledge_checks where session_id = $1 order by created_at", sess["id"])
    out_turns = [{"seq": t["seq"], "speaker": t["speaker"], "speaker_name": _speaker_name(t["speaker"], panel),
                  "kind": t["kind"], "text": t["text"], "lens": lens_of.get(t["hypothesis_id"] or ""),
                  "hypothesis_id": t["hypothesis_id"], "intent": t["intent"], "citations": t["citations"] or [],
                  "review": (t["audit"] or {}).get("review"), "created_at": t["created_at"]} for t in turns]
    probes = state.get("probes") or []
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
            "knowledge": [{"turn_seq": seq_of.get(str(k["turn_id"])), "question_seq": seq_of.get(str(k["question_turn_id"])),
                           "vc_id": k["vc_id"], "lens": k["lens"], "verdict": k["verdict"],
                           "label": knowledge.label(k["verdict"]), "explanation": k["explanation"],
                           "citations": k["citations"] or [], "expected": k["expected"], "retrieval": k["retrieval"]}
                          for k in checks],
            "knowledge_ready": {"on": bool(sess["settings"].get("knowledge", True)), "probes": len(probes),
                                "left": sum(1 for p in probes if not p["asked"])},
            "carried": memory.carried_view(state, turns, sess["status"] == "live"),
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
