"""Deterministic audit applied to every VC line, Vicky message, coaching card and report.

1. Every number must match a code-computed Figure (±2% or the precision it was stated at), or be
   a quote of what the founder said.
2. Benchmark language needs a `[src:id]` token that resolves in the source library.
3. Valuation numbers and investment advice are blocked outright.
4. A `[kb:path]` token cites a knowledge-base note: it must follow a quote, in double quotes, that
   appears word for word in that note (one the agent's kb tools returned this turn). Numbers inside
   that quote are the note's text, not a claim; anywhere else they still need a Figure.
5. With `require_citations` (model-written chat answers), every statement must carry a citation: a
   computed figure, a note quote with its `[kb:path]` or a `[src:id]`. Only questions are exempt.

The result carries `citations[]` (footnotes) with offsets into the text.
"""

import re
from typing import Literal

from pydantic import BaseModel, Field

from vicky.model.currencies import _PREFIX_RX, _PREFIXES, _SYMBOL_RX, _SYMBOLS, CURRENCY_CODES
from vicky.model.figures import CURRENCY_UNITS, Figure
from vicky.model.sources import source_by_id
from vicky.model.truth import METRIC_ALIASES, _tolerance

FindingKind = Literal["number", "benchmark", "valuation", "advice", "source", "note", "uncited"]


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


# Money markers, lowercase (patterns run on lowered text): a dollar prefix (C$, US$, S$ …), a symbol,
# or an ISO code (CAD, CHF …). `CUR` may be absent; `CUR_REQ` must be there.
_CUR_MARK = (rf"(?:{_PREFIX_RX}|{_SYMBOL_RX}|\$|\b(?:{'|'.join(sorted(CURRENCY_CODES, key=len, reverse=True))})\s?)")
CUR, CUR_REQ = rf"{_CUR_MARK}?", _CUR_MARK
_SCALE = r"(?:k|m|mm|b|bn|thousand|million|billion)"
_UNITS_W = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
            "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
            "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS_W = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_SCALES_W = {"thousand": 1e3, "million": 1e6, "billion": 1e9}
_NUM_W = "|".join([*_UNITS_W, *_TENS_W])

