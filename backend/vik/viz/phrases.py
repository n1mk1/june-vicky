"""Offline phrase → dashboard intent: turns a short request into a WidgetSpec or a time range.

This is plain pattern matching over a fixed vocabulary, so it runs without an LLM and is fully
testable. It only ever produces *structure* (metric refs, grouping, window, template, title);
the numbers are still computed by `evaluate.py` when the spec is previewed or added.

    "burn excluding credits as % of revenue by quarter"
        → bar of pct_of(burn_ex_non_dilutive, revenue), grouped by quarter
    "zoom to the last 6 months"   → time range {last_months: 6}
    "reset zoom"                  → time range cleared
    "why is burn falling?"        → a question for the panel, not a widget
"""

import math
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from vik.model.canonical import OPEX_CATEGORIES
from vik.model.context import TruthContext
from vik.viz.defaults import OPEX_NAMES
from vik.viz.spec import MAX_SERIES, Presentation, SeriesSpec, WidgetSpec, Window

Kind = Literal["widget", "time_range", "question", "none"]
Unit = Literal["money", "pct", "count", "months", "other"]

_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "eighteen": 18,
    "twenty four": 24,
    "thirty six": 36,
}
_UNIT_MONTHS = {"month": 1, "quarter": 3, "year": 12}
_GRAN_MONTHS = {"month": 1, "quarter": 3, "year": 12}
_PERIOD_WORDS = r"(?:months?|quarters?|years?|periods?)\b"
_CREDITS = (
    r"(?:the )?(?:non dilutive(?: income)?|(?:tax |r and d |rd )?credits?|grants?|sr and ed|sred|subsid\w*)"
)


class Intent(BaseModel):
    kind: Kind
    spec: WidgetSpec | None = None
    last_months: int | None = None  # time_range: None (and no span) clears it
    span: dict[str, str] | None = None  # time_range: {from, to} months, for "zoom to Q1 2026"
    summary: str = ""


@dataclass(frozen=True)
class Measure:
    ref: str
    label: str
    unit: Unit
    scalar: bool = False  # a single figure (kpi), not a per-period series


@dataclass
class _Hit:
    start: int
    end: int
    measure: Measure


# ---------------------------------------------------------------- normalisation


def normalise(text: str) -> str:
    t = text.lower().replace("’", "'")
    t = re.sub(r"(\w)\s*&\s*(\w)", r"\1 and \2", t)  # r&d → r and d, s&m → s and m
    t = t.replace("%", " pct ").replace("percentage", "pct").replace("percent", "pct")
    t = re.sub(r"[-_/]", " ", t)
    t = re.sub(r"[^\w\s.?']", " ", t)
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", t)  # "incl." / "ex." / a closing full stop; keeps "1.5"
    t = re.sub(r"\s+", " ", t).strip()
    # Number words only where they count periods ("last six months", "three month rolling"):
    # "one-time revenue" must stay a measure, not become "1 time revenue".
    for word, n in sorted(_NUMBERS.items(), key=lambda kv: -len(kv[0])):
        t = re.sub(rf"\b{word}\b(?= {_PERIOD_WORDS})", str(n), t)
    return t


# ---------------------------------------------------------------- vocabulary


