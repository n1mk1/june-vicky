"""Session report (deterministic path): verdict, per-VC view, every question with its score and
strong answer, the claim ledger, knowledge gaps, an action plan and numbered sources.

Scores come from Vicky and the code accuracy check; knowledge checks are her verdicts on what the founder
recalled of their own notes; the synthesis here adds no figure that
isn't a Figure. Before anything is stored:
- the doubts and the synthesis written here (verdicts, action plan) get the full audit, and a flagged span is
  replaced in both the report and the Markdown (`audit_notes` says what changed and why);
- every line of the Markdown is checked for valuation, advice and uncited benchmark wording, which needs no
  context. Its numbers were audited when they were written, against the figures, the founder's words and the
  notes of that turn (questions when asked, scores when judged); figure and source lines are the engine's own.
"""

import re
from typing import Any

from vicky import db
from vicky.areopagus.schema import LENS_LABELS, VCPersona
from vicky.audit import Finding, audit_text, extract_numbers
from vicky.model.context import TruthContext
from vicky.model.sources import define_term, source_by_id

LENS_TERMS = {
    "retention": ["NRR", "GRR", "logo churn"],
    "forecast": ["CMGR"],
    "unit_economics": ["CAC payback", "burn multiple", "gross margin"],
    "runway": ["runway", "default alive"],
    "concentration": ["concentration"],
    "claims": ["ARR"],
    "terms_cap_table": ["SAFE", "pro rata"],
    "governance": ["SR&ED"],
}


REMOVED = "[removed by the audit]"
WORDING = ("valuation", "advice", "benchmark")


def _readiness(overall: float) -> str:
    return "ready" if overall >= 4.0 else "nearly_ready" if overall >= 3.0 else "not_ready"


