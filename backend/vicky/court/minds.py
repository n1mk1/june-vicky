"""Investor minds, deterministic path (LLM_MODE=offline, or no API key).

Same contract as the LLM minds in the TRD: a private memo of weakness hypotheses drawn from
the attack list (gap ownership by lens weight), belief updates with the no-concession rule,
bids, questions in the persona's voice from its question bank, and an independent judge.
Every sentence that carries a number is audited against the engine's Figures before use.
"""

import re
from typing import Any

from vicky.areopagus.registry import canonical
from vicky.areopagus.schema import LENS_LABELS, VCPersona
from vicky.audit import audit_text
from vicky.model.context import TruthContext
from vicky.model.figures import Figure
from vicky.model.truth import AttackItem, _lc
from vicky.playbooks import BankQuestion, bank_ids, country_programs, fill, question_bank

MAX_HYPS = 4
SHARE_SEVERITY = 0.8
LENS_WORDS: dict[str, list[str]] = {
    "forecast": ["growth", "growing", "slow", "forecast", "plan", "rate", "pipeline"],
    "retention": ["churn", "retention", "nrr", "grr", "left", "leave", "renew", "cohort"],
    "unit_economics": ["margin", "cac", "payback", "burn multiple", "magic", "efficien", "support"],
    "concentration": ["largest customer", "top customer", "concentration", "one customer", "renewal"],
    "runway": ["runway", "cash", "burn", "raise", "months of", "default"],
    "claims": ["deck", "arr", "calculate", "say", "number", "headline"],
    "governance": ["board", "credit", "sr&ed", "finance", "books", "grant", "mandate", "audit"],
    "market": ["market", "tam", "size", "bigger", "category"],
    "team": ["team", "hire", "who", "founder", "role", "milestone"],
    "product_tech": ["product", "feature", "copy", "tech", "build", "integration"],
    "terms_cap_table": ["terms", "cap", "safe", "pro rata", "rofr", "valuation", "dilution", "preference"],
    "impact": ["impact", "mandate", "jobs", "outcome"],
}
HEDGES = ["i think", "maybe", "probably", "kind of", "sort of", "hopefully", "i guess", "not sure"]
DEFENSIVE = ["trust me", "obviously", "that's not true", "you don't understand", "with respect", "clearly you"]
OWNING = ["you're right", "fair", "the risk is", "weak spot", "we missed", "honestly, it", "admit", "the gap is", "lower than"]
PLAN = ["we will", "we'll", "plan", "next quarter", "hire", "hiring", "by q", "milestone", "we're fixing", "we are fixing",
        "leading indicator", "pipeline", "renewal"]


def _figs(ctx: TruthContext) -> dict[str, Figure]:
    return {k: v for k, v in ctx.figures.items() if isinstance(v, Figure)}


def passes(text: str, ctx: TruthContext, quotes: list[str] | None = None, allowed: list[float] | None = None) -> bool:
    return audit_text(text, ctx.available(), quotes, allowed).passed


# ---------------------------------------------------------------- memos (gap ownership)