def _vocabulary(ctx: TruthContext) -> list[tuple[str, Measure]]:
    """(regex, measure) in priority order: longer, more specific phrases first."""
    credits = ctx.model.has("non_dilutive_income")
    burn = Measure(
        "burn_ex_non_dilutive" if credits else "burn", "Burn ex-credits" if credits else "Burn", "money"
    )
    return [
        # scalar metrics (figures)
        (
            r"\bburn multiple (?:ex|excluding|excl|without) " + _CREDITS,
            Measure("burn_multiple_ex_credits", "Burn multiple ex-credits", "other", True),
        ),
        (r"\bburn multiple\b", Measure("burn_multiple", "Burn multiple", "other", True)),
        (
            r"\bcac payback\b|\bpayback(?: period)?\b",
            Measure("cac_payback_months", "CAC payback", "months", True),
        ),
        (r"\bcac\b|customer acquisition cost", Measure("cac", "CAC", "money", True)),
        (
            r"\bnrr\b|\bndr\b|net (?:revenue|dollar) retention",
            Measure("nrr", "Net revenue retention", "pct", True),
        ),
        (
            r"\bgrr\b|gross (?:revenue|dollar) retention",
            Measure("grr", "Gross revenue retention", "pct", True),
        ),
        (r"\bmagic number\b", Measure("magic_number", "Magic number", "other", True)),
        (r"\brevenue churn\b|\bmrr churn\b", Measure("revenue_churn_rate", "Revenue churn", "pct", True)),
        (r"\b(?:logo |customer )?churn(?: rate)?\b", Measure("logo_churn_rate", "Logo churn", "pct", True)),
        (
            r"\b(?:top|largest|biggest) customer(?: share)?\b|\bcustomer concentration\b|\bconcentration\b",
            Measure("top_customer_share", "Top customer share", "pct", True),
        ),
        (r"\brunway\b", Measure("runway_months", "Runway", "months", True)),
        (
            r"\bcmgr\b|\bcompound(?:ed)? monthly growth\b",
            Measure("cmgr_12m", "Growth, 12 months", "pct", True),
        ),
        # cohort table
        (
            r"\bcohorts?(?: retention)?\b|\bretention by cohort\b",
            Measure("cohort_retention", "Revenue retention by cohort", "pct"),
        ),
        # burn
        (
            r"\b(?:cash |net )?burn(?: rate)? (?:ex|excluding|excl|without|net of|less|minus|before) "
            + _CREDITS,
            Measure("burn_ex_non_dilutive", "Burn ex-credits", "money"),
        ),
        (
            r"\b(?:cash |net )?burn(?: rate)? (?:including|incl|with|after) " + _CREDITS,
            Measure("burn", "Burn incl. credits", "money"),
        ),
        (r"\b(?:cash |net )?burn(?: rate)?\b", burn),
        # revenue family
        (
            r"\bnet new (?:arr|annual(?:ised|ized)? recurring revenue)\b",
            Measure("net_new_arr_l12m", "Net new ARR, last 12 months", "money", True),
        ),
        (r"\barr\b|annual(?:ised|ized)? recurring revenue", Measure("arr", "ARR", "money")),
        (r"\bmrr\b|monthly recurring revenue", Measure("mrr", "MRR", "money")),
        (
            r"\b(?:one time|non recurring|services?|onboarding) revenue\b",
            Measure("revenue.one_time", "One-time revenue", "money"),
        ),
        (
            r"(?<!non )\b(?:recurring|subscription) revenue\b",
            Measure("revenue.recurring", "Recurring revenue", "money"),
        ),
        # margins and costs
        (
            r"\bgross margin (?:incl|including|with|after|net of) (?:customer success|cs|support)\b",
            Measure("gross_margin_incl_cs", "Gross margin incl. customer success", "pct"),
        ),
        (r"\bgross margins?\b|\bgm\b", Measure("gross_margin", "Gross margin", "pct")),
        (r"\bgross profit\b", Measure("gross_profit", "Gross profit", "money")),
        (
            r"\bcost of (?:revenue|goods(?: sold)?|sales)\b|\bcogs\b",
            Measure("cogs", "Cost of revenue", "money"),
        ),
        (
            r"\b(?:r and d|research(?: and development)?|engineering spend)\b",
            Measure("opex.r_and_d", "R&D", "money"),
        ),
        (
            r"\b(?:s and m|sales and marketing|marketing(?: spend)?)\b",
            Measure("opex.s_and_m", "Sales & marketing", "money"),
        ),
        (r"\b(?:g and a|general and admin\w*|overheads?)\b", Measure("opex.g_and_a", "G&A", "money")),
        (
            r"\bcustomer success\b|\bsupport (?:cost|spend)s?\b",
            Measure("opex.customer_success", "Customer success", "money"),
        ),
        (
            r"\bother (?:opex|op ex|operating (?:expenses|costs)|expenses|costs|spend)\b|\bopex other\b",
            Measure("opex.other", "Other opex", "money"),
        ),
        (
            r"\b(?:total )?(?:operating expenses|opex|op ex|operating costs|spend)\b",
            Measure("opex.total", "Operating expenses", "money"),
        ),
        (
            r"\boperating (?:income|loss|profit)\b|\bebit\b",
            Measure("operating_income", "Operating income", "money"),
        ),
        (
            r"\bnet (?:income|loss|profit)\b|\bbottom line\b|\bprofit\b",
            Measure("net_income", "Net income", "money"),
        ),
        (r"\bdepreciation\b", Measure("depreciation", "Depreciation", "money")),
        (r"\b" + _CREDITS + r"\b", Measure("non_dilutive_income", "Non-dilutive income", "money")),
        # balance, team, customers, pipeline
        (
            r"\bcash(?: balance| on hand| in (?:the )?bank)?\b",
            Measure("cash_balance", "Cash balance", "money"),
        ),
        (
            r"\bheadcount\b|\bemployees\b|\bteam size\b|\bftes?\b",
            Measure("headcount.total", "Headcount", "count"),
        ),
        (r"\bnew (?:customers|logos)\b", Measure("customers.new", "New customers", "count")),
        (
            r"\b(?:churned|lost) (?:customers|logos)\b",
            Measure("customers.churned", "Churned customers", "count"),
        ),
        (r"\bcustomers?(?: count)?\b|\blogos\b", Measure("customers.count", "Customers", "count")),
        (r"\bbookings\b", Measure("bookings", "Bookings", "money")),
        (r"\bpipeline\b", Measure("pipeline", "Pipeline", "money")),
        (r"\brevenue\b|\bsales\b|\btop line\b|\bturnover\b", Measure("revenue", "Revenue", "money")),
    ]


