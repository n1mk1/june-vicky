"""Deterministic audit applied to every VC line, Vicky message, coaching card and report.

1. Every number must match a code-computed Figure (±2% or the precision it was stated at), or be
   a quote of what the founder said.
2. Benchmark language needs a `[src:id]` token that resolves in the source library.
3. Valuation numbers and investment advice are blocked outright.
4. A `[kb:path]` token cites a knowledge-base note: it must follow a quote, in double quotes, that
   appears word for word in that note (one the agent's kb tools returned this turn). Numbers inside
   that quote are the note's text, not a claim; anywhere else they still need a Figure.

The result carries `citations[]` (footnotes) with offsets into the text.
"""

import re
from typing import Literal

from pydantic import BaseModel, Field

from vicky.model.figures import CURRENCY_UNITS, Figure
from vicky.model.sources import source_by_id
from vicky.model.truth import _tolerance

FindingKind = Literal["number", "benchmark", "valuation", "advice", "source", "note"]


class Finding(BaseModel):
    kind: FindingKind
    text: str
    detail: str


class Citation(BaseModel):
    marker: int
    start: int
    end: int
    text: str
    figure_id: str | None = None
    source_id: str | None = None
    label: str = ""
    display: str = ""
    formula: str = ""
    source: dict | None = None
    kind: str = ""
    url: str | None = None


class AuditResult(BaseModel):
    passed: bool
    findings: list[Finding] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)

    def feedback(self) -> str:
        return "; ".join(f"{f.kind}: '{f.text}' — {f.detail}" for f in self.findings)


VALUATION_PATTERNS = [
    r"\b(pre|post)[- ]money(\s+valuation)?\s*(of|at|around|near|should be|would be|=|:)?\s*(about\s*|around\s*|~\s*)?[$£€]?\s?\d",
    r"\bvaluation\s+(of|at|around|near|should be|would be|could be|is|=|:)\s*(about\s*|around\s*|~\s*)?[$£€]?\s?\d",
    r"[$£€]\s?\d[\d.,]*\s*(k|m|mm|b|million|billion)?\s+(pre-money|post-money|pre money|post money|valuation|cap)\b",
    r"\b(valuation|valuation cap|cap)\s+of\s+[$£€]\s?\d",
    r"\braise\s+at\s+(a\s+)?[$£€]?\s?\d",
    r"\b(worth|valued at)\s+(about\s+|around\s+|roughly\s+)?[$£€]\s?\d",
    r"\bvalue\s+(the company|your company|it|you)\s+at\s+[$£€]?\s?\d",
    r"\b\d[\d.,]*\s*(k|m|mm|b|million|billion)?\s+(pre|post)[- ]?money\b",
    r"\b(value|valuing|price|pricing)\s+(it|the company|the round|your company|you)\s+(at|around|near)\s+(about\s+|around\s+)?[$£€]?\s?\d",
    r"\b(price|priced)\s+(the round\s+)?at\s+[$£€]?\s?\d[\d.,]*\s*(k|m|mm|b|million|billion)?(\s+(pre|post)\b)?",
    r"[$£€]\s?\d[\d.,]*\s*(k|m|mm|b|million|billion)?\s+(pre|post)\b",
]
ADVICE_PATTERNS = [
    r"\b(you|founders?|investors?)\s+should\s+(invest|buy|sell|accept the|take the|sign the|raise at|price the round)",
    r"\b(is|would be|looks like)\s+an?\s+(good|great|bad|poor|solid|smart)\s+investment\b",
    r"\b(i|we)\s+(recommend|advise)\s+(that\s+you\s+)?(raise|accept|sign|price|invest)",
    r"\bmy advice is to (raise|accept|sign|price|invest)",
    r"\b(buy|sell)\s+(shares|stock|equity)\s+in\b",
]
BENCHMARK_PATTERNS = [
    r"\bbenchmarks?\b", r"\btop[- ]quartile\b", r"\bbottom[- ]quartile\b", r"\bmedian\b", r"\bbest[- ]in[- ]class\b",
    r"\bindustry (average|standard|norm)\b", r"\binvestors (usually|typically|generally) (expect|look for|want)\b",
    r"\brule of 40\b", r"\bthe norm\b", r"\bgood looks like\b", r"\bhealthy (range|level)\b",
    r"\b(typical|typically) (for|at) (seed|series a|saas)\b", r"\bpeers\b",
]