def build_memos(panel: list[VCPersona], ctx: TruthContext, focus: str | None = None) -> dict[str, dict]:
    hyps: dict[str, list[dict]] = {p.id: [] for p in panel}
    items = sorted(ctx.attack, key=lambda a: -a.severity)
    if focus:
        f = focus.lower()
        items.sort(key=lambda a: 0 if any(w in f for w in LENS_WORDS.get(a.lens, [])) or a.lens in f else 1)
    real = [a for a in items if not a.missing or not a.id.startswith("soft_")]
    soft = [a for a in items if a.id.startswith("soft_")]

    def assign(a: AttackItem) -> None:
        # Owners are the best-weighted investors with room left, so a full memo hands the gap on.
        ranked = [p for p in sorted(panel, key=lambda p: (-p.weight(a.lens), len(hyps[p.id])))
                  if len(hyps[p.id]) < MAX_HYPS and p.weight(a.lens) > 0.15]
        owners = ranked[:1]
        if a.severity >= SHARE_SEVERITY and len(ranked) > 1 and ranked[1].weight(a.lens) >= 0.5:
            owners.append(ranked[1])
        for k, p in enumerate(owners):
            h = _hyp(a, p, len(hyps[p.id]) + 1)
            h["shared"] = k > 0  # second owner of a severe gap: never their opener
            hyps[p.id].append(h)

    for a in real:
        assign(a)
    for p in panel:  # everyone gets at least one thread of their own (a shared one is never an opener)
        if not any(not h.get("shared") for h in hyps[p.id]):
            taken = {h["attack_id"] for hs in hyps.values() for h in hs}
            pool = [a for a in soft + real if a.id not in taken] or soft + real
            mine = sorted(pool, key=lambda a: -(p.weight(a.lens) * (0.5 + a.severity)))
            if mine:
                hyps[p.id].append(_hyp(mine[0], p, len(hyps[p.id]) + 1))
    memos = {}
    for p in panel:
        hs = sorted(hyps[p.id], key=lambda h: (h.get("shared", False), -h["severity"] * (0.5 + p.weight(h["lens"]))))
        thesis = (f"{p.name} reads {ctx.company} through {p.lens_line().lower()}. "
                  f"Main doubt: {hs[0]['claim'].lower() if hs else 'none found in the data'}.")
        memos[p.id] = {"thesis": thesis, "hypotheses": hs,
                       "mind_changers": [f"A cited answer on {h['claim'].lower()} with the figure, its window and a plan"
                                         for h in hs[:3]],
                       "opening_question": question_for(p, hs[0], ctx, asked=set()) if hs else "Walk me through the business."}
    return memos


def _hyp(a: AttackItem, p: VCPersona, n: int) -> dict:
    return {"id": f"{p.id}.h{n}", "attack_id": a.id, "claim": a.topic, "detail": a.detail, "lens": a.lens,
            "quotes": list(a.quotes),
            "evidence": list(a.figure_ids), "severity": round(a.severity, 2), "confidence": round(min(0.9, 0.4 + a.severity / 2), 2),
            "source_id": a.source_id, "status": "open", "asked": 0, "weak_answers": 0}


# ---------------------------------------------------------------- speaking

def _bank_match(p: VCPersona, hyp: dict, asked: set[str]) -> list[tuple[int, BankQuestion]]:
    """Unasked bank questions for a hypothesis with a relevance score (≥ 2 means it names the evidence)."""
    words = LENS_WORDS.get(hyp["lens"], [])
    scored = []
    for q in question_bank(canonical(p.id)):  # a session under an old id asks from the new investor's bank
        if f"{p.id}#{q.n}" in asked:
            continue
        t = q.text.lower()
        s = sum(1 for w in words if w in t) + 2 * sum(1 for e in hyp["evidence"] if e in q.placeholders or "{" + e + "}" in q.strong)
        if s:
            scored.append((s, q))
    scored.sort(key=lambda x: -x[0])
    return scored


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d[\d,.]*%?", text))


LENS_PROBES = {
    "forecast": "What does the plan look like if the recent rate is the real one?",
    "retention": "Who left, why, and what have you changed since?",
    "unit_economics": "How do you calculate it, and what moves it in the next two quarters?",
    "concentration": "What happens to the story if that customer leaves at renewal?",
    "runway": "What milestones does the remaining cash buy, and what's the plan if the round takes longer?",
    "claims": "Which months is that, and how exactly is it calculated?",
    "governance": "Who owns the books, and what would a diligence team find?",
    "market": "Build the market for me bottom-up: who buys, how many, at what price?",
    "team": "Who owns which number after the raise, and which hire comes first?",
    "product_tech": "What is the hardest thing you've built that a competitor couldn't copy in a quarter?",
    "terms_cap_table": "Walk me through the cap table after this round, including anything that converts.",
    "impact": "How does this fit the rules a mandate-driven fund has to follow?",
}

TONE_OPENERS = {
    "blunt": "", "calm_precise": "", "warm_conversational": "", "dry_exacting": "",
    "analytical": "", "quiet_probing": "", "genial_hard_nosed": "",
}


def fill_extra(ctx: TruthContext, voice: str = "your") -> dict[str, str]:
    """Bank placeholders that aren't figures: the largest customer (in the speaker's voice) and the country's
    public programmes from the geo playbook (Plato's mandate questions)."""
    out = {"top_customer": f"{voice} largest customer"}
    if programs := country_programs(ctx.profile.get("country")):
        out["country_programs"] = programs
    return out