def _measures(t: str, ctx: TruthContext) -> list[_Hit]:
    taken: list[tuple[int, int]] = []
    hits: list[_Hit] = []
    for pat, m in _vocabulary(ctx):
        for mt in re.finditer(pat, t):
            s, e = mt.span()
            if any(s < te and ts < e for ts, te in taken):
                continue
            taken.append((s, e))
            hits.append(_Hit(s, e, m))
    hits.sort(key=lambda h: h.start)
    out: list[_Hit] = []
    for h in hits:  # "revenue and revenue" → one series
        if all(x.measure.ref != h.measure.ref for x in out):
            out.append(h)
    return out


# ---------------------------------------------------------------- modifiers

_QUESTION = re.compile(r"^(?:why|how|should|explain|would|could|is|are|was|were|do|does|did|will|who|when)\b")
_CHART_VERB = re.compile(
    r"\b(?:show|add|chart|plot|graph|display|visuali[sz]e|track|compare|break ?down|give me|put|"
    r"create|make|draw|pin|build)\b"
)
_ZOOM = re.compile(r"\b(?:zoom|focus|narrow|limit|restrict|only show|show only|just show|just the|filter)\b")
_RESET = re.compile(
    r"\b(?:reset|clear|remove|undo)\b.*\b(?:zoom|range|filter|time)\b|\bzoom (?:all the way )?out\b|"
    r"\bshow (?:all|everything)\b|\ball time\b|\bfull (?:range|history)\b|\bunzoom\b"
)
_WINDOW = re.compile(
    r"\b(?:last|past|previous|trailing|recent|latest|most recent)\s+(?:(\d+)\s+)?(months?|quarters?|years?)\b"
)
_TTM = re.compile(r"\b(?:ttm|ltm|l12m|trailing twelve months)\b")
_GROUP = re.compile(
    r"\b(?:by|per|each|every) (month|quarter|year)s?\b|\b(monthly|quarterly|annual(?:ly)?|yearly)\b"
)
_PCT_OF = re.compile(r"\b(?:as (?:a )?)?(?:pct|share|proportion|ratio|fraction) (?:of|to) |\bpct of ")
_GROWTH = re.compile(r"\bgrowth(?: rate)?\b|\bgrowing\b")
_YOY = re.compile(r"\byoy\b|\byear on year\b|\byear over year\b|\bannual growth\b")
_CUMULATIVE = re.compile(r"\bcumulative\b|\brunning total\b")
_ROLLING = re.compile(
    r"\b(?:rolling|moving|trailing) (\d+) (month|quarter|period)s? (?:average|avg|mean)\b|"
    r"\b(\d+) (month|quarter|period)s? (?:rolling|moving) (?:average|avg|mean)\b"
)
_COMPARE_YOY = re.compile(
    r"\b(?:vs|versus|against|compared (?:to|with)) (?:the )?(?:same period )?(?:last|prior|previous) year\b"
)
_COMPARE_PREV = re.compile(
    r"\b(?:vs|versus|against|compared (?:to|with)) (?:the )?(?:last|prior|previous) "
    r"(?:period|month|quarter)\b"
)
_TEMPLATES: list[tuple[str, str]] = [
    (r"\bstacked\b|\bbreak ?down\b|\bmix\b|\bsplit\b|\bby category\b", "stacked_bar"),
    (r"\bwaterfall\b|\bbridge\b", "waterfall"),
    (r"\btable\b", "table"),
    (r"\barea\b", "area"),
    (r"\bbars?\b|\bcolumns?\b|\bhistogram\b", "bar"),
    (r"\blines?\b|\btrend\b|\bover time\b", "line"),
    (r"\bkpi\b|\bcard\b|\btile\b|\bheadline\b", "kpi"),
    (r"\bgauge\b|\bring\b|\bdonut\b", "gauge_ring"),
]