SRC_RE = re.compile(r"\[src:([a-z0-9_\-.]+)\]", re.I)
KB_RE = re.compile(r"\[kb:([^\[\]\n]{1,400})\]")
OPEN_QUOTES, CLOSE_QUOTES = "\"“", "\"”"
NOTE_QUOTE_MAX = 1200
MONEY_RE = re.compile(r"(?<![\w.])(?:(?:CA|C|US|AU|A|NZ)(?=\$))?([$£€])\s?(\d[\d,]*(?:\.\d+)?)\s*(k|m|mm|b|bn|thousand|million|billion)?\b", re.I)
CODE_MONEY_RE = re.compile(r"\b(CAD|USD|GBP|EUR|AUD)\s?(\d[\d,]*(?:\.\d+)?)\s*(k|m|mm|b|bn|thousand|million|billion)?\b", re.I)
PCT_RE = re.compile(r"(?<![\w.$£€])(-?\d[\d,]*(?:\.\d+)?)\s?(%|percent\b|per cent\b|pp\b|percentage points?\b)", re.I)
MONTHS_RE = re.compile(r"(?<![\w.$£€])(\d+(?:\.\d+)?)\s?(months?|mo)\b", re.I)
MULT_RE = re.compile(r"(?<![\w.$£€])(\d+(?:\.\d+)?)\s?x\b", re.I)
PLAIN_RE = re.compile(r"(?<![\w.$£€/:-])(\d[\d,]*(?:\.\d+)?)(?![\w%.]|\s?(%|x\b|months?|mo\b|k\b|m\b))", re.I)
QUOTE_RE = re.compile(r"[\"“]([^\"”]{2,300})[\"”]")

MULTIPLIERS = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mm": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _spans_overlap(a: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
    return any(a[0] < b[1] and b[0] < a[1] for b in spans)