VALUATION_PATTERNS = [
    rf"\b(pre|post)[- ]money(\s+valuation)?\s*(of|at|around|near|should be|would be|=|:)?\s*(about\s*|around\s*|~\s*)?{CUR}\s?\d",
    rf"\bvaluation\s*(of|at|around|near|should be|would be|could be|is|=|:)\s*(about\s*|around\s*|~\s*)?{CUR}\s?\d",
    rf"{CUR_REQ}\s?\d[\d.,]*\s*(k|m|mm|b|million|billion)?\s+(pre-money|post-money|pre money|post money|valuation|cap)\b",
    rf"\b(valuation|valuation cap|cap)\s+of\s+{CUR_REQ}\s?\d",
    rf"\braise\s+at\s+(a\s+)?{CUR}\s?\d",
    rf"\bvalued at\s+(about\s+|around\s+|roughly\s+)?{CUR}\s?\d",
    rf"\bworth\s+(about\s+|around\s+|roughly\s+|over\s+)?({CUR_REQ}\s?\d|\d[\d.,]*\s?{_SCALE}\b)",
    rf"\bvalue\s+(the company|your company|it|you)\s+at\s+{CUR}\s?\d",
    r"\b\d[\d.,]*\s*(k|m|mm|b|million|billion)?\s+(pre|post)[- ]?money\b",
    rf"\b(value|valuing|price|pricing)\s+(it|the company|the round|your company|you)\s+(at|around|near)\s+(about\s+|around\s+)?{CUR}\s?\d",
    rf"\b(price|priced)\s+(the round\s+)?at\s+{CUR}\s?\d[\d.,]*\s*(k|m|mm|b|million|billion)?(\s+(pre|post)\b)?",
    rf"{CUR_REQ}\s?\d[\d.,]*\s*(k|m|mm|b|million|billion)?\s+(pre|post)\b",
    # Written in words, no digit at all: "a ten million dollar valuation", "worth about twelve million".
    r"\b(valuation|valued|pre-money|post-money|pre money|post money)\b[^.!?\n]{0,40}\b(thousand|million|billion)\b",
    r"\b(thousand|million|billion)\b[^.!?\n]{0,20}\b(valuation|pre-money|post-money|pre money|post money)\b",
    rf"\bworth\s+(about\s+|around\s+|roughly\s+|over\s+)?((a|{_NUM_W}|hundred|point|and)[\s-]+){{1,6}}(thousand|million|billion)\b",
]
_DEAL = r"(term ?sheets?|offers?|deals?|round|investment|money|cheque|check|safe|notes?|terms|valuation|cap)\b"
_DEAL_OBJ = rf"\s+((the|this|that|their|our|any|an?|his|her)\s+)?([\w-]+\s+){{0,2}}?{_DEAL}"
_DEAL_VERB = r"(accept|take|sign|reject|decline|turn down|walk away from)"
ADVICE_PATTERNS = [
    r"\b(you|founders?|investors?)\s+should\s+(invest|buy|sell|raise at|price the round)",
    rf"\b(you|founders?|investors?)\s+(should|must|ought to)\s+{_DEAL_VERB}{_DEAL_OBJ}",
    r"\b(you|founders?)\s+(should|must|ought to)\s+walk away\b",
    rf"\bi(?:'d|’d| would)\s+((definitely|probably|just)\s+)?{_DEAL_VERB}{_DEAL_OBJ}",
    r"\bif i were you,?\s+i(?:'d|’d| would)\s+(accept|take|sign|reject|decline|walk|invest|raise|price)",
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
OPEN_QUOTES, CLOSE_QUOTES = "\"“„«", "\"”“»"
NOTE_QUOTE_MAX = 1200
FOUNDER_QUOTE_MIN = 8
_NUM = r"(\d[\d,]*(?:\.\d+)?)"
_CODE_RX = "|".join(sorted(CURRENCY_CODES | {"rmb"}, key=len, reverse=True))
# A marker before the number ("C$1.3M", "£80K", "CHF 4.2M") or a code or currency word after it ("4.2M CAD").
MONEY_RE = re.compile(rf"(?<![\w.])(?:({_PREFIX_RX})|({_SYMBOL_RX}|\$)|({_CODE_RX})\s?)\s?{_NUM}\s*({_SCALE})?\b", re.I)
MONEY_AFTER_RE = re.compile(rf"(?<![\w.$£€]){_NUM}\s*({_SCALE})?\s?(?:({_CODE_RX})|(dollars?|bucks|euros?|pounds))(?![a-z])", re.I)
TRAILING_CODE_RE = re.compile(rf"\s?({_CODE_RX})(?![a-z])", re.I)
CURRENCY_WORDS = {"euro": "eur", "euros": "eur", "pounds": "gbp"}
SCALED_RE = re.compile(rf"(?<![\w.$£€/:])(?<![\w.]-){_NUM}\s?({_SCALE})\b", re.I)  # "4.2M", "85K": money or a count
PCT_RE = re.compile(r"(?<![\w.$£€])(-?\d[\d,]*(?:\.\d+)?)\s?(%|percent\b|per cent\b|pp\b|percentage points?\b)", re.I)
MONTHS_RE = re.compile(r"(?<![\w.$£€])(\d+(?:\.\d+)?)\s?(months?|mo)\b", re.I)
MULT_RE = re.compile(r"(?<![\w.$£€])(\d+(?:\.\d+)?)\s?x\b", re.I)
# A number may end a sentence ("CAC payback is 9."), but "1.5" or "1,500" is never read as "1".
PLAIN_RE = re.compile(r"(?<![\w.$£€/:])(?<![\w.]-)(\d[\d,]*(?:\.\d+)?)(?![\w%]|[.,]\d|\s?(%|x\b|months?|mo\b|k\b|m\b))", re.I)
QUOTE_RE = re.compile(r"[\"“]([^\"”]{2,300})[\"”]")
# Numbers in words: "sixty thousand dollars", "nine point nine million", "twenty-five percent".
_GROUP_W = rf"(?:(?:{'|'.join(_TENS_W)})(?:[\s-]+(?:{'|'.join(list(_UNITS_W)[1:10])}))?|{'|'.join(_UNITS_W)})"
_HGROUP_W = rf"{_GROUP_W}(?:\s+hundred(?:\s+(?:and\s+)?{_GROUP_W})?)?"
WORD_NUM_RE = re.compile(
    rf"\b(?:{_HGROUP_W}(?:\s+point(?:\s+(?:{'|'.join(list(_UNITS_W)[:10])}))+)?|a(?=\s+(?:hundred|thousand|million|billion)\s+(?:dollars?|bucks|euros?|pounds)\b))"
    rf"(?:,?\s+(?:thousand|million|billion|hundred)(?:,?\s+(?:and\s+)?{_HGROUP_W})?)*"
    r"(?:[\s-]+(percent|per cent|dollars?|bucks|euros?|pounds|months?))?\b", re.I)
WINDOW_RE = re.compile(r"\b(over|last|past|previous|trailing|next|within|every|per|first|in the|across|for the)\s+(the\s+)?$")
LAST_VERB_RE = re.compile(r"\b(will|would|could|should|might|may|can|to|only|still|it'll|it’ll)\s+last\s+$")  # "cash will last 40 months"
MONTH_METRICS = {"runway_months", "cac_payback_months"}
# A count noun right after a small number or a year makes it a claim ("2000 customers"), unless it ranks ("top 3 customers").
COUNT_AFTER_RE = re.compile(r"^\s*(customers?|clients?|users?|logos?|accounts?|employees|hires)\b")
RANK_BEFORE_RE = re.compile(r"\b(top|largest|biggest|first|last|next|of the|of your)\s*$")
METRIC_IS_RE = re.compile(rf"\b({'|'.join(re.escape(a) for a in sorted(METRIC_ALIASES, key=len, reverse=True))})"
                          r"\s+(is|was|are|were|of|at|stands at|sits at|=|:)\s*(about\s+|around\s+|roughly\s+|~\s*)?$")

MULTIPLIERS = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mm": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _spans_overlap(a: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
    return any(a[0] < b[1] and b[0] < a[1] for b in spans)


def _names_metric(text: str, start: int, end: int) -> bool:
    """A small number or a year is a claim when it is stated as a metric: "payback is 11", "2000 customers"."""
    before = text[max(0, start - 40):start].lower()
    if COUNT_AFTER_RE.match(text[end:end + 20].lower()) and not RANK_BEFORE_RE.search(before):
        return True
    return bool(METRIC_IS_RE.search(before))


def _ignorable_plain(text: str, start: int, end: int, value: float) -> bool:
    before = text[max(0, start - 12):start].lower()
    after = text[end:end + 12].lower()
    stated = _names_metric(text, start, end)
    if 1900 <= value <= 2100 and float(value).is_integer() and "," not in text[start:end].rstrip(",") and not stated:
        return True
    # Period labels with a two-digit year: "Sep 26", "Mar '25", "Q3 26".
    if value < 100 and float(value).is_integer() and re.search(
            r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s*'?$|\bq[1-4]\s*'?$", before):
        return True
    if re.search(r"(slide|page|p\.|q|question|step|round|#|section|appendix|no\.)\s*$", before):
        return True
    if re.match(r"^(st|nd|rd|th)\b", after):
        return True
    if 0 <= value <= 12 and float(value).is_integer() and not stated:
        return True  # small counts: "3 milestones", "two of the 5 VCs"
    if re.match(r"^\s*(of|out of|/)\s*\d", after) or re.search(r"\d\s*(of|out of|/)\s*$", before):
        return True
    return False


def _word_value(words: str) -> float:
    """ "nine point nine million" → 9_900_000; "fifty-eight thousand" → 58_000."""
    total, cur, dec = 0.0, 0.0, None
    for t in re.findall(r"[a-z]+", words.lower()):
        if t == "and":
            continue
        if t == "a":
            cur = 1.0
        elif t == "point":
            dec = ""
        elif dec is not None and t in _UNITS_W and _UNITS_W[t] < 10:
            dec += str(_UNITS_W[t])
        else:
            if dec:
                cur += float(f"0.{dec}")
            dec = None
            if t in _UNITS_W:
                cur += _UNITS_W[t]
            elif t in _TENS_W:
                cur += _TENS_W[t]
            elif t == "hundred":
                cur = (cur or 1.0) * 100
            elif t in _SCALES_W:
                total, cur = total + (cur or 1.0) * _SCALES_W[t], 0.0
    if dec:
        cur += float(f"0.{dec}")
    return total + cur


def _signed(text: str, start: int, v: float) -> tuple[int, float]:
    """A loss reads "-$850.6K" or "-850,000": the sign belongs to the number unless it joins two words ("pre-$1M")."""
    if start and text[start - 1] in "-−" and (start == 1 or not text[start - 2].isalnum()):
        return start - 1, -v
    return start, v


def extract_numbers(text: str) -> list[dict]:
    found: list[dict] = []
    spans: list[tuple[int, int]] = []

    def add(start: int, end: int, value: float, unit: str, currency: str | None = None) -> None:
        found.append({"start": start, "end": end, "text": text[start:end], "value": value, "unit": unit, "currency": currency})
        spans.append((start, end))

    for m in MONEY_RE.finditer(text):
        if _spans_overlap((m.start(), m.end()), spans):
            continue
        prefix, sym, code = m.group(1), m.group(2), m.group(3)
        if code and code.lower() in ("try", "pen") and not code.isupper():
            continue  # "try 3" is a verb, "TRY 3" is Turkish lira
        cur = (_PREFIXES[prefix.lower()] if prefix else _SYMBOLS.get(sym) if sym and sym != "$" else
               (code.lower() if code and code.lower() != "rmb" else "cny" if code else None))
        end = m.end()
        if sym == "$" and (tail := TRAILING_CODE_RE.match(text, end)) and (tail.group(1).isupper() or tail.group(1).lower() not in ("try", "pen")):
            end, cur = tail.end(), tail.group(1).lower().replace("rmb", "cny")  # "$1.29M USD" is US dollars
        v = _num(m.group(4)) * MULTIPLIERS.get((m.group(5) or "").lower(), 1.0)
        start, v = _signed(text, m.start(), v)
        add(start, end, v, "money", cur)
    for m in MONEY_AFTER_RE.finditer(text):
        if _spans_overlap((m.start(), m.end()), spans):
            continue
        code, word = m.group(3), (m.group(4) or "").lower()
        if code and code.lower() in ("try", "pen") and not code.isupper():
            continue
        cur = ("cny" if code.lower() == "rmb" else code.lower()) if code else CURRENCY_WORDS.get(word)
        v = _num(m.group(1)) * MULTIPLIERS.get((m.group(2) or "").lower(), 1.0)
        start, v = _signed(text, m.start(), v)
        add(start, m.end(), v, "money", cur)
    for m in PCT_RE.finditer(text):
        if _spans_overlap((m.start(), m.end()), spans):
            continue
        add(m.start(), m.end(), _num(m.group(1)) / 100, "pct")
    for m in MONTHS_RE.finditer(text):
        if _spans_overlap((m.start(), m.end()), spans):
            continue
        if _time_window(text, m.start(), m.end()):
            spans.append((m.start(), m.end()))  # a time window ("over 12 months"), not a measured figure
            continue
        add(m.start(), m.end(), _num(m.group(1)), "months")
    for m in MULT_RE.finditer(text):
        if _spans_overlap((m.start(), m.end()), spans):
            continue
        add(m.start(), m.end(), _num(m.group(1)), "x")
    for m in SCALED_RE.finditer(text):
        if _spans_overlap((m.start(), m.end()), spans):
            continue
        start, v = _signed(text, m.start(), _num(m.group(1)) * MULTIPLIERS[m.group(2).lower()])
        add(start, m.end(), v, "plain")
    for m in WORD_NUM_RE.finditer(text):
        if _spans_overlap((m.start(), m.end()), spans) or not m.group(0).strip():
            continue
        unit_word = (m.group(1) or "").lower()
        v = _word_value(m.group(0)[:m.start(1) - m.start()] if m.group(1) else m.group(0))
        if unit_word in ("percent", "per cent"):
            add(m.start(), m.end(), v / 100, "pct")
        elif unit_word.startswith(("dollar", "buck", "euro", "pound")):
            add(m.start(), m.end(), v, "money", CURRENCY_WORDS.get(unit_word))
        elif unit_word.startswith("month"):
            if _time_window(text, m.start(), m.end()):
                spans.append((m.start(), m.end()))
            else:
                add(m.start(), m.end(), v, "months")
        elif not _ignorable_plain(text, m.start(), m.end(), v):
            add(m.start(), m.end(), v, "plain")
    for m in PLAIN_RE.finditer(text):
        if _spans_overlap((m.start(), m.end()), spans):
            continue
        start, v = _signed(text, m.start(), _num(m.group(1)))
        if _ignorable_plain(text, m.start(), m.end(), v):
            continue
        add(start, m.end(), v, "plain")
    found.sort(key=lambda d: d["start"])
    return found


def _time_window(text: str, start: int, end: int) -> bool:
    """ "over 12 months", "the last 6 months": a period, not a figure. "Runway for the next 40 months" is still a claim,
    and "cash will last 40 months" never was a window."""
    before = text[max(0, start - 20):start].lower()
    w = WINDOW_RE.search(before)
    if not w or LAST_VERB_RE.search(before):
        return False
    return not (w.group(1) == "next" and MONTH_METRICS & set(metric_context(text, start, end)))


def _compatible(fig: Figure, unit: str, currency: str | None = None, named: bool = False) -> bool:
    """`currency` is the one the text names ("US$", "CHF"); none means the reporting currency, which every
    money figure is in. A bare number next to the metric's name ("payback is 9") may be that metric in its unit."""
    if unit == "money":
        return fig.unit in CURRENCY_UNITS and (currency is None or fig.unit == currency)
    if unit == "pct":
        return fig.unit == "pct"
    if unit == "months":
        return fig.unit == "months"
    if unit == "x":
        return fig.unit in ("x", "ratio")
    return fig.unit in ("count",) or fig.unit in CURRENCY_UNITS or (named and fig.unit in ("months", "x", "ratio"))


_CLAUSE_END = re.compile(r"[.!?](?=\s|$)|[;:\n]|,\s")


def metric_context(text: str, start: int, end: int) -> list[str]:
    """Figure ids named next to a number ("NRR is 92%" → nrr), nearest metric phrase first."""
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


def match_figure(value: float, unit: str, figures: list[Figure], prefer: list[str] | None = None,
                 currency: str | None = None) -> Figure | None:
    if prefer:
        def is_named(f: Figure) -> bool:
            return f.id in prefer or f.id.removeprefix("fact.") in prefer  # non-metric facts are figures named fact.<id>

        named = [f for f in figures if (is_named(f) or f.group == "answer")  # answer figures are built for this very reply
                 and _compatible(f, unit, currency, named=True)]
        if named:
            # The sentence names a metric: the number must be that metric, not any figure that happens to match.
            return _closest(value, unit, named, currency, named=True)
        if not any(is_named(f) for f in figures):
            return None  # "Churn is 45%" with no churn figure: never borrow another metric's figure
    return _closest(value, unit, figures, currency)


def _closest(value: float, unit: str, figures: list[Figure], currency: str | None, named: bool = False) -> Figure | None:
    best: tuple[float, Figure] | None = None
    for f in figures:
        if not _compatible(f, unit, currency, named):
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


_CLAIM_END = re.compile(r"[.!?][\"”’»)\]]*(?=\s|$)|\[(?:kb|src):[^\[\]\n]{1,400}\]")
# "U.S.", "e.g.", "Inc." end in a period without ending the sentence.
_ABBREV = re.compile(r"(?:\b[A-Za-z]\.){1,3}$|\b(?:e\.g|i\.e|etc|vs|inc|ltd|corp|co|no|mr|mrs|ms|dr|st|approx|fig|jan|feb|"
                     r"mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\.$", re.I)


def _claim_sentences(text: str) -> list[tuple[int, int, str]]:
    """Statements for rule 5. A sentence also ends right after every citation token, so an uncited remark
    can't ride along behind a quote ("“…” [kb:a], and that will double revenue."); a period after an
    abbreviation ("U.S.", "e.g.") doesn't end one."""
    out, start = [], 0
    for m in _CLAIM_END.finditer(text):
        nxt = text[m.end():].lstrip()[:1]
        if m.group(0)[0] == "." and _ABBREV.search(text[start:m.start() + 1]) and (nxt.islower() or nxt.isdigit() or nxt in OPEN_QUOTES):
            continue  # "U.S. stores", "e.g. churn"; but "the U.S. It will…" is two sentences
        out.append((start, m.end(), text[start:m.end()]))
        start = m.end()
    if start < len(text):
        out.append((start, len(text), text[start:]))
    return out


def _norm_quote(s: str) -> str:
    """Case, curly quotes, markdown marks and whitespace don't matter when matching a note quote.
    Passages reach the model with `<` and `>` escaped, so a faithful quote may carry the entities."""
    s = s.replace("&lt;", "<").replace("&gt;", ">")
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
               extra_allowed: list[float] | None = None, notes: dict[str, dict] | None = None,
               require_citations: bool = False) -> AuditResult:
    """`notes` maps note path → {id, title, content} for the notes the agent's kb tools returned.
    `require_citations`: every sentence that isn't a question must overlap a citation (rule 5)."""
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
    quotes_norm = [_norm_quote(q) for q in founder_quotes or []]
    src_spans = [(m.start(), m.end()) for m in SRC_RE.finditer(text)] + note_spans
    allowed = extra_allowed or []
    valuation_spans = [(m.start(), m.end()) for f in findings if f.kind == "valuation"
                       for m in [re.search(re.escape(f.text.lower()), lower)] if m]

    for n in extract_numbers(text):
        span = (n["start"], n["end"])
        if _spans_overlap(span, src_spans) or _spans_overlap(span, valuation_spans):
            continue
        if _spans_overlap(span, quote_spans):
            # Only the founder's own words, 8+ characters of them: a quote that merely contains a short
            # answer ("Yes") is not a quote of it.
            quoted = _norm_quote(next(text[a:b] for a, b in quote_spans if a <= span[0] < b).strip("\"“” "))
            if len(quoted) >= FOUNDER_QUOTE_MIN and any(quoted in q for q in quotes_norm):
                continue
        if any(abs(n["value"] - a) <= max(abs(a) * 0.02, 1e-9) for a in allowed):
            continue
        fig = match_figure(n["value"], n["unit"], figures, metric_context(text, n["start"], n["end"]), n.get("currency"))
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
    if require_citations:
        cited = [(c.start, c.end) for c in citations]
        for s_start, s_end, sentence in _claim_sentences(text):
            st = sentence.strip()
            if not re.search(r"[^\W\d_]", st) or st.rstrip("\"”)'").endswith("?"):
                continue
            if any(a < s_end and s_start < b for a, b in cited):
                continue
            findings.append(Finding(kind="uncited", text=st[:160],
                                    detail="Every statement needs a citation: quote the note word for word with its "
                                           "[kb:path] token, or state a computed figure. Drop what you can't cite."))
    return AuditResult(passed=not findings, findings=findings, citations=citations)


def strip_src_tokens(text: str) -> str:
    return SRC_RE.sub("", text).replace("  ", " ").strip()