def _window_months(t: str) -> int | None:
    if _TTM.search(t):
        return 12
    m = _WINDOW.search(t)
    if not m:
        return None
    n = int(m.group(1) or 1)
    unit = m.group(2).rstrip("s")
    return max(1, min(240, n * _UNIT_MONTHS[unit]))


def _group_by(t: str) -> str | None:
    m = _GROUP.search(t)
    if not m:
        return None
    word = m.group(1) or m.group(2)
    return {
        "monthly": "month",
        "quarterly": "quarter",
        "annual": "year",
        "annually": "year",
        "yearly": "year",
    }.get(word, word)


_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
_SPAN_PARTS = re.compile(
    r"\bq([1-4]) (\d{4})\b|\b(\d{4}) q([1-4])\b|\b(" + "|".join(_MONTHS) + r")[a-z]* (\d{4})\b|"
    r"\b(\d{4}) (0[1-9]|1[0-2])\b|\b((?:19|20)\d{2})\b"
)


def _span(t: str) -> dict[str, str] | None:
    """The months named in "zoom to Q1 2026", "2025", "jan 2025 to mar 2026": {from, to} as YYYY-MM."""
    bounds: list[tuple[str, str]] = []
    for m in _SPAN_PARTS.finditer(t):
        if m.group(1) or m.group(3):
            y, q = (m.group(2), int(m.group(1))) if m.group(1) else (m.group(3), int(m.group(4)))
            bounds.append((f"{y}-{3 * q - 2:02d}", f"{y}-{3 * q:02d}"))
        elif m.group(5):
            ym = f"{m.group(6)}-{_MONTHS.index(m.group(5)) + 1:02d}"
            bounds.append((ym, ym))
        elif m.group(7):
            bounds.append((f"{m.group(7)}-{m.group(8)}", f"{m.group(7)}-{m.group(8)}"))
        else:
            bounds.append((f"{m.group(9)}-01", f"{m.group(9)}-12"))
    if not bounds:
        return None
    return {"from": min(b[0] for b in bounds), "to": max(b[1] for b in bounds)}


