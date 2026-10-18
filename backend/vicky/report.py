"""Session report (deterministic path): verdict, per-VC view, every question with its score and
strong answer, the claim ledger, knowledge gaps, an action plan and numbered sources.

Scores come from Vicky and the code accuracy check; knowledge checks are her verdicts on what the founder
recalled of their own notes; the synthesis here adds no figure that
isn't a Figure. The whole Markdown is audited before it is stored.
"""

from vicky import db
from vicky.areopagus.schema import LENS_LABELS, VCPersona
from vicky.audit import audit_text
from vicky.model.context import TruthContext
from vicky.model.sources import define_term, source_by_id

LENS_TERMS = {"retention": ["NRR", "GRR", "logo churn"], "forecast": ["CMGR"], "unit_economics": ["CAC payback", "burn multiple", "gross margin"],
              "runway": ["runway", "default alive"], "concentration": ["concentration"], "claims": ["ARR"],
              "terms_cap_table": ["SAFE", "pro rata"], "governance": ["SR&ED"]}


def _readiness(overall: float) -> str:
    return "ready" if overall >= 4.0 else "nearly_ready" if overall >= 3.0 else "not_ready"


async def build(sid: str, ctx: TruthContext, panel: dict[str, VCPersona]) -> str:
    sess = await db.fetchrow("select * from sessions where id::text = $1", sid)
    turns = await db.fetch("select * from turns where session_id = $1 order by seq", sess["id"])
    scores = {str(s["turn_id"]): s for s in await db.fetch(
        "select * from scores where turn_id = any($1::uuid[])", [t["id"] for t in turns])}
    claims = await db.fetch("select * from claims where session_id = $1 order by created_at", sess["id"])
    kchecks = await db.fetch("select * from knowledge_checks where session_id = $1 order by created_at", sess["id"])
    state = sess["state"]
    hyps = {h["id"]: (vc, h) for vc, s in state["vcs"].items() for h in s["hyps"]}

    questions, dim_sums, n = [], {"accuracy": 0.0, "evidence": 0.0, "clarity": 0.0, "composure": 0.0, "investor_fit": 0.0}, 0
    acc_n = 0
    for i, t in enumerate(turns):
        if t["kind"] != "question":
            continue
        ans = next((a for a in turns[i + 1:] if a["kind"] == "answer"), None)
        nxt_q = next((a for a in turns[i + 1:] if a["kind"] == "question"), None)
        if ans is None or (nxt_q is not None and nxt_q["seq"] < ans["seq"]):
            continue
        sc = scores.get(str(ans["id"]))
        if sc is None:
            continue
        n += 1
        for k in ("evidence", "clarity", "composure", "investor_fit"):
            dim_sums[k] += float(sc["dims"].get(k, 0))
        if sc["accuracy"] is not None:
            dim_sums["accuracy"] += float(sc["accuracy"]) * 5
            acc_n += 1
        vc, h = hyps.get(t["hypothesis_id"] or "", (t["speaker"], None))
        questions.append({
            "turn_id": str(t["id"]), "seq": t["seq"], "vc_id": t["speaker"],
            "vc_name": panel[t["speaker"]].name if t["speaker"] in panel else t["speaker"],
            "lens": h["lens"] if h else None, "question": t["text"], "why_asked": sc["rationale"].get("why_asked", ""),
            "answer": ans["text"], "scores": {"accuracy": float(sc["accuracy"]) if sc["accuracy"] is not None else None, **sc["dims"]},
            "good": sc["rationale"].get("good", ""), "missing": sc["rationale"].get("missing", ""),
            "correct_figure": sc["rationale"].get("correct_figure"), "strong_answer": sc["rationale"].get("strong_answer", ""),
            "citations": t["citations"] or []})
    dims = {k: round(dim_sums[k] / n, 2) for k in ("evidence", "clarity", "composure", "investor_fit")} if n else {}
    if acc_n:
        dims["accuracy"] = round(dim_sums["accuracy"] / acc_n, 2)
    overall = round(sum(dims.values()) / len(dims), 2) if dims else 0.0

    prev = await db.fetchrow("select overall from reports where engagement_id = $1 order by created_at desc limit 1",
                             sess["engagement_id"])
    delta = round(overall - float(prev["overall"]), 2) if prev and prev["overall"] is not None else None

    per_vc = []
    for vid, p in panel.items():
        hs = state["vcs"][vid]["hyps"]
        open_h = [h for h in hs if h["status"] != "resolved" and h["confidence"] >= 0.5]
        resolved = [h for h in hs if h["status"] == "resolved" or h["confidence"] < 0.4]
        verdict = (f"Still doubts {', '.join(h['claim'].lower() for h in open_h[:2])}." if open_h
                   else "Doubts answered with the data.")
        per_vc.append({"vc_id": vid, "name": p.name, "verdict": verdict, "second_meeting": not open_h or overall >= 3.5,
                       "beliefs": [{"hypothesis": h["claim"], "lens": h["lens"], "confidence": h["confidence"],
                                    "status": h["status"]} for h in hs],
                       "resolved": [h["claim"] for h in resolved]})

    ledger = [{"text": c["text"], "metric": c["metric"], "value": float(c["value"]) if c["value"] is not None else None,
               "unit": c["unit"], "status": c["status"], "figure": c["figure"]} for c in claims]

    weak_lenses = sorted({q["lens"] for q in questions if q["lens"] and
                          sum(v for k, v in q["scores"].items() if k != "accuracy" and v is not None) / 4 < 3}, key=str)
    gaps = []
    for lens in weak_lenses:
        for term in LENS_TERMS.get(lens, []):
            g = define_term(term)
            if g and not any(x["term"] == g.get("term") for x in gaps):
                gaps.append({"term": g.get("term"), "text": g.get("text") or g.get("definition", ""), "source_id": g.get("source_id")})

    open_all = sorted([(vc, h) for vc, s in state["vcs"].items() for h in s["hyps"] if h["status"] != "resolved"],
                      key=lambda x: -x[1]["confidence"] * x[1]["severity"])
    action_plan = [{"priority": i + 1, "text": f"Prepare a cited answer on {h['claim'].lower()}: the figure, its window, "
                                               f"the weak spot and the fix.", "drill_lens": h["lens"]}
                   for i, (_, h) in enumerate(open_all[:5])]
    knowledge = [{"vc_id": k["vc_id"], "vc_name": panel[k["vc_id"]].name if k["vc_id"] in panel else k["vc_id"],
                  "question": next((t["text"] for t in turns if t["id"] == k["question_turn_id"]), ""),
                  "answer": next((t["text"] for t in turns if t["id"] == k["turn_id"]), ""),
                  "verdict": k["verdict"], "explanation": k["explanation"], "path": (k["expected"] or {}).get("path"),
                  "citations": k["citations"] or []} for k in kchecks]
    to_reread = sorted({k["path"] for k in knowledge if k["verdict"] in ("missed", "contradicts", "partial") and k["path"]})
    if to_reread:
        action_plan.insert(0, {"priority": 0, "text": "Re-read your notes before the meeting: " + ", ".join(to_reread)
                               + ". You didn't recall what they say.", "drill_lens": "knowledge"})
    if any(c["status"] == "contradicts" for c in claims):
        action_plan.insert(0, {"priority": 0, "text": "Fix the numbers you stated that disagree with your own data (see the ledger).",
                               "drill_lens": "claims"})

    sources, seen = [], set()
    for q in questions:
        f = q.get("correct_figure")
        if f and f.get("id") not in seen:
            seen.add(f["id"])
            sources.append({"n": len(sources) + 1, "kind": f["source"]["kind"], "ref": f["source"].get("ref", ""),
                            "label": f["label"], "formula": f["formula"]})
    for _, h in open_all:
        sid_ = h.get("source_id")
        if sid_ and sid_ not in seen and (s := source_by_id(sid_)):
            seen.add(sid_)
            sources.append({"n": len(sources) + 1, "kind": "url", "url": s.get("url"), "publisher": s.get("publisher"),
                            "label": s.get("title") or s.get("publisher"), "as_of": str(s.get("as_of") or "")})

    rep = {"company": ctx.company,
           "verdict": {"readiness": _readiness(overall), "overall": overall, "dims": dims, "delta": delta,
                       "questions": n},
           "per_vc": per_vc, "questions": questions, "ledger": ledger, "slides": [], "delivery": None,
           "knowledge_gaps": gaps, "knowledge": knowledge, "action_plan": action_plan, "audit_notes": [], "sources": sources,
           "memos": [{"vc_id": r["vc_id"], **r["memo"]} for r in await db.fetch(
               "select vc_id, memo from memos where session_id = $1", sess["id"])]}
    md = to_markdown(rep)
    # Audit the synthesis Vicky wrote. Questions were audited when asked, strong answers when
    # judged, and figure/source lines are the engine's own citations.
    synthesis = " ".join([p["verdict"] for p in per_vc] + [a["text"] for a in action_plan])
    res = audit_text(synthesis, ctx.available())
    rep["audit_notes"] = [{"changed": f.text, "why": f.detail} for f in res.findings]
    rid = await db.fetchval(
        """insert into reports (session_id, engagement_id, report, markdown, overall, dims, delta_vs_previous, audit_notes,
             sources, readiness) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) returning id::text""",
        sess["id"], sess["engagement_id"], rep, md, overall, dims, delta, rep["audit_notes"], sources, _readiness(overall))
    for vc, h in open_all[:5]:
        await db.execute(
            """insert into founder_memory (engagement_id, kind, lens, topic, payload, severity)
               values ($1, 'weakness', $2, $3, $4, $5)""",
            sess["engagement_id"], h["lens"], h["claim"], {"session_id": sid, "vc_id": vc, "confidence": h["confidence"],
                                                       "attack_id": h["attack_id"], "hypothesis_id": h["id"]},
            h["severity"])
    return rid


