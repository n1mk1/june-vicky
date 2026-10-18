"""Knowledge checks, deterministic path: questions that test whether the founder knows what their own
notes say, and Vicky's verdict on the answer.

A probe is written from one retrieved passage of the founder's knowledge base (docs/08-RAG.md). Its
answer key is a verbatim span of that passage, so the verdict can quote it with the passage's
`[kb:path]` token and pass the audit. Vicky schedules probes (`candidate`), an investor asks one in
their voice, and the answer is checked against the key plus a fresh retrieval over the answer.

Verdicts: `knows`, `partial`, `contradicts` (a number that disagrees with the note), `missed`, and
`unverified` (nothing to check against). No figure is produced here; numbers appear only inside
verbatim note quotes.
"""

import re
from typing import Any

from vicky.areopagus.schema import LENS_LABELS, VCPersona
from vicky.court import referee

VERDICTS = ("knows", "partial", "contradicts", "missed", "unverified")
PROBES_PER_VC = 2
KNOW_GAP = 3            # questions between two knowledge checks
QUOTE_MAX = 280
STOP = set("""a an and are as at be been but by can could did do does for from had has have how i if in into is it its
of on or our out so than that the their them then there these they this to was we were what when where which who why
will with would you your about after also any been being just more most much not only other over some such very
""".split())
DONT_KNOW = ("don't know", "do not know", "not sure", "no idea", "can't remember", "cannot remember", "don't remember",
             "need to check", "i'd have to look")


ASK = ("Without looking at your notes: what have you written down about {topic}?",
       "From memory, no slides: what do your own notes say about {topic}?",
       "Quick check before we go on. What have you recorded about {topic}?")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z'&-]{3,}", (s or "").lower()) if w not in STOP}


