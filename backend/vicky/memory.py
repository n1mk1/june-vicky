"""Founder memory (`founder_memory`): the questions the founder marked to drill, and the weak spots each
report left, read back when the next Prepare session starts so they shape its agenda.

- Drills (kind `drill`) are saved from the Questions list ("Drill N selected"): one row per marked question,
  `repeat` (ask it again) or `study` (the founder will study the topic first). A session that starts takes the
  pending ones (or the ones it was given) and marks them used.
- Weak spots (kind `weakness`) are written by the report: the open doubts of the last sessions.

Code only orders the agenda and raises a carried doubt's severity (a drilled one by more); it never lowers a
doubt or its confidence (the no-concession rule) and produces no figure. The referee still ranks the bids and
Vicky's chair still picks: a drilled topic is put at the top of the ranked list while it hasn't been asked,
the way a due knowledge check is (`agenda_candidate`).
"""

from typing import Any

from vicky import db
from vicky.areopagus.schema import VCPersona
from vicky.court import knowledge, referee
from vicky.court import minds as court_minds
from vicky.model.context import TruthContext

MARKS = ("repeat", "study")
DRILL_BOOST = {"repeat": 0.3, "study": 0.2}
WEAK_BOOST = 0.1
WEAK_SESSIONS = 3     # weak spots from the last N reports
MAX_DRILLS = 10
MAX_WEAK = 15


def _hyp_of(state: dict, hyp_id: str | None) -> tuple[str | None, dict | None]:
    for vc, s in state["vcs"].items():
        for h in s["hyps"]:
            if h["id"] == hyp_id:
                return vc, h
    return None, None


# ---------------------------------------------------------------- write

async def save_drills(sid: str, items: list[dict]) -> list[dict]:
    """Store the marked questions of session `sid` as drills. `items` are `{seq, mark}`; re-marking a
    question replaces its pending drill. Returns the stored drills."""
    sess = await db.fetchrow("select id, engagement_id, state from sessions where id::text = $1", sid)
    if sess is None:
        raise KeyError("session")
    marks = {int(i["seq"]): i["mark"] for i in items if i.get("mark") in MARKS}
    if not marks:
        return []
    turns = await db.fetch(
        """select id::text, seq, speaker, intent, hypothesis_id, text from turns
           where session_id = $1 and kind in ('question', 'interject') and seq = any($2::int[]) order by seq""",
        sess["id"], list(marks))
    state = sess["state"] or {"vcs": {}}
    out = []
    async with db.pool().acquire() as conn, conn.transaction():
        for t in turns:
            mark = marks[t["seq"]]
            _, h = _hyp_of(state, t["hypothesis_id"])
            pr = knowledge.probe(state, t["hypothesis_id"]) if h is None else None
            lens = h["lens"] if h else (pr or {}).get("lens")
            topic = h["claim"] if h else (pr or {}).get("topic") or t["text"][:120]
            payload = {"session_id": sid, "turn_id": t["id"], "seq": t["seq"], "mark": mark, "question": t["text"],
                       "vc_id": t["speaker"], "intent": t["intent"], "hypothesis_id": t["hypothesis_id"],
                       "attack_id": h["attack_id"] if h else None,
                       "note_path": ((pr or {}).get("expected") or {}).get("path")}
            await conn.execute(
                """delete from founder_memory where engagement_id = $1 and kind = 'drill'
                     and payload->>'turn_id' = $2 and not payload ? 'used_by'""", sess["engagement_id"], t["id"])
            mid = await conn.fetchval(
                """insert into founder_memory (engagement_id, kind, lens, topic, payload, severity)
                   values ($1, 'drill', $2, $3, $4, $5) returning id::text""",
                sess["engagement_id"], lens, topic, payload, h["severity"] if h else None)
            out.append({"id": mid, "seq": t["seq"], "mark": mark, "topic": topic, "lens": lens})
    return out


async def mark_used(ids: list[str], sid: str) -> None:
    if ids:
        await db.execute(
            """update founder_memory set payload = payload || jsonb_build_object('used_by', $2::text), last_seen_at = now()
               where id::text = any($1::text[])""", ids, sid)