async def build(sid: str, ctx: TruthContext, panel: dict[str, VCPersona]) -> str:
    sess = await db.fetchrow("select * from sessions where id::text = $1", sid)
    turns = await db.fetch("select * from turns where session_id = $1 order by seq", sess["id"])
    scores = {
        str(s["turn_id"]): s
        for s in await db.fetch(
            "select * from scores where turn_id = any($1::uuid[])", [t["id"] for t in turns]
        )
    }
    claims = await db.fetch("select * from claims where session_id = $1 order by created_at", sess["id"])
    kchecks = await db.fetch(
        "select * from knowledge_checks where session_id = $1 order by created_at", sess["id"]
    )
    state = sess["state"]
    hyps = {h["id"]: (vc, h) for vc, s in state["vcs"].items() for h in s["hyps"]}
    audit_notes: list[dict] = []
    code_nums = _code_numbers(ctx)
    claims_ok: dict[str, str] = {}

    def claim(h: dict) -> str:
        """The doubt as the report states it: audited once, flagged spans replaced."""
        if h["claim"] not in claims_ok:
            claims_ok[h["claim"]] = _scrub(h["claim"], ctx, code_nums, audit_notes)
        return claims_ok[h["claim"]]

    questions, dim_sums, n = (
        [],
        {"accuracy": 0.0, "evidence": 0.0, "clarity": 0.0, "composure": 0.0, "investor_fit": 0.0},
        0,
    )
    acc_n = 0
    for i, t in enumerate(turns):
        if t["kind"] != "question":
            continue
        ans = next((a for a in turns[i + 1 :] if a["kind"] == "answer"), None)
        nxt_q = next((a for a in turns[i + 1 :] if a["kind"] == "question"), None)
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
        questions.append(
            {
                "turn_id": str(t["id"]),
                "seq": t["seq"],
                "vc_id": t["speaker"],
                "vc_name": panel[t["speaker"]].name if t["speaker"] in panel else t["speaker"],
                "lens": h["lens"] if h else None,
                "question": t["text"],
                "why_asked": sc["rationale"].get("why_asked", ""),
                "answer": ans["text"],
                "scores": {
                    "accuracy": float(sc["accuracy"]) if sc["accuracy"] is not None else None,
                    **sc["dims"],
                },
                "good": sc["rationale"].get("good", ""),
                "missing": sc["rationale"].get("missing", ""),
                "correct_figure": sc["rationale"].get("correct_figure"),
                "strong_answer": sc["rationale"].get("strong_answer", ""),
                "citations": t["citations"] or [],
            }
        )
    dims = (
        {k: round(dim_sums[k] / n, 2) for k in ("evidence", "clarity", "composure", "investor_fit")}
        if n
        else {}
    )
    if acc_n:
        dims["accuracy"] = round(dim_sums["accuracy"] / acc_n, 2)
    overall = round(sum(dims.values()) / len(dims), 2) if dims else 0.0

    prev = await db.fetchrow(
        "select overall from reports where engagement_id = $1 and session_id <> $2 "
        "order by created_at desc limit 1",
        sess["engagement_id"],
        sess["id"],
    )
    delta = round(overall - float(prev["overall"]), 2) if prev and prev["overall"] is not None else None

    per_vc = []
    for vid, p in panel.items():
        hs = state["vcs"][vid]["hyps"]
        open_h = [h for h in hs if h["status"] != "resolved" and h["confidence"] >= 0.5]
        resolved = [h for h in hs if h["status"] == "resolved" or h["confidence"] < 0.4]
        verdict = (
            f"Still doubts {', '.join(claim(h).lower() for h in open_h[:2])}."
            if open_h
            else "Doubts answered with the data."
        )
        per_vc.append(
            {
                "vc_id": vid,
                "name": p.name,
                "verdict": _scrub(verdict, ctx, code_nums, audit_notes),
                "second_meeting": not open_h or overall >= 3.5,
                "beliefs": [
                    {
                        "hypothesis": claim(h),
                        "lens": h["lens"],
                        "confidence": h["confidence"],
                        "status": h["status"],
                    }
                    for h in hs
                ],
                "resolved": [claim(h) for h in resolved],
            }
        )

    ledger = [
        {
            "text": c["text"],
            "metric": c["metric"],
            "value": float(c["value"]) if c["value"] is not None else None,
            "unit": c["unit"],
            "status": c["status"],
            "figure": c["figure"],
        }
        for c in claims
    ]

    weak_lenses = sorted(
        {
            q["lens"]
            for q in questions
            if q["lens"]
            and sum(v for k, v in q["scores"].items() if k != "accuracy" and v is not None) / 4 < 3
        },
        key=str,
    )
    gaps = []
    for lens in weak_lenses:
        for term in LENS_TERMS.get(lens, []):
            g = define_term(term)
            if g and not any(x["term"] == g.get("term") for x in gaps):
                gaps.append(
                    {
                        "term": g.get("term"),
                        "text": g.get("text") or g.get("definition", ""),
                        "source_id": g.get("source_id"),
                    }
                )

    open_all = sorted(
        [(vc, h) for vc, s in state["vcs"].items() for h in s["hyps"] if h["status"] != "resolved"],
        key=lambda x: -x[1]["confidence"] * x[1]["severity"],
    )
    action_plan = [
        {
            "priority": i + 1,
            "text": f"Prepare a cited answer on {claim(h).lower()}: the figure, its window, "
            f"the weak spot and the fix.",
            "drill_lens": h["lens"],
        }
        for i, (_, h) in enumerate(open_all[:5])
    ]
    knowledge = [
        {
            "vc_id": k["vc_id"],
            "vc_name": panel[k["vc_id"]].name if k["vc_id"] in panel else k["vc_id"],
            "question": next((t["text"] for t in turns if t["id"] == k["question_turn_id"]), ""),
            "answer": next((t["text"] for t in turns if t["id"] == k["turn_id"]), ""),
            "verdict": k["verdict"],
            "explanation": k["explanation"],
            "path": (k["expected"] or {}).get("path"),
            "citations": k["citations"] or [],
        }
        for k in kchecks
    ]
    to_reread = sorted(
        {k["path"] for k in knowledge if k["verdict"] in ("missed", "contradicts", "partial") and k["path"]}
    )
    if to_reread:
        action_plan.insert(
            0,
            {
                "priority": 0,
                "text": "Re-read your notes before the meeting: "
                + ", ".join(to_reread)
                + ". You didn't recall what they say.",
                "drill_lens": "knowledge",
            },
        )
    if any(c["status"] == "contradicts" for c in claims):
        action_plan.insert(
            0,
            {
                "priority": 0,
                "text": "Fix the numbers you stated that disagree with your own data (see the ledger).",
                "drill_lens": "claims",
            },
        )
    for a in action_plan:
        a["text"] = _scrub(a["text"], ctx, code_nums, audit_notes)

    sources, seen = [], set()
    for q in questions:
        f = q.get("correct_figure")
        if f and f.get("id") not in seen:
            seen.add(f["id"])
            sources.append(
                {
                    "n": len(sources) + 1,
                    "kind": f["source"]["kind"],
                    "ref": f["source"].get("ref", ""),
                    "label": f["label"],
                    "formula": f["formula"],
                }
            )
    for _, h in open_all:
        sid_ = h.get("source_id")
        if sid_ and sid_ not in seen and (s := source_by_id(sid_)):
            seen.add(sid_)
            sources.append(
                {
                    "n": len(sources) + 1,
                    "kind": "url",
                    "url": s.get("url"),
                    "publisher": s.get("publisher"),
                    "label": s.get("title") or s.get("publisher"),
                    "as_of": str(s.get("as_of") or ""),
                }
            )

    rep = {
        "company": ctx.company,
        "verdict": {
            "readiness": _readiness(overall),
            "overall": overall,
            "dims": dims,
            "delta": delta,
            "questions": n,
        },
        "per_vc": per_vc,
        "questions": questions,
        "ledger": ledger,
        "slides": [],
        "delivery": None,
        "knowledge_gaps": gaps,
        "knowledge": knowledge,
        "action_plan": action_plan,
        "audit_notes": [],
        "sources": sources,
        "memos": [
            {"vc_id": r["vc_id"], **r["memo"]}
            for r in await db.fetch("select vc_id, memo from memos where session_id = $1", sess["id"])
        ],
    }
    for k in ("per_vc", "questions", "knowledge_gaps", "knowledge", "action_plan"):
        rep[k] = _clean_wording(rep[k], ctx, audit_notes)
    md = to_markdown(rep)
    for f in _wording_findings(md, ctx):  # wording only the Markdown's layout put together
        md = md.replace(f.text, REMOVED)
        audit_notes.append({"changed": f.text, "why": f.detail})
    rep["audit_notes"] = audit_notes
    # One report per session: when two ends race, the second insert does nothing and returns the first report.
    rid = await db.fetchval(
        """insert into reports (session_id, engagement_id, report, markdown, overall, dims, delta_vs_previous, audit_notes,
             sources, readiness) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
           on conflict (session_id) do nothing returning id::text""",
        sess["id"],
        sess["engagement_id"],
        rep,
        md,
        overall,
        dims,
        delta,
        rep["audit_notes"],
        sources,
        _readiness(overall),
    )
    if rid is None:
        return await db.fetchval("select id::text from reports where session_id = $1", sess["id"])
    for vc, h in open_all[:5]:
        await db.execute(
            """insert into founder_memory (engagement_id, kind, lens, topic, payload, severity)
               values ($1, 'weakness', $2, $3, $4, $5)""",
            sess["engagement_id"],
            h["lens"],
            h["claim"],
            {
                "session_id": sid,
                "vc_id": vc,
                "confidence": h["confidence"],
                "attack_id": h["attack_id"],
                "hypothesis_id": h["id"],
            },
            h["severity"],
        )
    return rid