def _template(t: str) -> str | None:
    return next((tpl for pat, tpl in _TEMPLATES if re.search(pat, t)), None)


def _lower(label: str) -> str:
    return label if label[:2].isupper() else label[:1].lower() + label[1:]


def _range_label(months: int) -> str:
    if months % 12 == 0 and months >= 12:
        n = months // 12
        return "the last year" if n == 1 else f"the last {n} years"
    return "the last month" if months == 1 else f"the last {months} months"


# ---------------------------------------------------------------- interpretation


def interpret(text: str, ctx: TruthContext) -> Intent:
    """Map one dashboard request to a widget spec, a time range, a question, or nothing."""
    t = normalise(text)
    if not t:
        return Intent(kind="none", summary="Type what you'd like to see.")
    if _RESET.search(t):
        return Intent(kind="time_range", last_months=None, summary="Showing the full range")

    hits = _measures(t, ctx)
    months = _window_months(t)
    if _ZOOM.search(t) and months:
        return Intent(kind="time_range", last_months=months, summary=f"Zoomed to {_range_label(months)}")
    if _ZOOM.search(t) and (span := _span(t)):
        return Intent(kind="time_range", span=span, summary=f"Zoomed to {span['from']} → {span['to']}")
    if not hits and months and len(t.split()) <= 6:  # "last 6 months"
        return Intent(kind="time_range", last_months=months, summary=f"Zoomed to {_range_label(months)}")
    if "valuation" in t or "valued" in t or (_QUESTION.match(t) and not _CHART_VERB.search(t)):
        return Intent(kind="question", summary="That's a question for the panel.")
    if not hits:
        return Intent(kind="none", summary="I couldn't find a metric in that.")
    spec = _build_spec(t, hits, months, ctx)
    return Intent(kind="widget", spec=spec, summary=spec.title)