def _ignorable_plain(text: str, start: int, end: int, value: float) -> bool:
    before = text[max(0, start - 12):start].lower()
    after = text[end:end + 12].lower()
    if 1900 <= value <= 2100 and float(value).is_integer() and "," not in text[start:end].rstrip(","):
        return True
    # Period labels with a two-digit year: "Sep 26", "Mar '25", "Q3 26".
    if value < 100 and float(value).is_integer() and re.search(
            r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s*'?$|\bq[1-4]\s*'?$", before):
        return True
    if re.search(r"(slide|page|p\.|q|question|step|round|#|section|appendix|no\.)\s*$", before):
        return True
    if re.match(r"^(st|nd|rd|th)\b", after):
        return True
    if value <= 12 and float(value).is_integer():
        return True  # small counts: "3 milestones", "two of the 5 VCs"
    if re.match(r"^\s*(of|out of|/)\s*\d", after) or re.search(r"\d\s*(of|out of|/)\s*$", before):
        return True
    return False


def extract_numbers(text: str) -> list[dict]:
    found: list[dict] = []
    spans: list[tuple[int, int]] = []
    for m in [*MONEY_RE.finditer(text), *CODE_MONEY_RE.finditer(text)]:
        if _spans_overlap((m.start(), m.end()), spans):
            continue
        v = _num(m.group(2)) * MULTIPLIERS.get((m.group(3) or "").lower(), 1.0)
        found.append({"start": m.start(), "end": m.end(), "text": m.group(0), "value": v, "unit": "money"})
        spans.append((m.start(), m.end()))
    for m in PCT_RE.finditer(text):
        if _spans_overlap((m.start(), m.end()), spans):
            continue
        found.append({"start": m.start(), "end": m.end(), "text": m.group(0), "value": _num(m.group(1)) / 100, "unit": "pct"})
        spans.append((m.start(), m.end()))
    for m in MONTHS_RE.finditer(text):
        if _spans_overlap((m.start(), m.end()), spans):
            continue
        before = text[max(0, m.start() - 20):m.start()].lower()
        if re.search(r"\b(over|last|past|previous|trailing|next|within|every|per|first|in the|across|for the)\s+(the\s+)?$", before):
            spans.append((m.start(), m.end()))  # a time window ("over 12 months"), not a measured figure
            continue
        found.append({"start": m.start(), "end": m.end(), "text": m.group(0), "value": _num(m.group(1)), "unit": "months"})
        spans.append((m.start(), m.end()))
    for m in MULT_RE.finditer(text):
        if _spans_overlap((m.start(), m.end()), spans):
            continue
        found.append({"start": m.start(), "end": m.end(), "text": m.group(0), "value": _num(m.group(1)), "unit": "x"})
        spans.append((m.start(), m.end()))
    for m in PLAIN_RE.finditer(text):
        if _spans_overlap((m.start(), m.end()), spans):
            continue
        v = _num(m.group(1))
        if _ignorable_plain(text, m.start(), m.end(), v):
            continue
        found.append({"start": m.start(), "end": m.end(), "text": m.group(0), "value": v, "unit": "plain"})
        spans.append((m.start(), m.end()))
    found.sort(key=lambda d: d["start"])
    return found


def _compatible(fig: Figure, unit: str) -> bool:
    if unit == "money":
        return fig.unit in CURRENCY_UNITS
    if unit == "pct":
        return fig.unit == "pct"
    if unit == "months":
        return fig.unit == "months"
    if unit == "x":
        return fig.unit in ("x", "ratio")
    return fig.unit in ("count",) or fig.unit in CURRENCY_UNITS


_CLAUSE_END = re.compile(r"[.!?](?=\s|$)|[;:\n]|,\s")


def metric_context(text: str, start: int, end: int) -> list[str]:
    """Figure ids named next to a number ("NRR is 92%" → nrr), nearest metric phrase first."""
    from vicky.model.truth import METRIC_ALIASES

    lo = max(0, start - 60)
    cuts = [m.end() for m in _CLAUSE_END.finditer(text, lo, start)]
    lo = cuts[-1] if cuts else lo
    stop = _CLAUSE_END.search(text, end)
    hi = min(len(text), end + 30, stop.start() if stop else len(text))
    aliases = sorted(METRIC_ALIASES, key=len, reverse=True)

    def scan(window: str) -> list[tuple[int, int, str]]:
        hits: list[tuple[int, int, str]] = []
        for alias in aliases:
            for m in re.finditer(rf"\b{re.escape(alias)}\b", window):
                if not any(a <= m.start() < b for a, b, _ in hits):
                    hits.append((m.start(), m.end(), alias))
        return hits

    left = sorted(scan(text[lo:start].lower()), key=lambda h: -h[1])   # nearest to the number first
    right = sorted(scan(text[end:hi].lower()), key=lambda h: h[0])
    ordered = [a for _, _, a in left] + [a for _, _, a in right]
    ids: list[str] = []
    for alias in ordered:
        for i in METRIC_ALIASES[alias]:
            if i not in ids:
                ids.append(i)
    return ids


def match_figure(value: float, unit: str, figures: list[Figure], prefer: list[str] | None = None) -> Figure | None:
    if prefer:
        named = [f for f in figures if (f.id in prefer or f.group == "answer") and _compatible(f, unit)]  # answer figures are built for this very reply
        if named:
            # The sentence names a metric: the number must be that metric, not any figure that happens to match.
            return match_figure(value, unit, named)
    best: tuple[float, Figure] | None = None
    for f in figures:
        if not _compatible(f, unit):
            continue
        tol = _tolerance(value, f.unit, 0.02)
        diff = abs(value - f.value)
        # a stated percent may also be a whole-number reading of a ratio ("0.6x" vs "0.6")
        if diff <= tol and (best is None or diff < best[0]):
            best = (diff, f)
    return best[1] if best else None


def _sentences(text: str) -> list[tuple[int, int, str]]:
    out, start = [], 0
    for m in re.finditer(r"[.!?](\s|$)", text):
        out.append((start, m.end(), text[start:m.end()]))
        start = m.end()
    if start < len(text):
        out.append((start, len(text), text[start:]))
    return out


def _norm_quote(s: str) -> str:
    """Case, curly quotes, markdown marks and whitespace don't matter when matching a note quote."""
    s = s.lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"[*_`#|>]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _note_quote(text: str, lo: int, token_start: int, content: str) -> tuple[int, int] | None:
    """Span of the quote right before a `[kb:…]` token whose words are in the note, longest first."""
    before = text[:token_start].rstrip()
    if not before or before[-1] not in CLOSE_QUOTES:
        return None
    close = len(before) - 1
    body = _norm_quote(content)
    for i in range(max(lo, close - NOTE_QUOTE_MAX), close):
        if text[i] in OPEN_QUOTES:
            inner = _norm_quote(text[i + 1:close])
            if len(inner) >= 2 and inner in body:
                return i, close + 1
    return None


def _lookup_note(notes: dict[str, dict], path: str) -> dict | None:
    if path in notes:
        return notes[path]
    low = path.lower()
    return next((n for p, n in notes.items() if p.lower() == low or p.lower().rsplit(".", 1)[0] == low), None)


def audit_text(text: str, figures: list[Figure], founder_quotes: list[str] | None = None,
               extra_allowed: list[float] | None = None, notes: dict[str, dict] | None = None) -> AuditResult:
    """`notes` maps note path → {id, title, content} for the notes the agent's kb tools returned."""
    findings: list[Finding] = []
    citations: list[Citation] = []
    lower = text.lower()

    for pat in VALUATION_PATTERNS:
        for m in re.finditer(pat, lower):
            findings.append(Finding(kind="valuation", text=text[m.start():m.end()],
                                    detail="Valuation figures are never given; explain how valuation and SAFE conversion work instead."))
    for pat in ADVICE_PATTERNS:
        for m in re.finditer(pat, lower):
            findings.append(Finding(kind="advice", text=text[m.start():m.end()], detail="No investment advice."))

    for _s_start, _s_end, sentence in _sentences(text):
        if any(re.search(p, sentence.lower()) for p in BENCHMARK_PATTERNS) and not SRC_RE.search(sentence):
            findings.append(Finding(kind="benchmark", text=sentence.strip()[:160],
                                    detail="Benchmark language needs a [src:id] from cite_source, or must be removed."))

    marker = 0
    for m in SRC_RE.finditer(text):
        sid = m.group(1)
        src = source_by_id(sid)
        if not src:
            findings.append(Finding(kind="source", text=m.group(0), detail=f"Unknown source id '{sid}'."))
            continue
        marker += 1
        citations.append(Citation(marker=marker, start=m.start(), end=m.end(), text=m.group(0), source_id=sid,
                                  label=src.get("publisher", ""), display=src.get("title") or src.get("publisher", ""),
                                  formula=src.get("claim", ""), kind="benchmark", url=src.get("url"),
                                  source={"kind": "benchmark", "ref": src.get("title") or "", "url": src.get("url"), "source_id": sid}))

    note_spans: list[tuple[int, int]] = []
    lo = 0
    for m in KB_RE.finditer(text):
        path = m.group(1).strip()
        note_spans.append((m.start(), m.end()))  # numbers in the path are not claims
        note = _lookup_note(notes or {}, path)
        if note is None:
            findings.append(Finding(kind="source", text=m.group(0),
                                    detail=f"Unknown note '{path}'; cite only notes returned by kb_search or kb_read."))
        elif (span := _note_quote(text, lo, m.start(), note.get("content") or "")) is None:
            findings.append(Finding(kind="note", text=text[max(lo, m.start() - 120):m.end()].strip(),
                                    detail=f"A [kb:{path}] cite must follow a word-for-word quote from that note in "
                                           "double quotes; never restate a note's numbers."))
        else:
            note_spans.append(span)
            marker += 1
            npath = note.get("path") or path
            citations.append(Citation(marker=marker, start=span[0], end=m.end(), text=text[span[0]:m.end()],
                                      label=note.get("title") or npath, display=npath, kind="note",
                                      source={"kind": "note", "ref": npath, "note_id": note.get("id")}))
        lo = m.end()

    quote_spans = [(m.start(), m.end()) for m in QUOTE_RE.finditer(text)]
    quotes_lower = [q.lower() for q in founder_quotes or []]
    src_spans = [(m.start(), m.end()) for m in SRC_RE.finditer(text)] + note_spans
    allowed = extra_allowed or []
    valuation_spans = [(m.start(), m.end()) for f in findings if f.kind == "valuation"
                       for m in [re.search(re.escape(f.text.lower()), lower)] if m]

    for n in extract_numbers(text):
        span = (n["start"], n["end"])
        if _spans_overlap(span, src_spans) or _spans_overlap(span, valuation_spans):
            continue
        if _spans_overlap(span, quote_spans):
            quoted = next(text[a:b] for a, b in quote_spans if a <= span[0] < b).lower()
            if quotes_lower and any(quoted.strip("\"“” ") in q or q in quoted for q in quotes_lower):
                continue
        if any(abs(n["value"] - a) <= max(abs(a) * 0.02, 1e-9) for a in allowed):
            continue
        fig = match_figure(n["value"], n["unit"], figures, metric_context(text, n["start"], n["end"]))
        if fig is None:
            findings.append(Finding(kind="number", text=n["text"],
                                    detail="No computed figure matches this number; use get_metric and quote the figure."))
            continue
        marker += 1
        citations.append(Citation(marker=marker, start=n["start"], end=n["end"], text=n["text"], figure_id=fig.id,
                                  label=fig.label, display=fig.display, formula=fig.formula,
                                  source=fig.source.model_dump(mode="json"), kind=fig.kind))
    citations.sort(key=lambda c: c.start)
    for i, c in enumerate(citations, 1):
        c.marker = i
    return AuditResult(passed=not findings, findings=findings, citations=citations)


def strip_src_tokens(text: str) -> str:
    return SRC_RE.sub("", text).replace("  ", " ").strip()