def _code_numbers(ctx: TruthContext) -> list[float]:
    """Numbers in the engine's own attack items (thresholds such as "below 100%"): written by code, so a doubt
    built from one may state them."""
    return [n["value"] for a in ctx.attack for t in (a.topic, a.detail) for n in extract_numbers(t or "")]


def _span(text: str, f: Finding) -> str:
    """The text a finding covers: its match, or for benchmark wording the whole sentence (the audit reports
    at most its first 160 characters)."""
    i = text.find(f.text)
    if i < 0 or f.kind != "benchmark" or len(f.text) < 160:
        return f.text
    m = re.search(r"[.!?](\s|$)|\n", text[i + len(f.text) :])
    return text[i : i + len(f.text) + (m.end() if m else len(text))].rstrip()


def _scrub(text: str, ctx: TruthContext, allowed: list[float], notes: list[dict]) -> str:
    """`text` with every span the audit flags replaced; each replacement is noted."""
    res = audit_text(text, ctx.available(), None, allowed)
    for f in res.findings:
        span = _span(text, f)
        if span:
            text = text.replace(span, REMOVED)
        notes.append({"changed": f.text, "why": f.detail})
    return text


# Not Vicky's wording, so not re-checked: the founder's own words (answers) and the engine's figures and
# citations. The founder may well say "valuation"; the rules bind what Vicky and the investors say.
NOT_OURS = {"answer", "correct_figure", "citations", "scores"}