def _nums(s: str) -> set[str]:
    return {n.replace(",", "") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", s or "")}


def key_quote(text: str) -> str:
    """The answer key: the first full sentence (or two) of a passage with substance, copied verbatim."""
    body = "\n".join(ln for ln in (text or "").splitlines() if ln.strip() and not ln.lstrip().startswith(("#", "|", "---")))
    for s in re.split(r"(?<=[.!?])\s+|\n+", body):
        s = s.strip().lstrip("-*• ").strip()
        if len(s.split()) >= 6 and s.count(",") <= 6:  # a sentence, not a CSV header or a list of fields
            return s[:QUOTE_MAX].rsplit(" ", 1)[0] if len(s) > QUOTE_MAX else s
    return ""


def verbatim_in(quote: str, text: str) -> bool:
    return bool(quote) and _norm(quote).lower() in _norm(text).lower()


def _topic(passage: dict, lens: str) -> str:
    for t in (passage.get("heading"), passage.get("title")):
        t = re.sub(r"[#*_`]", "", str(t or "")).strip()
        if t and not re.search(r"\d", t) and len(t) <= 60:
            return t.lower() if t.isupper() else t
    return LENS_LABELS.get(lens, lens).lower()


def lens_queries(p: VCPersona) -> list[tuple[str, str]]:
    """(lens, query) pairs that find the passages an investor would test the founder on."""
    return [(lens, LENS_LABELS.get(lens, lens)) for lens in p.top_lenses(2)]


def probe_from(passage: dict, vc: str, lens: str, n: int) -> dict | None:
    quote = key_quote(passage.get("text", ""))
    if not quote or not verbatim_in(quote, passage.get("text", "")):
        return None
    topic = _topic(passage, lens)
    return {"id": f"k:{vc}.{n}", "vc": vc, "lens": lens, "topic": topic,
            "question": ASK[(n + len(vc)) % len(ASK)].format(topic=topic),
            "expected": {"chunk_id": passage.get("id"), "note_id": passage.get("note_id"), "cite": passage.get("cite"),
                         "path": passage.get("path"), "title": passage.get("title"), "heading": passage.get("heading"),
                         "quote": quote, "text": (passage.get("text") or "")[:800]},
            "asked": False, "source": "offline"}


def build_probes(passages: dict[str, list[tuple[str, dict]]]) -> list[dict]:
    """Up to PROBES_PER_VC probes per investor from the passages found for their lenses; no two
    investors test the same passage."""
    out, used = [], set()
    for vc, found in passages.items():
        n = 0
        for lens, c in found:
            if n >= PROBES_PER_VC or c.get("id") in used:
                continue
            pr = probe_from(c, vc, lens, n + 1)
            if pr:
                used.add(c.get("id"))
                out.append(pr)
                n += 1
    return out


# ---------------------------------------------------------------- orchestration

def candidate(state: dict, ranked: list[referee.Candidate], *, question_count: int, cap: int,
              weak: bool) -> referee.Candidate | None:
    """Vicky's call on whether a knowledge check is due now, and whose. Code decides; the chair may
    still pick another candidate. Never right after a weak answer (the follow-up comes first)."""
    probes = [p for p in state.get("probes") or [] if not p["asked"] and p["vc"] in state["vcs"]]
    if not probes or weak or question_count < 1:
        return None
    asked = sum(1 for p in state.get("probes") or [] if p["asked"])
    if asked >= max(1, cap // KNOW_GAP):
        return None
    last = state.get("last_knowledge_q")
    left = cap - question_count
    due = (last is None and (question_count >= 2 or left <= 2)) or (last is not None and question_count - last >= KNOW_GAP)
    if not due:
        return None
    pick = min(probes, key=lambda p: (not p.get("drill"), state["vcs"][p["vc"]]["last_spoke"], p["id"]))  # drilled first
    top = max((c.score for c in ranked), default=0.5)
    return referee.Candidate(pick["vc"], "knowledge", pick["id"], round(top + 0.05, 4),
                             ["Vicky: knowledge check due", f"tests {pick['expected'].get('path') or 'a note'}"])


def probe(state: dict, probe_id: str | None) -> dict | None:
    return next((p for p in state.get("probes") or [] if p["id"] == probe_id), None)


# ---------------------------------------------------------------- verification

def verify(answer: str, pr: dict, passages: list[dict]) -> dict[str, Any]:
    """Vicky's verdict on a knowledge answer, by code: overlap with the answer key and the notes found
    for the answer, a number that disagrees with the note, or an admitted blank."""
    exp = pr.get("expected") or {}
    quote = exp.get("quote") or ""
    if not quote:
        return {"verdict": "unverified", "explanation": "There was nothing in your notes to check that answer against.",
                "cite": None, "source": "offline"}
    t = answer.lower()
    same_note = [c for c in passages if c.get("note_id") and c.get("note_id") == exp.get("note_id")]
    key = _words(quote)
    found = _words(answer)
    overlap = len(found & key) / max(1, min(len(key), 8))
    a_nums, q_nums = _nums(answer), _nums(" ".join([quote, *(c.get("text", "") for c in same_note)]))
    if any(d in t for d in DONT_KNOW) and overlap < 0.2:
        verdict = "missed"
    elif a_nums and q_nums and not (a_nums & q_nums):
        verdict = "contradicts"
    elif overlap >= 0.5:
        verdict = "knows"
    elif overlap >= 0.2:
        verdict = "partial"
    else:
        verdict = "missed"
    return {"verdict": verdict, "explanation": explain(verdict, quote, exp.get("cite")), "cite": exp.get("cite"),
            "source": "offline"}


def explain(verdict: str, quote: str, cite: str | None) -> str:
    said = f'Your notes say "{quote}" {cite}' if quote and cite else "Your notes say otherwise"
    return {"knows": f"That matches your notes. {said}.",
            "partial": f"Part of it. {said}.",
            "contradicts": f"That disagrees with your own notes. {said}.",
            "missed": f"You didn't recall it. {said}.",
            "unverified": "There was nothing in your notes to check that answer against."}[verdict]


def adjust_score(score: dict, check: dict) -> dict:
    """Code's scoring of a knowledge answer: evidence follows the verdict; the rationale quotes the note."""
    v = check["verdict"]
    ev = {"knows": 4.5, "partial": 3.0, "contradicts": 1.0, "missed": 1.0}.get(v)
    if ev is not None:
        score["dims"]["evidence"] = ev
    r = score["rationale"]
    if v == "knows":
        r["good"] = "knew what your own notes say"
    elif v in ("partial", "contradicts", "missed"):
        r["missing"] = check["explanation"]
    quote = ((check.get("expected") or {}).get("quote")) or ""
    if quote and v != "knows":
        r["strong_answer"] = f'"{quote}"'  # the note, word for word
    r["why_asked"] = "A knowledge check: investors test whether you know your own material without looking."
    return score


def label(verdict: str) -> str:
    return {"knows": "Knew it", "partial": "Partly", "contradicts": "Contradicts notes", "missed": "Missed",
            "unverified": "Not checked"}.get(verdict, verdict)