def question_for(p: VCPersona, hyp: dict, ctx: TruthContext, asked: set[str], company_extra: dict | None = None) -> str:
    """The VC's question on a hypothesis: the evidence line, then a question in their voice.

    A bank question rides on the evidence line only when it is about that evidence; otherwise the
    evidence line gets the lens probe, so the two halves never talk past each other.
    """
    figs = _figs(ctx)
    extra = {**fill_extra(ctx), **(company_extra or {})}
    quotes = hyp.get("quotes") or []
    lead = hyp["detail"] if hyp.get("detail") and passes(hyp["detail"], ctx, quotes) else ""
    for score, q in _bank_match(p, hyp, asked):
        text = fill(q.text, figs, ctx.company, extra)
        if text is None:
            continue
        text = _cap(text)
        if lead and score >= 2 and not (_numbers(lead) & _numbers(text)) and passes(f"{lead} {text}", ctx, quotes):
            asked.add(f"{p.id}#{q.n}")
            return f"{lead} {text}"
        if (not lead or score >= 2) and passes(text, ctx):
            asked.add(f"{p.id}#{q.n}")
            return text
    probe = LENS_PROBES.get(hyp["lens"], "Tell me more.")
    candidate = f"{lead} {probe}" if lead else f"{hyp['claim']}. {probe}"
    return candidate if passes(candidate, ctx, quotes) else f"{hyp['claim']}. {probe}"


def follow_up_for(p: VCPersona, hyp: dict, ctx: TruthContext, checks: list[dict], answer: str, asked: set[str]) -> str:
    """Follow-up on a weak answer: confront a contradiction, ask for the missing number, or press."""
    contra = next((c for c in checks if c["status"] == "contradicts" and c.get("figure")), None)
    if contra:
        f = contra["figure"]
        quote = _sentence_with(answer, contra.get("text") or "")
        said = f'You said "{quote}". ' if quote else ""
        text = f"{said}The data says {_lc(f['label'])} is {f['display']}. Which one is right, and which months are you using?"
        if passes(text, ctx, [answer]):
            return text
    if not checks:
        ev = next((ctx.figure(e) for e in hyp["evidence"] if ctx.figure(e)), None)
        if ev is not None:
            return f"You haven't given me a number. What is {_lc(ev.label)}, how is it calculated, and over which months?"
        return "That's a story, not evidence. What would you show me to prove it?"
    for _, q in _bank_match(p, hyp, asked):
        if "so what" in q.text.lower() or not q.placeholders:
            text = fill(q.text, _figs(ctx), ctx.company, fill_extra(ctx))
            if text and passes(text, ctx):
                asked.add(f"{p.id}#{q.n}")
                return text
    if p.style.tone == "blunt":
        return f"So what? Why does that change whether {ctx.company} is alive in two years?"
    return "Go one level deeper: which rows does that come from, and what was it a quarter earlier?"


def _sentence_with(answer: str, fragment: str) -> str:
    """The founder's whole sentence containing a claim fragment (for quoting them back)."""
    frag = re.sub(r"\s+", " ", fragment.strip().lower())
    for s in re.split(r"(?<=[.?!])\s+", answer.strip()):
        core = re.sub(r"\s+", " ", s.lower())
        if frag and (frag[:24] in core or core in frag):
            return s.strip().rstrip(".")
    return answer.strip().rstrip(".") if len(answer) <= 160 else ""


def coach_card(hyp: dict, ctx: TruthContext) -> str:
    """Coached-mode time-out. Names the gap and points at the figure; adds no number."""
    ev = next((ctx.figure(e) for e in hyp["evidence"] if ctx.figure(e)), None)
    name = re.sub(r"\s*\d+.*$", "", ev.label.split(",")[0]).strip().lower() if ev else ""
    where = f"Open {name} on your dashboard and use that figure" if name else "Use a figure from your data"
    return (f"Time-out. Two answers on “{hyp['claim'].lower()}” haven't landed. {where}: say the number, the window it "
            f"covers and how it's calculated, admit the weak spot, then say what you're doing about it.")