def _clean_wording(v: Any, ctx: TruthContext, notes: list[dict], key: str | None = None) -> Any:
    """Every string in a report section with valuation, advice and uncited benchmark wording replaced."""
    if key in NOT_OURS:
        return v
    if isinstance(v, str):
        for f in audit_text(v, ctx.available()).findings:
            if f.kind in WORDING and (span := _span(v, f)) in v:
                v = v.replace(span, REMOVED)
                notes.append({"changed": f.text, "why": f.detail})
        return v
    if isinstance(v, list):
        return [_clean_wording(x, ctx, notes, key) for x in v]
    if isinstance(v, dict):
        return {k: _clean_wording(x, ctx, notes, k) for k, x in v.items()}
    return v


def _wording_findings(md: str, ctx: TruthContext) -> list[Finding]:
    """Valuation, advice and uncited benchmark wording in the Markdown's own lines (each finding's text is the
    span to remove). Skipped: the founder's words (answers, "You said", the claim ledger) and the Sources list,
    whose lines are the citations themselves (a source's title may well say "benchmarks")."""
    out: list[Finding] = []
    section = ""
    for line in md.splitlines():
        if line.startswith("## "):
            section = line.strip()
        s = line.strip()
        if not s or section in ("## Sources", "## Claim ledger") or s.startswith((">", "- You said:")):
            continue
        out += [
            f.model_copy(update={"text": _span(line, f)})
            for f in audit_text(line, ctx.available()).findings
            if f.kind in WORDING
        ]
    return out


def to_markdown(r: dict) -> str:
    v = r["verdict"]
    lines = [
        f"# Practice report: {r['company']}",
        "",
        f"**Readiness:** {v['readiness'].replace('_', ' ')} · overall {v['overall']} / 5"
        + (
            f" ({'+' if v['delta'] >= 0 else ''}{v['delta']} vs last session)"
            if v.get("delta") is not None
            else ""
        ),
        "",
    ]
    if v["dims"]:
        lines += (
            ["| Dimension | Score / 5 |", "|---|---|"]
            + [f"| {k.replace('_', ' ')} | {s} |" for k, s in v["dims"].items()]
            + [""]
        )
    lines += ["## What each investor thinks", ""]
    for p in r["per_vc"]:
        lines.append(
            f"- **{p['name']}**: {p['verdict']} Second meeting: {'yes' if p['second_meeting'] else 'not yet'}."
        )
    lines += ["", "## Questions", ""]
    for i, q in enumerate(r["questions"], 1):
        lines += [
            f"### {i}. {q['vc_name']}: {q['question']}",
            "",
            f"*Why they asked:* {q['why_asked']}",
            "",
            f"> {q['answer']}",
            "",
            f"- Good: {q['good']}",
            f"- Missing: {q['missing']}",
        ]
        if q.get("correct_figure"):
            f = q["correct_figure"]
            lines.append(
                f"- The figure: {f['label']} = {f['display']} ({f['formula']}; source: {f['source'].get('ref', '')})"
            )
        if q.get("strong_answer"):
            lines.append(f"- A strong answer: {q['strong_answer']}")
        lines.append("")
    if r["ledger"]:
        lines += ["## Claim ledger", "", "| You said | Status |", "|---|---|"]
        lines += [f"| {c['text']} | {c['status'].replace('_', ' ')} |" for c in r["ledger"]] + [""]
    if r.get("knowledge"):
        lines += ["## Knowledge checks", ""]
        for k in r["knowledge"]:
            lines += [
                f"- **{k['vc_name']}**: {k['question']}",
                f"  - You said: {k['answer']}",
                f"  - {k['verdict'].replace('_', ' ').capitalize()}: {k['explanation']}",
            ]
        lines.append("")
    if r["knowledge_gaps"]:
        lines += (
            ["## Terms to know", ""] + [f"- **{g['term']}**: {g['text']}" for g in r["knowledge_gaps"]] + [""]
        )
    lines += (
        ["## Action plan", ""]
        + [
            f"{a['priority'] + 1 if a['priority'] == 0 else a['priority']}. {a['text']}"
            for a in r["action_plan"]
        ]
        + [""]
    )
    if r["sources"]:
        lines += ["## Sources", ""]
        for s in r["sources"]:
            if s["kind"] == "url":
                lines.append(
                    f"{s['n']}. {s['label']}, {s.get('publisher') or ''} ({s.get('as_of') or 'n.d.'}). {s.get('url') or ''}"
                )
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