# ---------------------------------------------------------------- read

async def recall(eid: str, drill_ids: list[str] | None = None) -> dict[str, list[dict]]:
    """Drills (the given ones, or every pending one, in the order they were marked) and the weak spots of
    the last `WEAK_SESSIONS` reports (most severe first)."""
    if drill_ids:
        drills = await db.fetch(
            """select id::text, lens, topic, payload, severity from founder_memory
               where engagement_id = $1 and kind = 'drill' and id::text = any($2::text[])
               order by last_seen_at desc, (payload->>'seq')::int limit $3""", eid, drill_ids, MAX_DRILLS)
    else:
        drills = await db.fetch(
            """select id::text, lens, topic, payload, severity from founder_memory
               where engagement_id = $1 and kind = 'drill' and not payload ? 'used_by'
               order by last_seen_at desc, (payload->>'seq')::int limit $2""", eid, MAX_DRILLS)
    weak = await db.fetch(
        """select id::text, lens, topic, payload, severity from founder_memory
           where engagement_id = $1 and kind = 'weakness' and payload->>'session_id' in (
             select session_id::text from reports where engagement_id = $1 order by created_at desc limit $2)
           order by severity desc nulls last, last_seen_at desc limit $3""", eid, WEAK_SESSIONS, MAX_WEAK)
    return {"drills": [dict(r) for r in drills], "weaknesses": [dict(r) for r in weak]}


# ---------------------------------------------------------------- the agenda (pure)

def _find(memos: dict[str, dict], row: dict) -> tuple[str | None, dict | None]:
    """The new session's hypothesis for a remembered topic: same attack item, else same doubt. A gap two
    investors share goes to the one who asked it last time, else to its main owner."""
    pl = row.get("payload") or {}
    aid, topic = pl.get("attack_id"), (row.get("topic") or "").strip().lower()
    for key in ("attack", "topic"):
        hits = [(vc, h) for vc, m in memos.items() for h in m["hypotheses"]
                if (key == "attack" and aid and h["attack_id"] == aid)
                or (key == "topic" and topic and h["claim"].strip().lower() == topic)]
        if hits:
            return min(hits, key=lambda x: (x[0] != pl.get("vc_id"), bool(x[1].get("shared"))))
    return None, None


def _seat(memos: dict[str, dict], panel: list[VCPersona], ctx: TruthContext, row: dict) -> tuple[str | None, dict | None]:
    """A drilled topic no one on this panel owns: the best-weighted investor takes it, if the attack item
    still exists in the data."""
    aid = (row.get("payload") or {}).get("attack_id")
    item = next((a for a in ctx.attack if a.id == aid), None) if aid else None
    if item is None or not panel:
        return None, None
    p = max(panel, key=lambda p: p.weight(item.lens))
    ids, n = {h["id"] for h in memos[p.id]["hypotheses"]}, len(memos[p.id]["hypotheses"]) + 1
    while f"{p.id}.h{n}" in ids:
        n += 1
    h = court_minds._hyp(item, p, n)
    memos[p.id]["hypotheses"].append(h)
    return p.id, h


