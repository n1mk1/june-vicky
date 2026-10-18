"""Answer questions about the ingested data (the dashboard's "Ask Vicky").

Deterministic and offline: the question is parsed for the measures it names (metrics, canonical
fields, raw columns, facts), the periods it mentions and what it wants done (value, explain, max,
min, total, average, change, list). Code computes every number; each stated number is a Figure
(derived ones carry their formula and the source rows) and the reply passes the citation audit
before it is returned. With an API key, `answer_llm` lets Claude phrase the answer from the same
fact sheet, and anything it says is held to the same audit; failures fall back to this path.
With notes in the knowledge base, Claude can also read them (`vicky.kb.tools`) and quote them verbatim,
cited by path; offline, a question the data can't answer is looked up in the notes by keyword.
"""

import difflib
import re
from dataclasses import dataclass, field
from statistics import mean
from typing import Any, Literal

from vicky.audit import audit_text
from vicky.model.canonical import FIELDS
from vicky.model.context import TruthContext
from vicky.model.coverage import coverage
from vicky.model.currencies import norm_currency
from vicky.model.figures import CURRENCY_UNITS, Fact, Figure, FigureRef, MissingFigure, Source, fmt_value
from vicky.model.loader import period_sort_key, quarter_of
from vicky.model.metrics import FACT_ALIASES
from vicky.model.sources import define_term
from vicky.model.truth import METRIC_ALIASES

Op = Literal["value", "explain", "define", "max", "min", "sum", "avg", "change", "list", "count"]

# Everyday names for canonical fields (the FIELDS labels are added automatically).
FIELD_SYNONYMS: dict[str, list[str]] = {
    "revenue.total": ["revenue", "total revenue", "sales", "turnover", "top line", "income from sales"],
    "revenue.recurring": ["recurring revenue", "subscription revenue", "subscriptions", "subscription", "saas revenue"],
    "revenue.one_time": ["one time revenue", "services revenue", "onboarding fees", "onboarding revenue",
                         "professional services", "setup fees", "non recurring revenue"],
    "cogs": ["cogs", "cost of revenue", "cost of sales", "cost of goods sold", "hosting costs", "direct costs"],
    "gross_profit": ["gross profit"],
    "opex.r_and_d": ["r and d", "rnd", "research and development", "engineering spend", "engineering costs", "product spend"],
    "opex.s_and_m": ["sales and marketing", "s and m", "marketing spend", "sales spend", "acquisition spend",
                     "sales and marketing spend"],
    "opex.g_and_a": ["g and a", "general and administrative", "admin costs", "overheads", "overhead"],
    "opex.customer_success": ["customer success", "support costs", "customer support", "cs costs", "customer success costs"],
    "opex.total": ["opex", "operating expenses", "total opex", "total expenses", "expenses", "operating costs", "spend",
                   "spending", "costs"],
    "operating_income": ["operating income", "operating loss", "ebit", "operating profit"],
    "net_income": ["net income", "net loss", "net profit", "profit", "loss", "bottom line"],
    "non_dilutive_income": ["sr and ed", "sred", "tax credits", "tax credit", "credits", "grants", "grant income",
                            "non dilutive income", "non dilutive funding", "government funding", "refund"],
    "cash_balance": ["cash", "cash balance", "bank balance", "cash in the bank", "money in the bank"],
    "headcount.total": ["headcount", "employees", "team size", "staff", "people"],
    "customers.count": ["customers", "customer count", "paying customers", "logos", "clients"],
    "customers.new": ["new customers", "new logos", "customers added", "customers won"],
    "customers.churned": ["churned customers", "lost customers", "customers lost"],
    "depreciation": ["depreciation"],
}
PERIOD_KEY = re.compile(r"\d{4}(?:-\d{2}|-Q[1-4])?")
FLOW_FACT_WORDS = ("from_operations", "purchases", "received", "revenue", "mrr_bridge", "spend", "income", "burn")

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_MONTH_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"


# ---------------------------------------------------------------- data model

@dataclass
class Series:
    key: str
    label: str
    unit: str
    agg: Literal["sum", "last"]
    points: dict[str, float]
    kind: Literal["field", "raw", "fact"]
    granularity: str
    source_for: Any = None  # (periods) -> Source

    def periods(self) -> list[str]:
        return sorted(self.points, key=period_sort_key)


@dataclass
class Target:
    """What a phrase in the question refers to: a computed figure, a series, or both."""
    phrase: str
    figure_ids: list[str] = field(default_factory=list)
    series_keys: list[str] = field(default_factory=list)


@dataclass
class Answer:
    reply: str
    figures: list[Figure] = field(default_factory=list)
    allowed: list[float] = field(default_factory=list)
    quotes: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    chart: str | None = None  # a chat request that would chart what was asked about
    topic: str = "answer"