def intro(panel: list[VCPersona], ctx: TruthContext, coaching: str, cap: int, knowledge: bool = False) -> str:
    names = ", ".join(p.name for p in panel[:-1]) + (f" and {panel[-1].name}" if len(panel) > 1 else panel[0].name)
    mode = ("I'll call a time-out if an answer misses twice." if coaching == "coached"
            else "No time-outs: this one runs like the real meeting.")
    notes = (" Some questions test whether you know your own notes; I check those answers against what you wrote."
             if knowledge else "")
    return (f"I'm Vicky, chairing today. {names} have read {ctx.company}'s numbers and written private memos. "
            f"Each of them owns different weak spots, so expect different questions. I review every question before "
            f"it's asked and score every answer. {mode}{notes} "
            f"Answer with your own figures; every number is checked against your data.")


# ---------------------------------------------------------------- judging

def judge(answer: str, hyp: dict | None, checks: list[dict], ctx: TruthContext, question: str) -> dict:
    t = answer.lower()
    words = len(re.findall(r"\w+", answer))
    matches = [c for c in checks if c["status"] == "matches"]
    contras = [c for c in checks if c["status"] in ("contradicts", "forecast_as_fact")]
    accuracy = round(len(matches) / len(checks), 2) if checks else None
    lens_words = LENS_WORDS.get(hyp["lens"], []) if hyp else []

    evidence = 1.0 + (2 if matches else 0) + (1 if any(w in t for w in lens_words) else 0) \
        + (1 if re.search(r"\d", answer) else 0) - 1.5 * len(contras)
    clarity = 1.0 if words < 8 else 2.0 if words > 220 else 4.0 if words <= 120 else 3.0
    clarity += 1 if any(w in t for w in ("because", "which means", " so ", "that's why")) else 0
    clarity -= min(2, sum(1 for h in HEDGES if h in t))
    composure = 4.0 - sum(1 for d in DEFENSIVE if d in t) - (1 if words < 6 else 0) - (1 if "!" in answer else 0) \
        + (1 if any(o in t for o in OWNING) else 0)
    fit = 2.0 + (1 if any(w in t for w in PLAN) else 0) + (1 if any(o in t for o in OWNING) else 0) \
        + (1 if any(w in t for w in ("runway", "round", "cash", "milestone", "series a")) else 0)
    dims = {k: round(max(0.0, min(5.0, v)), 1) for k, v in
            {"evidence": evidence, "clarity": clarity, "composure": composure, "investor_fit": fit}.items()}

    correct = None
    if hyp:
        correct = next((ctx.figure(e) for e in hyp["evidence"] if ctx.figure(e)), None)
    good = []
    if matches:
        good.append("used " + ", ".join(sorted({c['figure']['label'].lower() for c in matches if c.get('figure')})) + " correctly")
    if any(o in t for o in OWNING):
        good.append("owned the weak spot")
    if any(w in t for w in PLAN):
        good.append("said what happens next")
    missing = []
    if contras:
        c = contras[0]
        f = c.get("figure") or {}
        missing.append(f"a number that matches your data: {f.get('label', c['metric']).lower()} is {f.get('display', 'different')}"
                       if f else "a number your data supports")
    elif not checks and correct is not None:
        missing.append(f"the figure itself: {_lc(correct.label)}")
    if not any(o in t for o in OWNING):
        missing.append("the weak spot, said plainly")
    if not any(w in t for w in PLAN):
        missing.append("what you're doing about it")
    return {"accuracy": accuracy, "dims": dims,
            "rationale": {"good": "; ".join(good) or "nothing to keep yet",
                          "missing": "; ".join(missing) or "nothing major",
                          "correct_figure": correct.model_dump(mode="json") if correct else None,
                          "strong_answer": strong_answer(hyp, ctx) if hyp else "",
                          "why_asked": hyp["detail"] if hyp else question}}