def carry_over(memos: dict[str, dict], panel: list[VCPersona], ctx: TruthContext, memory: dict[str, list[dict]],
               cap: int) -> tuple[list[dict], list[str]]:
    """Apply remembered drills and weak spots to the new memos, in place.

    Returns (carried, queue): what came back and where, for the view; and the drilled hypotheses in agenda
    order (repeat before study, at most half the question cap) for `agenda_candidate`. Severity only goes up,
    confidence is never lowered."""
    carried: list[dict] = []
    queue: dict[str, list[str]] = {"repeat": [], "study": []}
    for row in memory.get("drills") or []:
        pl = row.get("payload") or {}
        mark = pl.get("mark") if pl.get("mark") in MARKS else "repeat"
        entry = {"memory_id": row["id"], "kind": "drill", "mark": mark, "topic": row.get("topic"),
                 "lens": row.get("lens"), "question": pl.get("question"), "from_session": pl.get("session_id"),
                 "hypothesis_id": None, "probe_id": None, "vc_id": None, "note_path": pl.get("note_path")}
        if pl.get("intent") == "knowledge" and not pl.get("attack_id"):
            carried.append(entry)  # matched to a knowledge check once the probes are written (`carry_probes`)
            continue
        vc, h = _find(memos, row)
        if h is None:
            vc, h = _seat(memos, panel, ctx, row)
        if h is not None:
            h["severity"] = round(min(1.0, h["severity"] + DRILL_BOOST[mark]), 2)
            h["drill"] = "repeat" if h.get("drill") == "repeat" else mark
            if h["id"] not in queue["repeat"] + queue["study"]:
                queue[mark].append(h["id"])
            entry |= {"hypothesis_id": h["id"], "vc_id": vc}
        carried.append(entry)
    for row in memory.get("weaknesses") or []:
        vc, h = _find(memos, row)
        if h is None or h.get("carried") == "weakness":
            continue
        pl = row.get("payload") or {}
        sev = float(row["severity"]) if row.get("severity") is not None else h["severity"]
        h["severity"] = round(max(h["severity"], min(1.0, sev + WEAK_BOOST)), 2)
        if pl.get("confidence") is not None:
            h["confidence"] = round(max(h["confidence"], float(pl["confidence"])), 2)  # the doubt stands as it was left
        h["carried"] = "weakness"
        carried.append({"memory_id": row["id"], "kind": "weakness", "mark": None, "topic": row.get("topic"),
                        "lens": row.get("lens"), "question": None, "from_session": pl.get("session_id"),
                        "hypothesis_id": h["id"], "probe_id": None, "vc_id": vc, "note_path": None})
    order = (queue["repeat"] + queue["study"])[:max(1, cap // 2)]
    for vc in memos:  # the memo lists drilled doubts first, then the rest by severity
        memos[vc]["hypotheses"].sort(key=lambda h: (h["id"] not in order, order.index(h["id"]) if h["id"] in order else 0))
    return carried, order


def carry_probes(carried: list[dict], probes: list[dict]) -> None:
    """A drilled knowledge check comes back as this session's check on the same note, when there is one."""
    for e in carried:
        if e["kind"] != "drill" or e["hypothesis_id"] or not e.get("note_path"):
            continue
        pr = next((p for p in probes if not p.get("drill") and (p.get("expected") or {}).get("path") == e["note_path"]), None)
        if pr is not None:
            pr["drill"] = e["mark"]
            e |= {"probe_id": pr["id"], "vc_id": pr["vc"]}


def agenda_candidate(state: dict, ranked: list[referee.Candidate], *, weak: bool) -> referee.Candidate | None:
    """Vicky's agenda: the next drilled topic not asked yet, at the top of the ranked list. Never right
    after a weak answer (the follow-up comes first); the chair may still pick another candidate."""
    if weak:
        return None
    for hid in state.get("drill_agenda") or []:
        vc, h = _hyp_of(state, hid)
        if h is None or h["asked"] or h["status"] != "open":
            continue
        top = max((c.score for c in ranked), default=0.5)
        return referee.Candidate(vc, "new_topic", hid, round(top + 0.05, 4),
                                 [f"Vicky: drilled last session ({h.get('drill') or 'repeat'})"])
    return None


def carried_view(state: dict, turns: list[Any], live: bool) -> list[dict]:
    """What came back from founder memory, and which question asked it."""
    first: dict[str, int] = {}
    for t in turns:
        if t["kind"] in ("question", "interject") and t["hypothesis_id"] and t["hypothesis_id"] not in first:
            first[t["hypothesis_id"]] = t["seq"]
    out = []
    for e in state.get("carried") or []:
        target = e.get("hypothesis_id") or e.get("probe_id")
        seq = first.get(target) if target else None
        status = "asked" if seq else "unmatched" if not target else "queued" if live else "not_reached"
        out.append({k: e.get(k) for k in ("memory_id", "kind", "mark", "topic", "lens", "question", "vc_id",
                                          "hypothesis_id", "probe_id")} | {"status": status, "asked_seq": seq})
    return out