def norm(text: str) -> str:
    t = text.lower().replace("’", "'")
    t = re.sub(r"(\w)\s*&\s*(\w)", r"\1 and \2", t)
    t = t.replace("%", " pct ")
    t = re.sub(r"[-_/]", " ", t)
    t = re.sub(r"[^\w\s.$']", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _human(col: str) -> str:
    return re.sub(r"\s+", " ", col.replace("_", " ").replace(".", " ")).strip()


def _currency(ctx: TruthContext) -> str:
    return norm_currency(ctx.currency)


def build_series(ctx: TruthContext) -> dict[str, Series]:
    m = ctx.model
    cur = _currency(ctx)
    out: dict[str, Series] = {}
    for fid, by_p in m.cells.items():
        f = FIELDS.get(fid)
        if f is None or not by_p:
            continue
        out[fid] = Series(fid, f.label, cur if f.kind == "money" else "count", f.agg,
                          {p: c.value for p, c in by_p.items()}, "field", m.granularity,
                          lambda ps, fid=fid: _model_source(ctx, fid, ps))
    for key, by_p in m.raw.items():
        ds_id, col = m.raw_source.get(key, (None, key.split(":")[-1]))
        out[f"raw:{key}"] = Series(f"raw:{key}", _human(col).capitalize(), cur, "sum", dict(by_p), "raw", m.granularity,
                                   lambda ps, ds_id=ds_id, col=col: Source(kind="csv", ref=f"column {col} · {_span(ps)}",
                                                                           dataset_id=ds_id))
    if "net_income" in m.cells:
        nd = m.cells.get("non_dilutive_income", {})
        pts = {p: -(c.value - (nd[p].value if p in nd else 0.0)) for p, c in m.cells["net_income"].items()}
        out["burn"] = Series("burn", "Burn (net loss excluding credits)", cur, "sum", pts, "field", m.granularity,
                             lambda ps: _model_source(ctx, "net_income", ps))
    facts: dict[str, list[Fact]] = {}
    for f in ctx.facts:
        if f.status == "removed" or f.period is None or f.kind == "forecast" or not PERIOD_KEY.fullmatch(f.period):
            continue  # "L12M"-style windows aren't points on a time axis
        facts.setdefault(f.name, []).append(f)
    for name, fs in facts.items():
        if len({f.period for f in fs}) < 2 or name in out:
            continue
        unit = fs[0].unit if fs[0].unit in (*CURRENCY_UNITS, "pct", "months", "count", "ratio", "x") else "count"
        agg = "sum" if any(w in name for w in FLOW_FACT_WORDS) and unit in CURRENCY_UNITS else "last"
        gran = "quarter" if "-Q" in (fs[0].period or "") else "month" if "-" in (fs[0].period or "") else "year"
        by_ref = {f.period: f.source for f in fs}
        out[f"fact:{name}"] = Series(f"fact:{name}", fs[0].label or _human(name), unit, agg,
                                     {f.period: f.value for f in fs if f.period}, "fact", gran,
                                     lambda ps, by_ref=by_ref: by_ref.get(ps[-1]) or next(iter(by_ref.values())))
    return out


_MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def pl(p: str) -> str:
    """A period label with a four-digit year: 'Mar 2026', 'Q1 2026', '2025'."""
    if "-Q" in p:
        y, q = p.split("-Q")
        return f"Q{q} {y}"
    if re.fullmatch(r"\d{4}-\d{2}", p):
        y, m = p.split("-")
        return f"{_MONTH_NAMES[int(m) - 1]} {y}"
    return p


def rollup(s: Series, to: Literal["quarter", "year"]) -> Series:
    """A monthly (or quarterly) series summed, or taken at period end, by quarter or year."""
    groups: dict[str, list[str]] = {}
    for p in s.periods():
        if "-Q" in p:
            key = p.split("-Q")[0] if to == "year" else p
        elif "-" in p:
            key = quarter_of(p) if to == "quarter" else p.split("-")[0]
        else:
            key = p
        groups.setdefault(key, []).append(p)
    pts = {k: (sum(s.points[p] for p in ps) if s.agg == "sum" else s.points[ps[-1]]) for k, ps in groups.items()}
    return Series(s.key, s.label, s.unit, s.agg, pts, s.kind, to,
                  lambda ps, s=s, groups=groups: s.source_for([q for k in ps for q in groups.get(k, [k])]))


def _span(ps: list[str]) -> str:
    return pl(ps[0]) if len(ps) == 1 else f"{pl(ps[0])} → {pl(ps[-1])}"


def _model_source(ctx: TruthContext, fid: str, periods: list[str]) -> Source:
    ds, ref, kind = ctx.model.source_ref(fid, periods)
    return Source(kind=kind if kind in ("csv", "xlsx") else "derived", ref=ref, dataset_id=ds)


# ---------------------------------------------------------------- vocabulary

def vocabulary(ctx: TruthContext, series: dict[str, Series]) -> dict[str, Target]:
    vocab: dict[str, Target] = {}

    def add(phrase: str, figure: str | None = None, s: str | None = None) -> None:
        p = norm(phrase)
        if len(p) < 2:
            return
        t = vocab.setdefault(p, Target(p))
        if figure and figure not in t.figure_ids:
            t.figure_ids.append(figure)
        if s and s not in t.series_keys:
            t.series_keys.append(s)

    for fid, f in ctx.figures.items():
        add(f.label or fid, figure=fid)
        if not fid.startswith("fact."):
            add(_human(fid), figure=fid)
    for alias, ids in METRIC_ALIASES.items():
        for fid in ids:
            if fid in ctx.figures:
                add(alias, figure=fid)
            elif f"fact.{fid}" in ctx.figures:  # e.g. customer count stated in the data pack
                add(alias, figure=f"fact.{fid}")
            elif fid in series:
                add(alias, s=fid)
    for phrase in ("growing", "how fast", "growth rate", "monthly growth", "growth"):
        for fid in ("cmgr_recent", "cmgr_12m"):
            if fid in ctx.figures:
                add(phrase, figure=fid)
    for name, fid in FACT_ALIASES.items():
        if fid in ctx.figures:
            add(_human(name), figure=fid)
    for key, s in series.items():
        add(s.label, s=key)
        if s.kind == "field":
            for syn in FIELD_SYNONYMS.get(key, []):
                add(syn, s=key)
        else:
            col = _human(key.split(":")[-1])
            add(col, s=key)
            # "cogs hosting" is also just "hosting" / "hosting cost(s)"
            words = col.split()
            if len(words) > 1 and words[0] in ("cogs", "opex", "rev", "revenue", "cost", "costs", "sm", "ga", "rnd", "cs"):
                short = " ".join(words[1:])
                add(short, s=key)
                add(f"{short} cost", s=key)
                add(f"{short} costs", s=key)
    for phrase in list(vocab):
        if phrase.endswith(" costs"):
            vocab.setdefault(phrase[:-1], vocab[phrase])  # "hosting costs" → "hosting cost"
    # The headline field and metric of the same name answer together ("revenue" → series + figure).
    if "revenue" in ctx.figures and norm("revenue") in vocab:
        ids = vocab[norm("revenue")].figure_ids
        ids[:] = ["revenue", *(i for i in ids if i != "revenue")]
    return vocab


def find_targets(t: str, vocab: dict[str, Target]) -> list[Target]:
    """Longest phrases first, never overlapping."""
    taken: list[tuple[int, int]] = []
    hits: list[tuple[int, Target]] = []
    for phrase in sorted(vocab, key=len, reverse=True):
        for m in re.finditer(rf"(?<![\w]){re.escape(phrase)}(?![\w])", t):
            if any(a < m.end() and m.start() < b for a, b in taken):
                continue
            taken.append((m.start(), m.end()))
            hits.append((m.start(), vocab[phrase]))
    return [h for _, h in sorted(hits, key=lambda x: x[0])]


GENERIC = {"spend", "spending", "costs", "cost", "expenses", "people", "profit", "loss", "growth"}


def prune(targets: list[Target]) -> list[Target]:
    """Drop generic words ("spend", "costs") when the question also names something specific."""
    specific = [t for t in targets if t.phrase not in GENERIC]
    return specific or targets


def strip_targets(t: str, targets: list[Target]) -> str:
    for tg in targets:
        t = re.sub(rf"(?<![\w]){re.escape(tg.phrase)}(?![\w])", " ", t)
    return re.sub(r"\s+", " ", t)


# ---------------------------------------------------------------- periods

@dataclass
class When:
    periods: list[str] = field(default_factory=list)   # explicit periods (months, quarters or years), in order
    last: int | None = None                            # last N months
    label: str = ""


def parse_when(t: str, model_periods: list[str]) -> When:
    found: list[str] = []
    t = re.sub(rf"\b{_MONTH_RE}\s+\d{{1,2}}(?:st|nd|rd|th)?\s+(\d{{4}})\b", r"\1 \2", t)  # "march 15 2026" → "march 2026"
    for m in re.finditer(rf"\b{_MONTH_RE}\s*'?(\d{{4}}|\d{{2}})\b", t):
        y = int(m.group(2))
        y = y + 2000 if y < 100 else y
        found.append(f"{y:04d}-{MONTHS[m.group(1)[:3]]:02d}")
    for m in re.finditer(r"\b(\d{4})\s(\d{2})\b", t):  # "2026-03" normalised to "2026 03"
        if 1 <= int(m.group(2)) <= 12 and 1990 < int(m.group(1)) < 2100:
            found.append(f"{m.group(1)}-{m.group(2)}")
    for m in re.finditer(r"\bq([1-4])\s*(?:of\s*)?(?:fy\s*)?'?(\d{4}|\d{2})\b|\b(\d{4})\s*q([1-4])\b", t):
        if m.group(1):
            y = int(m.group(2))
            y = y + 2000 if y < 100 else y
            found.append(f"{y:04d}-Q{m.group(1)}")
        else:
            found.append(f"{m.group(3)}-Q{m.group(4)}")
    taken = " ".join(found)
    for m in re.finditer(r"\b(?:in|for|during|of|fy|year)?\s*(20\d{2}|19\d{2})\b", t):
        if m.group(1) not in taken:
            found.append(m.group(1))
    # Bare month names refer to the latest such month in the data ("in March").
    if not found:
        for m in re.finditer(rf"\b(?:in|for|during|of|at end of|end of)\s+{_MONTH_RE}\b", t):
            mm = MONTHS[m.group(1)[:3]]
            cands = [p for p in model_periods if "-" in p and "Q" not in p and int(p.split("-")[1]) == mm]
            if cands:
                found.append(cands[-1])
    w = When(periods=sorted(dict.fromkeys(found), key=period_sort_key))
    mm = re.search(r"\b(?:last|past|previous|trailing|recent)\s+(\d+)\s+(months?|quarters?|years?)\b", t)
    if mm:
        n = int(mm.group(1)) * {"m": 1, "q": 3, "y": 12}[mm.group(2)[0]]
        w.last, w.label = n, f"the last {mm.group(1)} {mm.group(2)}"
    elif re.search(r"\b(?:last|past|previous|trailing)\s+(?:12 months|year|twelve months)\b|\bltm\b|\bttm\b|\bl12m\b", t):
        w.last, w.label = 12, "the last 12 months"
    elif re.search(r"\b(?:last|previous|latest|most recent)\s+quarter\b", t):
        w.last, w.label = 3, "the last quarter"
    elif re.search(r"\blast month\b|\blatest month\b|\bmost recent month\b|\bthis month\b", t):
        w.last, w.label = 1, "the latest month"
    return w


def periods_in(key: str, s: Series) -> list[str]:
    """Series periods inside a month, quarter or year key."""
    ps = s.periods()
    if key in s.points:
        return [key]
    if "-Q" in key:
        return [p for p in ps if ("-Q" not in p and "-" in p and quarter_of(p) == key) or p == key]
    if "-" not in key:
        return [p for p in ps if p.startswith(key + "-") or p == key]
    if "-Q" in (ps[0] if ps else "") and "-" in key:
        q = quarter_of(key)
        return [q] if q in s.points else []
    return []


def window(s: Series, when: When) -> list[str]:
    ps = s.periods()
    if when.last:
        per = 3 if s.granularity == "quarter" else 12 if s.granularity == "year" else 1
        n = max(1, round(when.last / per))
        return ps[-n:]
    return ps


# ---------------------------------------------------------------- figures for answers

def _fig(fid: str, label: str, value: float, unit: str, formula: str, source: Source, period: str | None,
         inputs: list[FigureRef] | None = None) -> Figure:
    return Figure(id=fid, label=label, value=value, unit=unit, formula=formula, source=source, period=period,
                  inputs=inputs or [], group="answer")


def point_figure(s: Series, p: str) -> Figure:
    return _fig(f"q.{s.key}.{p}", f"{s.label}, {pl(p)}", s.points[p], s.unit,
                f"{s.label} in {pl(p)}", s.source_for([p]), p)


def agg_figure(s: Series, ps: list[str], how: str) -> Figure:
    vals = [s.points[p] for p in ps]
    span = _span(ps)
    if how == "sum":
        v, label, word = sum(vals), f"{s.label}, {span} in total", "sum"
    elif how == "avg":
        v, label, word = mean(vals), f"{s.label}, average per {s.granularity} {span}", "average"
    else:
        v, label, word = vals[-1], f"{s.label} at the end of {pl(ps[-1])}", "period-end value"
    return _fig(f"q.{how}.{s.key}.{ps[0]}.{ps[-1]}", label, v, s.unit,
                f"{word} of {s.label.lower()} over {len(ps)} period{'s' if len(ps) != 1 else ''}, {span}",
                s.source_for(ps), f"{ps[0]}..{ps[-1]}",
                [FigureRef(column=s.key, period=p, value=s.points[p]) for p in ps])


def change_figure(s: Series, a: str, b: str) -> Figure | None:
    va, vb = s.points[a], s.points[b]
    if not va:
        return None
    return _fig(f"q.chg.{s.key}.{a}.{b}", f"Change in {s.label.lower()}, {pl(a)} → {pl(b)}",
                vb / va - 1, "pct", f"{s.label} {pl(b)} ÷ {pl(a)} − 1", s.source_for([a, b]), b,
                [FigureRef(column=s.key, period=a, value=va), FigureRef(column=s.key, period=b, value=vb)])


def aggregate_at(s: Series, key: str) -> tuple[Figure | None, list[str]]:
    ps = periods_in(key, s)
    if not ps:
        return None, []
    if len(ps) == 1:
        return point_figure(s, ps[0]), ps
    return agg_figure(s, ps, "sum" if s.agg == "sum" else "last"), ps


# ---------------------------------------------------------------- intent

def detect_op(rest: str, raw: str) -> Op:
    if re.search(r"\b(how many)\b", raw):
        return "count"
    if re.search(r"\b(what does .* mean|meaning of|define|definition|what is meant by|stand for)\b", raw):
        return "define"
    if re.search(r"\b(how (is|are|do you|did you|was|were|does|did) .*\b(calculat|comput|measur|work|deriv|get)|formula|"
                 r"explain|why|where does .* come from|source of|how .* derived|break down how|walk me through)", raw):
        return "explain"
    if re.search(r"\b(highest|max|maximum|peak|largest|biggest|best|record|most)\b", rest):
        return "max"
    if re.search(r"\b(lowest|min|minimum|smallest|least|worst)\b", rest):
        return "min"
    if re.search(r"\b(average|avg|mean|typical|per month on average)\b", raw):  # raw: the metric may be named "Average monthly burn"
        return "avg"
    if re.search(r"\b(total|sum|cumulative|altogether|combined|in total|overall)\b", rest):
        return "sum"
    if re.search(r"\b(change|changed|grow|grew|growing|growth|increase|increased|decrease|decreased|decline|declined|"
                 r"drop|dropped|rise|rose|fall|fell|falling|rising|trend|compare|compared|vs|versus|between)\b", rest):
        return "change"
    if re.search(r"\b(list|each|every|month by month|by month|monthly|per month|by quarter|quarterly|breakdown|"
                 r"break down|history|over time|all periods|series)\b", rest):
        return "list"
    return "value"


SPECIAL = [
    ("valuation", re.compile(r"\b(valuation|valued|worth|pre money|post money|what should we raise at|price the round|"
                             r"cap should|which cap|should i (accept|take|sign)|should we (accept|take|sign)|"
                             r"should i invest|good investment)\b")),
    ("risks", re.compile(r"\b(weak spots?|weaknesses|risks?|red flags?|what will (investors|they|the panel|vcs) ask|"
                         r"attack list|concerns?|worr(y|ies)|biggest problems?)\b")),
    ("missing", re.compile(r"\b(what(?:'s| is) missing|missing data|what data (?:is|are) missing|can'?t (?:you )?compute|"
                           r"coverage|what can'?t|what else do you need|what should i upload)\b")),
    ("inventory", re.compile(r"\b(what data|which data|what files?|which files?|which columns|what columns|what fields|"
                             r"what did (?:i|we|you) (?:upload|ingest|load)|what'?s in (?:the|my) (?:data|file))\b")),
    ("summary", re.compile(r"\b(summary|summari[sz]e|overview|how are we doing|how am i doing|key metrics|headline numbers|"
                           r"snapshot|health check|tl ?dr|big picture)\b")),
    ("help", re.compile(r"^(help|hi|hello|hey|what can you do|what can i ask)\b")),
]


# ---------------------------------------------------------------- answering

def answer(question: str, ctx: TruthContext) -> dict[str, Any]:
    """Answer a question about the data; returns {kind, reply, citations, suggestions, chart, topic}."""
    a = _answer(question, ctx)
    figures = ctx.available() + a.figures
    res = audit_text(a.reply, figures, a.quotes or None, a.allowed or None)
    if not res.passed:
        # Never show an unchecked number: fall back to the figures we built, stated plainly.
        safe = "Here is what your data says: " + "; ".join(f"{f.label}: {f.display}" for f in a.figures[:6]) + "." \
            if a.figures else "I couldn't answer that reliably from your data."
        a = Answer(reply=safe, figures=a.figures, suggestions=a.suggestions, chart=a.chart, topic=a.topic)
        res = audit_text(a.reply, ctx.available() + a.figures)
        if not res.passed:  # not even the plain figures check out: say so rather than show them uncited
            a = Answer(reply="I couldn't answer that reliably from your data.", suggestions=a.suggestions,
                       chart=a.chart, topic=a.topic)
            res = audit_text(a.reply, [])
    return {"kind": "answer", "reply": a.reply, "citations": [c.model_dump(mode="json") for c in res.citations],
            "suggestions": a.suggestions[:4], "chart": drawable(a.chart, ctx), "topic": a.topic,
            "audit": {"passed": res.passed, "findings": [f.model_dump() for f in res.findings]}}


TREND_WORDS = re.compile(r"\b(fall|falling|fell|drop|dropping|dropped|declin\w*|ris(?:e|ing)|rose|grow\w*|increas\w*|"
                         r"decreas\w*|up|down|slow\w*|accelerat\w*)\b")
_LAST_RAW = [""]


def _answer(question: str, ctx: TruthContext) -> Answer:
    raw = norm(question)
    _LAST_RAW[0] = raw
    if not raw:
        return Answer("Ask me anything about your numbers, e.g. “what was revenue in March?”", topic="help")
    series = build_series(ctx)
    vocab = vocabulary(ctx, series)
    found = find_targets(raw, vocab)
    rest = strip_targets(raw, found)
    targets, seen_keys = [], set()
    for tg in prune(found):
        key = (tuple(tg.figure_ids[:1]), tuple(tg.series_keys[:1]))
        if key not in seen_keys:
            seen_keys.add(key)
            targets.append(tg)

    for topic, rx in SPECIAL:
        if rx.search(raw if topic != "risks" else rest):
            if topic == "summary" and targets:
                continue
            return SPECIAL_HANDLERS[topic](ctx, series)

    if not targets:
        return _not_found(raw, vocab, ctx)
    when = parse_when(rest, ctx.model.periods)
    op = detect_op(rest, raw)
    grain = "quarter" if re.search(r"\b(?:which|each|by|per|every|what)\s+quarter\b|\bquarterly\b", rest) else \
        "year" if re.search(r"\b(?:which|each|by|per|every|what)\s+year\b|\b(?:annual|annually|yearly)\b", rest) else None
    parts = [_answer_target(tg, op, when, ctx, series, grain) for tg in targets[:3]]
    parts = [p for p in parts if p is not None]
    if not parts:
        return _not_found(raw, vocab, ctx)
    out = Answer(" ".join(p.reply for p in parts), [f for p in parts for f in p.figures],
                 [v for p in parts for v in p.allowed], suggestions=[s for p in parts for s in p.suggestions],
                 chart=next((p.chart for p in parts if p.chart), None), topic=parts[0].topic)
    return out


def _answer_target(tg: Target, op: Op, when: When, ctx: TruthContext, series: dict[str, Series],
                   grain: str | None = None) -> Answer | None:
    fig = next((ctx.figures[i] for i in tg.figure_ids if i in ctx.figures), None)
    s = next((series[k] for k in tg.series_keys if k in series), None)
    if s is None and isinstance(fig, Figure):
        # A metric with a matching canonical series (e.g. "cash" ↔ cash_balance) can still do period maths.
        base = fig.id.removeprefix("fact.")
        s = series.get(fig.id) or series.get(FACT_ALIASES.get(base, base)) or series.get(f"fact:{base}")
    if s is not None and grain and s.granularity == "month" or (s is not None and grain == "year" and s.granularity == "quarter"):
        s = rollup(s, grain)  # "which quarter had the highest revenue"
    if op == "define":
        return _define(tg, fig, ctx)
    if op == "explain":
        if isinstance(fig, (Figure, MissingFigure)):
            base = _explain(fig, ctx)
            if s is not None and isinstance(fig, Figure) and TREND_WORDS.search(tg.phrase + " " + _LAST_RAW[0]):
                trend = _series_answer(s, "change", When(last=6, label="the last 6 months"), None)
                return Answer(f"{trend.reply} {base.reply}", trend.figures, base.allowed + trend.allowed,
                              chart=trend.chart or base.chart, topic=base.topic)
            return base
        if s is not None:
            return _explain_series(s, when)
    if (op == "avg" and isinstance(fig, Figure) and "average" in fig.label.lower()
            and not when.periods and not when.last):
        return _value(fig, ctx)  # the metric already is the average, over its own defined window
    if isinstance(fig, MissingFigure) and s is None:
        return Answer(f"{fig.label or fig.id} isn't in your data yet: {fig.reason}", topic="missing",
                      suggestions=["What data is missing?"])
    if s is not None and (op in ("max", "min", "sum", "avg", "change", "list") or when.periods or when.last
                          or not isinstance(fig, Figure)):
        return _series_answer(s, op, when, fig if isinstance(fig, Figure) else None)
    if isinstance(fig, Figure):
        others = [ctx.figures[i] for i in tg.figure_ids[1:3] if isinstance(ctx.figures.get(i), Figure)]
        if others and op in ("value", "count"):  # "growth" → the 12-month and the recent rate
            first = _value(fig, ctx)
            rest = [f"{o.label} is {o.display}." for o in others]
            return Answer(f"{first.reply} {' '.join(rest)}", allowed=first.allowed, chart=first.chart, topic=fig.id)
        return _value(fig, ctx)
    return None


def _value(f: Figure, ctx: TruthContext) -> Answer:
    when = f" ({pl(f.period)})" if f.period and ".." not in f.period and f.period not in ("L12M",) else \
        " over the last 12 months" if f.period == "L12M" else ""
    kind = {"founder_claim": " That figure rests on a founder statement, not a record.",
            "forecast": " That's a forecast, not an actual."}.get(f.kind, "")
    reply = f"{f.label} is {f.display}{when}. It's {_first_lower(f.formula)}.{kind}"
    allowed = [i.value for i in f.inputs if i.value is not None] + _nums(f.formula)  # "(172,512) ÷ (127,308)"
    return Answer(reply, [], allowed, suggestions=[f"How is {f.label.lower()} calculated?"],
                  chart=_chart_request(f.id, ctx), topic=f.id)


def _nums(text: str) -> list[float]:
    """Numbers inside reference text (row numbers, definitions) so the audit doesn't read them as claims."""
    vals = [float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*(?:\.\d+)?", text or "")]
    return vals + [v / 100 for v in vals]


def _first_lower(s: str) -> str:
    return s[:1].lower() + s[1:] if s and not s[:2].isupper() else s


def _explain(f: Figure | MissingFigure, ctx: TruthContext) -> Answer:
    if isinstance(f, MissingFigure):
        return Answer(f"I can't calculate {f.label or f.id} yet: {f.reason}", topic="missing")
    parts = [f"{f.label} is {f.display}, calculated as {_first_lower(f.formula)}."]
    named = [ctx.figures[i.figure_id] for i in f.inputs if i.figure_id and isinstance(ctx.figures.get(i.figure_id), Figure)]
    if named:
        parts.append("It uses " + ", ".join(f"{x.label.lower()} ({x.display})" for x in named) + ".")
    src = f.source
    where = {"csv": "your uploaded spreadsheet", "xlsx": "your uploaded spreadsheet", "pack_summary": "your data pack summary",
             "founder_stated": "a figure you typed in", "pdf": "your PDF", "derived": "other figures"}.get(src.kind, src.kind)
    parts.append(f"Source: {where}{f' ({src.ref})' if src.ref else ''}.")
    g = define_term(f.label) or define_term(f.id.replace("_", " "))
    gloss = str((g or {}).get("text") or (g or {}).get("definition") or "").strip()
    if gloss:
        parts.append(gloss)
    extra = _nums(src.ref) + _nums(gloss) + _nums(f.formula)
    return Answer(" ".join(parts), allowed=extra + [i.value for i in f.inputs if i.value is not None],
                  chart=_chart_request(f.id, ctx), topic=f.id)


def _explain_series(s: Series, when: When) -> Answer:
    ps = window(s, when) if when.last else s.periods()
    origin = {"field": "a column of your uploaded data mapped to this line", "raw": "an unmapped column of your upload",
              "fact": "your data pack"}[s.kind]
    last = point_figure(s, ps[-1])
    return Answer(f"{s.label} comes from {origin}, with {len(ps)} periods from {pl(ps[0])} to {pl(ps[-1])}. "
                  f"The latest value is {last.display} ({pl(ps[-1])}).", [last],
                  chart=f"show {s.label.lower()} by {s.granularity}" if s.kind != "fact" else None, topic=s.key)


def _define(tg: Target, fig: Figure | MissingFigure | None, ctx: TruthContext) -> Answer:
    g = define_term(tg.phrase) or (define_term(fig.label) if fig is not None and fig.label else None)
    text = str((g or {}).get("text") or (g or {}).get("definition") or "").strip()
    reply = f"{(g or {}).get('term', tg.phrase.upper())}: {text}" if text else f"I don't have a definition of “{tg.phrase}”."
    if isinstance(fig, Figure):
        reply += f" Yours is {fig.display}."
    # Numbers inside a glossary definition are part of the definition ("100% means…"), not claims about the company.
    allowed = [float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*(?:\.\d+)?", text)]
    allowed += [v / 100 for v in allowed]
    return Answer(reply, allowed=allowed, topic="define")


def _series_answer(s: Series, op: Op, when: When, fig: Figure | None) -> Answer:
    unit_word = s.label.lower()
    chart = f"show {unit_word} by {s.granularity}" if s.kind != "fact" else None
    # Explicit periods: values at (or totals over) each named period.
    if when.periods and op not in ("max", "min", "avg", "list"):
        figs: list[Figure] = []
        for key in when.periods:
            f, _ = aggregate_at(s, key)
            if f is not None:
                figs.append(f)
        if not figs:
            have = s.periods()
            return Answer(f"Your data has {unit_word} from {pl(have[0])} to {pl(have[-1])}, "
                          f"not for {', '.join(pl(p) for p in when.periods)}.", topic=s.key)
        if len(figs) >= 2 and (op == "change" or len(when.periods) == 2):
            a, b = figs[0], figs[-1]
            ch = (b.value / a.value - 1) if a.value else None
            extra = []
            reply = f"{s.label} was {a.display} in {pl(when.periods[0])} and {b.display} in {pl(when.periods[-1])}"
            if ch is not None:
                c = _fig(f"q.chg.{s.key}.{when.periods[0]}.{when.periods[-1]}", f"Change in {unit_word}", ch, "pct",
                         f"{pl(when.periods[-1])} ÷ {pl(when.periods[0])} − 1", b.source, when.periods[-1])
                extra.append(c)
                reply += f", a change of {('+' if ch >= 0 else '')}{c.display}"
            return Answer(reply + ".", figs + extra, chart=chart, topic=s.key)
        reply = "; ".join(f"{f.label} was {f.display}" for f in figs)
        return Answer(reply + ".", figs, chart=chart, topic=s.key)

    ps = window(s, when)
    if when.periods:  # max/min/avg/list within a named year or quarter
        inside = [p for key in when.periods for p in periods_in(key, s)]
        ps = sorted(dict.fromkeys(inside), key=period_sort_key) or ps
    if not ps:
        return Answer(f"There are no values of {unit_word} in that window.", topic=s.key)
    span = _span(ps)
    if op in ("max", "min"):
        pick = (max if op == "max" else min)(ps, key=lambda p: s.points[p])
        f = point_figure(s, pick)
        word = "highest" if op == "max" else "lowest"
        return Answer(f"The {word} {unit_word} was {f.display} in {pl(pick)} (across {span}).", [f],
                      chart=chart, topic=s.key)
    if op in ("sum", "avg"):
        how = op if not (op == "sum" and s.agg == "last") else "last"
        f = agg_figure(s, ps, how)
        return Answer(_agg_reply(s, f, how, span), [f], [i.value for i in f.inputs if i.value is not None],
                      chart=chart, topic=s.key)
    if op == "change":
        if len(ps) == 1 and not when.periods:  # "revenue vs last month": the latest month against the one before
            ps = s.periods()[-2:]
        a, b = ps[0], ps[-1]
        c = change_figure(s, a, b) if a != b else None
        fa, fb = point_figure(s, a), point_figure(s, b)
        reply = f"{s.label} went from {fa.display} in {pl(a)} to {fb.display} in {pl(b)}"
        figs = [fa, fb]
        if c is not None:
            figs.append(c)
            direction = "up" if c.value >= 0 else "down"
            reply += f", {direction} {_fig('x', '', abs(c.value), 'pct', '', c.source, None).display}"
            figs.append(_fig(f"q.abs.{c.id}", c.label, abs(c.value), "pct", c.formula, c.source, c.period))
        return Answer(reply + ".", figs, chart=chart, topic=s.key)
    if op == "list":
        show = ps[-12:]
        figs = [point_figure(s, p) for p in show]
        more = f" (latest {len(show)} of {len(ps)} periods)" if len(ps) > len(show) else ""
        return Answer(f"{s.label} by period{more}: " + "; ".join(f"{pl(f.period or '')} {f.display}" for f in figs) + ".",
                      figs, chart=chart, topic=s.key)
    # value: latest period in the window, or the figure when no window was asked for
    if fig is not None and not when.last:
        return Answer(f"{fig.label} is {fig.display}. It's {_first_lower(fig.formula)}.", [],
                      [i.value for i in fig.inputs if i.value is not None], chart=chart, topic=fig.id)
    if when.last and when.last > 1 and len(ps) > 1:
        how = "sum" if s.agg == "sum" else "last"
        f = agg_figure(s, ps, how)
        return Answer(_agg_reply(s, f, how, _span(ps)), [f], [i.value for i in f.inputs if i.value is not None],
                      chart=chart, topic=s.key)
    f = point_figure(s, ps[-1])
    return Answer(f"{f.label} was {f.display}.", [f], chart=chart, topic=s.key)


def _agg_reply(s: Series, f: Figure, how: str, span: str) -> str:
    if how == "sum":
        return f"{s.label} came to {f.display} in total over {span}."
    if how == "avg":
        return f"{s.label} averaged {f.display} a {s.granularity} over {span}."
    return f"{s.label} was {f.display} at the end of {pl(f.period.split('..')[-1]) if f.period else span} (it's a balance, so it isn't summed)."


def drawable(chart: str | None, ctx: TruthContext) -> str | None:
    """The "Chart it" request, only if the dashboard's phrase mapper turns it into one chart of one measure
    that the data can draw. Labels such as "Burn (net loss excluding credits)" or "Gross margin, as booked"
    name other measures, so the label is also tried without its parenthesis and qualifier."""
    from vicky.viz import evaluate_widget
    from vicky.viz.phrases import interpret

    if not chart:
        return None
    short = re.sub(r"\s*\([^)]*\)", "", chart).split(",")[0].strip()
    for text in dict.fromkeys((chart, short)):
        it = interpret(text, ctx)
        if it.kind == "widget" and it.spec is not None and len(it.spec.series) == 1 \
                and evaluate_widget(it.spec, ctx).status == "ok":
            return text
    return None


def _chart_request(fid: str, ctx: TruthContext) -> str | None:
    f = ctx.figures.get(fid)
    if not isinstance(f, Figure) or f.group in ("facts", "answer"):
        return None
    return f"show {(f.label or fid).lower()}"


# ---------------------------------------------------------------- special topics

def _valuation(ctx: TruthContext, series: dict[str, Series]) -> Answer:
    return Answer(
        "I won't put a number on the company or tell you which terms to accept: that's negotiated with your lead "
        "investor and depends on demand, round size, your metrics and stage. What I can do is explain the mechanics: "
        "the share of the company you sell is the new money divided by the post-money valuation, and SAFEs convert "
        "at the round, diluting everyone who held shares before it. Run your own cap table through those rules, and "
        "take term-sheet decisions with your lawyer.", topic="valuation")


def _risks(ctx: TruthContext, series: dict[str, Series]) -> Answer:
    items = [a for a in ctx.attack if not a.missing][:5] or ctx.attack[:5]
    if not items:
        return Answer("Nothing in your data stands out as a weak spot; expect questions on your headline numbers.", topic="risks")
    quotes = [q for a in items for q in a.quotes]
    figs = ctx.available()
    # Keep each item's detail only if its numbers check out; otherwise name the topic alone.
    lines = [f"{i + 1}. {a.topic}: {a.detail}" if audit_text(a.detail, figs, a.quotes or None).passed else f"{i + 1}. {a.topic}."
             for i, a in enumerate(items)]
    return Answer("What investors will push on first, strongest first: " + " ".join(lines), quotes=quotes,
                  allowed=[v for a in items for v in _nums(a.topic)],
                  suggestions=["What data is missing?", "Summarise my key metrics"], topic="risks")


def _missing(ctx: TruthContext, series: dict[str, Series]) -> Answer:
    gaps = [c for c in coverage(ctx.figures) if not c["available"] and "not recurring" not in (c.get("reason") or "")]
    if not gaps:
        return Answer("Every metric I track can be computed from your data.", topic="missing")
    lines = [f"{c['label']}: {c.get('reason', '')}" for c in gaps[:6]]
    return Answer(f"{len(gaps)} metric{'s' if len(gaps) != 1 else ''} can't be computed yet. " + " ".join(lines),
                  allowed=[float(len(gaps))], topic="missing")


def _inventory(ctx: TruthContext, series: dict[str, Series]) -> Answer:
    m = ctx.model
    fields = [s.label for s in series.values() if s.kind == "field"]
    raws = [s.label for s in series.values() if s.kind == "raw"]
    facts = len({f.name for f in ctx.facts if f.status != "removed"})
    span = f"{pl(m.periods[0])} to {pl(m.periods[-1])}" if m.periods else "no periods"
    reply = (f"Your data covers {span} by {m.granularity}. Mapped lines: {', '.join(fields)}."
             + (f" Kept as raw columns: {', '.join(raws[:12])}{'…' if len(raws) > 12 else ''}." if raws else "")
             + (f" Plus {facts} facts from your data pack or typed figures." if facts else ""))
    return Answer(reply, allowed=[float(facts), float(len(m.periods))], topic="inventory")


SUMMARY_IDS = ["arr", "revenue", "cmgr_12m", "cmgr_recent", "gross_margin", "burn", "cash_balance", "runway_months", "nrr"]


def _summary(ctx: TruthContext, series: dict[str, Series]) -> Answer:
    figs = [ctx.figures[i] for i in SUMMARY_IDS if isinstance(ctx.figures.get(i), Figure)]
    if not figs:
        return Answer("I don't have enough mapped data for a summary yet.", topic="summary")
    lines = "; ".join(f"{f.label} {f.display}" for f in figs)
    top = next((a for a in ctx.attack if not a.missing), None)
    reply = f"{ctx.company} at a glance: {lines}."
    quotes = []
    if top:
        ok = audit_text(top.detail, ctx.available(), top.quotes or None).passed
        reply += f" The first thing investors will raise: {top.topic.lower()}" + (f" ({top.detail})" if ok else ".")
        quotes = list(top.quotes)
    return Answer(reply, quotes=quotes, suggestions=["What are my weak spots?", "What data is missing?"], topic="summary")


def _help(ctx: TruthContext, series: dict[str, Series]) -> Answer:
    return Answer("Ask me about any number in your data: “what was revenue in March 2026?”, “which month had the "
                  "highest burn?”, “total sales and marketing spend in 2025”, “how is ARR calculated?”, “what are my "
                  "weak spots?”, or ask me to chart something, e.g. “show gross margin by quarter”.", topic="help")


SPECIAL_HANDLERS = {"valuation": _valuation, "risks": _risks, "missing": _missing, "inventory": _inventory,
                    "summary": _summary, "help": _help}


def _not_found(raw: str, vocab: dict[str, Target], ctx: TruthContext) -> Answer:
    words = [w for w in raw.split() if len(w) > 3]
    close: list[str] = []
    for w in words:
        close += difflib.get_close_matches(w, list(vocab), n=2, cutoff=0.75)
    close = list(dict.fromkeys(close))[:3]
    hint = f" Did you mean {', '.join('“' + c + '”' for c in close)}?" if close else ""
    return Answer(f"I couldn't find that in your data.{hint} I can answer questions about the lines and metrics in your "
                  "upload, e.g. revenue, burn, cash, margins, growth or any column by month.",
                  suggestions=[f"What is my {c}?" for c in close] or ["Summarise my key metrics", "What data do you have?"],
                  topic="not_found")


def fmt(value: float, unit: str) -> str:
    return fmt_value(value, unit)


# ---------------------------------------------------------------- the LLM path (optional)

QA_SYSTEM = """You are Vicky, answering a founder's question about their own company data.
Use ONLY the numbers in the <data> block, written exactly as they appear there (same rounding and units).
Never estimate, extrapolate or invent a number, a benchmark or a valuation. If the data can't answer the
question, say so in one sentence and name what would answer it. Never give valuation or investment advice.
Answer in at most four short sentences of plain prose, no lists, no markdown."""


def fact_sheet(ctx: TruthContext) -> tuple[str, list[Figure]]:
    """Every computed figure plus every value of every series, as text the model may quote, and the
    figures that back those values for the audit."""
    lines, extra = [], []
    for f in ctx.figures.values():
        if isinstance(f, Figure):
            lines.append(f"{f.label} = {f.display}" + (f" ({pl(f.period)})" if f.period and ".." not in f.period else "")
                         + f" — {f.formula}")
        else:
            lines.append(f"{f.label or f.id}: not available ({f.reason})")
    for s in build_series(ctx).values():
        pts = [point_figure(s, p) for p in s.periods()[-36:]]
        extra += pts
        lines.append(f"{s.label} by {s.granularity}: " + "; ".join(f"{pl(f.period or '')} {f.display}" for f in pts))
    return "\n".join(lines), extra


QA_KB = """The founder's knowledge base (their own notes: decks, memos, board packs, tables) is open to you
through kb_search and kb_read. Use it for what the data can't answer (plans, context, what a memo says).
Quote a note only word for word inside double quotes, followed by its [kb:path] token. A number from a note
may appear only inside such a quote: never restate, round, convert or compute it. Numbers outside quotes come
only from the <data> block. Return the answer as `reply`."""


async def answer_any(question: str, ctx: TruthContext, dashboard_id: str | None = None) -> dict[str, Any]:
    """The offline answer, or Claude's phrasing of the same data when a key is set and its answer passes the audit.

    Once Fill dashboard has built the knowledge-base index, the notes come from hybrid retrieval and the answer
    goes through the ladder in `vicky.kb.ask` (docs/08-RAG.md §Ask Vicky): every model-written statement cites
    a figure or quotes a note, and the whole-vault catch-all is only offered (`offer`), never run unasked.
    Before the first Fill, Claude gets `kb_search` / `kb_read` as before, and offline a question the data
    can't answer is looked up in the notes by keyword.
    """
    offline = answer(question, ctx)
    from vicky import llm

    if offline["topic"] in ("valuation", "help") or (not llm.enabled() and offline["topic"] != "not_found"):
        return offline
    from vicky.kb import ask
    from vicky.kb.index import active_build_id

    if await active_build_id():
        return await ask.answer(question, ctx, offline, dashboard_id=dashboard_id)
    from vicky.kb.tools import vault_for_agents

    vault = await vault_for_agents()
    if llm.enabled():
        out = await _answer_llm(question, ctx, offline, vault)
        if out is not None:
            return out
    if vault is not None and offline["topic"] == "not_found":
        return await _answer_from_notes(question, ctx, offline, vault) or offline
    return offline


def _with_notes(out: dict[str, Any], res: Any) -> dict[str, Any]:
    cited = [c.source for c in res.citations if c.kind == "note" and c.source]
    if cited:
        out["notes"] = list({c["ref"]: {"id": c.get("note_id"), "path": c["ref"]} for c in cited}.values())
    return out


async def _answer_llm(question: str, ctx: TruthContext, offline: dict[str, Any], vault: Any) -> dict[str, Any] | None:
    from vicky.llm.client import LLMError, get_llm, with_timeout
    from vicky.llm.schemas import QAReply

    sheet, extra = fact_sheet(ctx)
    msg = (f"<data company=\"{ctx.company}\">\n{sheet}\n</data>\n\nQuestion: {question}\n\n"
           f"A deterministic draft answer (correct, but possibly clumsy): {offline['reply']}")
    messages = [{"role": "user", "content": msg}]
    try:
        if vault is None:
            text = await with_timeout(get_llm().text("qa", system=QA_SYSTEM, messages=messages), 25)
        else:
            r = await with_timeout(get_llm().run_tools("qa", QAReply, system=[QA_SYSTEM, QA_KB], messages=messages,
                                                       tools=vault.tools(), max_iterations=4), 25)
            text = r.reply.strip()
    except LLMError:
        return None
    res = audit_text(text, ctx.available() + extra, notes=vault.notes() if vault is not None else None)
    if not res.passed or not text:
        return None
    return _with_notes({**offline, "reply": text, "citations": [c.model_dump(mode="json") for c in res.citations],
                        "audit": {"passed": True, "findings": []}, "llm": True}, res)


async def _answer_from_notes(question: str, ctx: TruthContext, offline: dict[str, Any], vault: Any) -> dict[str, Any] | None:
    """Offline: quote the best-matching lines of the notes, verbatim and cited, when the data has no answer."""
    try:
        found = await vault.search(question, limit=3)
    except Exception:
        return None
    quotes: list[str] = []
    for n in found["notes"]:
        for ex in n["excerpts"]:
            line = f"“{ex}” {n['cite']}"
            if audit_text(line, ctx.available(), notes=vault.notes()).passed:
                quotes.append(line)
                break
        if len(quotes) == 2:
            break
    if not quotes:
        return None
    reply = "Your numbers don't cover that, but your notes do: " + " ".join(quotes)
    res = audit_text(reply, ctx.available(), notes=vault.notes())
    if not res.passed:
        return None
    return _with_notes({**offline, "reply": reply, "citations": [c.model_dump(mode="json") for c in res.citations],
                        "topic": "notes", "audit": {"passed": True, "findings": []}}, res)