def strong_answer(hyp: dict, ctx: TruthContext) -> str:
    figs = _figs(ctx)
    for vc in bank_ids():
        for q in question_bank(vc):
            if not q.strong or not any("{" + e + "}" in q.strong for e in hyp["evidence"]):
                continue
            # Banks mix spoken answers with descriptions of one ("gives the figure and window …");
            # only a first-person, spoken answer can be handed to the founder as a rewrite.
            if not re.match(r"^(\{|\d|we\b|our\b|i\b|it's|they're|nothing\b|over\b|in\b|since\b)", q.strong.strip().lower()):
                continue
            text = fill(q.strong, figs, ctx.company, fill_extra(ctx, "our"))
            if text and passes(text, ctx):
                return text
    f = next((ctx.figure(e) for e in hyp["evidence"] if ctx.figure(e)), None)
    if f is None:
        return ("Give the figure from your data, the window it covers and how it's calculated; admit the weak spot; "
                "say what you're doing about it.")
    allowed = [i.value for i in f.inputs if i.value is not None]
    text = (f"{f.label} is {f.display}, calculated as {f.formula}. That's the weak spot, and here is what we're "
            f"doing about it and the number we'll show next quarter.")
    return text if passes(text, ctx, allowed=allowed) else (
        f"{f.label} is {f.display}. Say how it's calculated, own the weak spot and give the plan.")


def is_weak(score: dict) -> bool:
    d = score["dims"]
    avg = sum(d.values()) / len(d)
    return avg < 2.8 or (score["accuracy"] is not None and score["accuracy"] < 1.0)


# ---------------------------------------------------------------- beliefs and bids

def update_and_bid(p: VCPersona, state: dict, checks: list[dict], weak: bool, current_vc: str | None,
                   current_hyp: str | None, turns_since: int, discussed: set[str] | None = None) -> dict[str, Any]:
    """Belief update with the no-concession rule, then a bid for the next turn."""
    deltas = []
    matched = {c["figure_id"] for c in checks if c["status"] == "matches" and c.get("figure_id")}
    contradicted = {c["figure_id"] for c in checks if c["status"] in ("contradicts", "forecast_as_fact") and c.get("figure_id")}
    for h in state["hyps"]:
        if h["status"] != "open":
            continue
        old = h["confidence"]
        ev = set(h["evidence"])
        new = old
        why = ""
        if ev & contradicted:
            new, why = min(0.98, old + 0.15), "the answer contradicted the data"
        elif ev & matched and h["id"] == current_hyp and not weak:
            new, why = max(0.05, old - 0.3), "cited the matching figure and answered the doubt"
        elif ev & matched:
            new, why = max(0.05, old - 0.1), "cited the matching figure"
        elif h["id"] == current_hyp and weak:
            new, why = min(0.95, old + 0.05), "no figure cited; doubt stands"
        if new != old:
            h["confidence"] = round(new, 2)
            deltas.append({"hyp_id": h["id"], "new_confidence": h["confidence"], "why": why})
        if h["confidence"] < 0.2:
            h["status"] = "resolved"
        elif h["confidence"] > 0.85 and h["asked"] >= 2:
            h["status"] = "confirmed"
    open_h = [h for h in state["hyps"] if h["status"] == "open"]
    current = next((h for h in state["hyps"] if h["id"] == current_hyp), None)
    if p.id == current_vc and current is not None and weak and current["status"] == "open":
        intent, target = "follow_up", current
    elif any(set(h["evidence"]) & contradicted for h in open_h) and p.id != current_vc:
        intent, target = "jump_in", next(h for h in open_h if set(h["evidence"]) & contradicted)
    elif open_h:
        discussed = discussed or set()
        untouched = [h for h in open_h if h["attack_id"] not in discussed
                     and not (h["evidence"] and all(f"fig:{e}" in discussed for e in h["evidence"]))]
        fresh = [h for h in untouched if h["asked"] == 0] or untouched or open_h
        target = max(fresh, key=lambda h: h["confidence"] * h["severity"] * (0.5 + p.weight(h["lens"])))
        intent = "new_topic"
    else:
        return {"deltas": deltas, "bid": 0.0, "intent": "pass", "target_hyp": None, "lane_fit": 0.0}
    bid = target["confidence"] * (0.5 + target["severity"] / 2)
    if intent == "jump_in":
        bid = min(1.0, bid + 0.1 * p.style.interrupt_tendency)
    return {"deltas": deltas, "bid": round(bid, 3), "intent": intent, "target_hyp": target["id"],
            "lane_fit": round(0.4 + 0.6 * p.weight(target["lens"]), 3)}


def lens_label(lens: str) -> str:
    return LENS_LABELS.get(lens, lens)