def to_markdown(r: dict) -> str:
    v = r["verdict"]
    lines = [f"# Practice report: {r['company']}", "",
             f"**Readiness:** {v['readiness'].replace('_', ' ')} · overall {v['overall']} / 5"
             + (f" ({'+' if v['delta'] >= 0 else ''}{v['delta']} vs last session)" if v.get("delta") is not None else ""), ""]
    if v["dims"]:
        lines += ["| Dimension | Score / 5 |", "|---|---|"] + [f"| {k.replace('_', ' ')} | {s} |" for k, s in v["dims"].items()] + [""]
    lines += ["## What each investor thinks", ""]
    for p in r["per_vc"]:
        lines.append(f"- **{p['name']}**: {p['verdict']} Second meeting: {'yes' if p['second_meeting'] else 'not yet'}.")
    lines += ["", "## Questions", ""]
    for i, q in enumerate(r["questions"], 1):
        lines += [f"### {i}. {q['vc_name']}: {q['question']}", "",
                  f"*Why they asked:* {q['why_asked']}", "", f"> {q['answer']}", "",
                  f"- Good: {q['good']}", f"- Missing: {q['missing']}"]
        if q.get("correct_figure"):
            f = q["correct_figure"]
            lines.append(f"- The figure: {f['label']} = {f['display']} ({f['formula']}; source: {f['source'].get('ref', '')})")
        if q.get("strong_answer"):
            lines.append(f"- A strong answer: {q['strong_answer']}")
        lines.append("")
    if r["ledger"]:
        lines += ["## Claim ledger", "", "| You said | Status |", "|---|---|"]
        lines += [f"| {c['text']} | {c['status'].replace('_', ' ')} |" for c in r["ledger"]] + [""]
    if r.get("knowledge"):
        lines += ["## Knowledge checks", ""]
        for k in r["knowledge"]:
            lines += [f"- **{k['vc_name']}**: {k['question']}", f"  - You said: {k['answer']}",
                      f"  - {k['verdict'].replace('_', ' ').capitalize()}: {k['explanation']}"]
        lines.append("")
    if r["knowledge_gaps"]:
        lines += ["## Terms to know", ""] + [f"- **{g['term']}**: {g['text']}" for g in r["knowledge_gaps"]] + [""]
    lines += ["## Action plan", ""] + [f"{a['priority'] + 1 if a['priority'] == 0 else a['priority']}. {a['text']}"
                                       for a in r["action_plan"]] + [""]
    if r["sources"]:
        lines += ["## Sources", ""]
        for s in r["sources"]:
            if s["kind"] == "url":
                lines.append(f"{s['n']}. {s['label']}, {s.get('publisher') or ''} ({s.get('as_of') or 'n.d.'}). {s.get('url') or ''}")
            else:
                lines.append(f"{s['n']}. {s['label']}: {s['formula']}. {s['kind'].upper()} {s['ref']}")
    lines += ["", "*Synthetic practice feedback. Not investment advice.*"]
    return "\n".join(lines)


def lens_label(lens: str | None) -> str:
    return LENS_LABELS.get(lens or "", lens or "")


def describe(lenses: list[str | None] | None, focus: str | None = None) -> str:
    """One phrase for the reports list: the founder's focus if they set one, else the two lenses
    the panel pressed hardest. No figures."""
    if focus and focus.strip():
        f = " ".join(focus.split())
        return f"Focus: {f[:80].rstrip()}{'…' if len(f) > 80 else ''}"
    counts: dict[str, int] = {}
    for lens in lenses or []:
        if lens:
            counts[lens] = counts.get(lens, 0) + 1
    top = [lens_label(k).lower() for k, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:2]]
    if not top:
        return "Open questions from the panel"
    return "Pressed on " + ", ".join(top)