def _rolling(t: str, group_by: str | None, native: str) -> tuple[int, str, str | None] | None:
    """(periods, period word, group_by) for "3 month rolling average", or None.

    The average spans the months asked for: "3 month rolling average by quarter" can't be a whole number
    of quarters of two or more, so it is averaged by month (rolling(x, 3)), never stretched to 2 quarters.
    """
    roll = _ROLLING.search(t)
    if not roll:
        return None
    n, unit = int(roll.group(1) or roll.group(3)), roll.group(2) or roll.group(4)
    target = group_by or native
    if _GRAN_MONTHS[target] < _GRAN_MONTHS[native]:
        target = native
    if unit == "period":
        return max(2, n), target, group_by
    months = n * _UNIT_MONTHS[unit]
    per = _GRAN_MONTHS[target]
    if (months % per or months // per < 2) and _GRAN_MONTHS[unit] >= _GRAN_MONTHS[native]:
        target = unit  # average at the window's own granularity
        group_by = None if unit == native else unit
        per = _GRAN_MONTHS[target]
    return max(2, math.ceil(months / per)), target, group_by


def _build_spec(t: str, hits: list[_Hit], months: int | None, ctx: TruthContext) -> WidgetSpec:
    group_by = _group_by(t)
    native = ctx.model.granularity if ctx.model.granularity in _GRAN_MONTHS else "month"
    roll = _rolling(t, group_by, native)
    if roll:
        group_by = roll[2]
    target = group_by or native
    if _GRAN_MONTHS[target] < _GRAN_MONTHS[native]:
        target = native  # the evaluator explains this in a note
    explicit = _template(t)

    if hits[0].measure.ref == "cohort_retention":
        m = hits[0].measure
        return WidgetSpec(template="heatmap", title=m.label, series=[SeriesSpec(ref=m.ref)])

    scalars = [h.measure for h in hits if h.measure.scalar]
    if scalars and (len(scalars) == len(hits) or explicit in ("kpi", "gauge_ring")):
        tpl = "gauge_ring" if explicit == "gauge_ring" else "kpi"
        series = [SeriesSpec(ref=m.ref, label=m.label) for m in (scalars or [h.measure for h in hits])][
            :MAX_SERIES
        ]
        return WidgetSpec(template=tpl, title=series[0].label or "", series=series)
    measures = [h.measure for h in hits if not h.measure.scalar]

    # "a as % of b": everything before the marker is a numerator, the first measure after it the denominator
    series: list[tuple[str, str, Unit]] = []
    pct = _PCT_OF.search(t)
    den = next((h for h in hits if pct and h.start >= pct.end() and not h.measure.scalar), None)
    if pct and den is not None:
        nums = [h.measure for h in hits if h.end <= pct.start() and not h.measure.scalar] or [
            h.measure for h in hits if h is not den and not h.measure.scalar
        ][:1]
        for n in nums:
            series.append(
                (
                    f"pct_of({n.ref}, {den.measure.ref})",
                    f"{n.label} as % of {_lower(den.measure.label)}",
                    "pct",
                )
            )
    elif explicit == "stacked_bar" and any(m.ref == "opex.total" for m in measures):
        cats = [c for c in OPEX_CATEGORIES if ctx.model.has(c)] or ["opex.total"]
        series = [(c, OPEX_NAMES.get(c, "Operating expenses"), "money") for c in cats]
    else:
        series = [(m.ref, m.label, m.unit) for m in measures]
    if not series:  # "runway as % of revenue": a single figure can't be a share of a series
        if scalars:
            return WidgetSpec(
                template="kpi",
                title=scalars[0].label,
                series=[SeriesSpec(ref=m.ref, label=m.label) for m in scalars][:MAX_SERIES],
            )
        series = [(m.ref, m.label, m.unit) for m in measures]

    # transforms
    if roll:
        n = roll[0]
        series = [(f"rolling({r}, {n})", f"{lbl}, {n}-{roll[1]} average", u) for r, lbl, u in series]
    elif _CUMULATIVE.search(t):
        series = [(f"cumsum({r})", f"Cumulative {_lower(lbl)}", u) for r, lbl, u in series]
    elif _GROWTH.search(t) and all(u != "pct" for _, _, u in series):
        fn, word = ("yoy", "growth, year on year") if _YOY.search(t) else ("mom", "growth, period on period")
        series = [(f"{fn}({r})", f"{lbl} {word}", "pct") for r, lbl, _ in series]
    series = series[:MAX_SERIES]

    compare = "yoy" if _COMPARE_YOY.search(t) else "previous_period" if _COMPARE_PREV.search(t) else None
    units = {u for _, _, u in series}
    mixed = len(units) > 1
    if explicit in ("line", "area", "bar", "stacked_bar", "table", "waterfall"):
        tpl = explicit
    elif mixed:
        tpl = "combo_bar_line"
    elif group_by in ("quarter", "year"):
        tpl = "bar"
    else:
        tpl = "line"
    if tpl == "waterfall":
        series = series[:1]

    # the first unit stays on the left; any other unit goes to the right axis
    first = series[0][2]
    specs = [
        SeriesSpec(
            ref=r,
            label=lbl[:80],
            axis="right" if mixed and u != first else "left",
            style="dashed" if mixed and u != first and tpl != "combo_bar_line" else "solid",
        )
        for r, lbl, u in series
    ]

    window = None
    if months:
        window = Window(last_n=max(1, math.ceil(months / _GRAN_MONTHS[target])))

    names = [lbl for _, lbl, _ in series]
    title = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + _lower(names[-1])
    if group_by:
        title += f" by {target}"
    if months:
        title += f", {_range_label(months)[4:]}"
    if compare:
        title += " vs a year earlier" if compare == "yoy" else " vs the previous period"
    return WidgetSpec(
        template=tpl,
        title=title[:120],
        series=specs,
        group_by=group_by,
        window=window,
        compare=compare,
        presentation=Presentation(stack=tpl == "stacked_bar", dual_axis=mixed),
    )
