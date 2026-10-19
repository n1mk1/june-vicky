"""The truth layer: claim checks, forecast-vs-history gaps and the attack list over 12 lenses.

Everything here is deterministic. Thresholds are stated in the rule text; when a sourced
benchmark exists for the topic its id is attached so agents can cite it as `[src:id]`.
"""

import math
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from vik.model.figures import CURRENCY_UNITS, Fact, Figure, MissingFigure, fmt_value
from vik.model.loader import parse_period, period_end_month
from vik.model.metrics import FACT_ALIASES, label_period
from vik.model.sources import cite_source

ClaimStatus = Literal["matches", "contradicts", "unsupported", "forecast_as_fact"]

# How founders name metrics → figure ids to compare against (first is the default).
METRIC_ALIASES: dict[str, list[str]] = {
    "arr": ["arr"],
    "annual recurring revenue": ["arr"],
    "run rate": ["arr"],
    "mrr": ["mrr"],
    "monthly recurring revenue": ["mrr"],
    "growth": ["cmgr_recent", "cmgr_12m"],
    "monthly growth": ["cmgr_recent", "cmgr_12m"],
    "mom growth": ["cmgr_recent", "cmgr_12m"],
    "cmgr": ["cmgr_recent", "cmgr_12m"],
    "growth rate": ["cmgr_recent", "cmgr_12m"],
    "revenue growth": ["revenue_growth", "cmgr_recent", "cmgr_12m"],
    "yoy growth": ["revenue_growth_yoy"],
    "annual growth": ["revenue_growth_yoy"],
    "churn": ["logo_churn_rate", "revenue_churn_rate"],
    "logo churn": ["logo_churn_rate"],
    "revenue churn": ["revenue_churn_rate"],
    "customer churn": ["logo_churn_rate"],
    "nrr": ["nrr"],
    "net revenue retention": ["nrr"],
    "ndr": ["nrr"],
    "net retention": ["nrr"],
    "grr": ["grr"],
    "gross revenue retention": ["grr"],
    "gross retention": ["grr"],
    "gross margin": ["gross_margin", "gross_margin_incl_cs", "gross_margin_incl_cs_l12m"],
    "margin": ["gross_margin", "gross_margin_incl_cs"],
    "burn": ["burn", "burn_incl_credits"],
    "monthly burn": ["burn", "burn_incl_credits"],
    "burn rate": ["burn", "burn_incl_credits"],
    "runway": ["runway_months"],
    "cash": ["cash_balance"],
    "cash balance": ["cash_balance"],
    "burn multiple": ["burn_multiple", "burn_multiple_ex_credits"],
    "cac": ["cac"],
    "customer acquisition cost": ["cac"],
    "payback": ["cac_payback_months"],
    "cac payback": ["cac_payback_months"],
    "customers": ["customers.count"],
    "customer count": ["customers.count"],
    "top customer": ["top_customer_share"],
    "concentration": ["top_customer_share"],
    "largest customer": ["top_customer_share"],
    "revenue": ["revenue", "arr"],
    "magic number": ["magic_number"],
    "headcount": ["headcount.total"],
}


class ClaimCheck(BaseModel):
    status: ClaimStatus
    metric: str
    value: float
    unit: str
    figure: dict | None = None
    figure_id: str | None = None
    delta: float | None = None
    explanation: str = ""
    text: str = ""  # the founder's own words, when the claim came from a deck or transcript


class AttackItem(BaseModel):
    id: str
    lens: str
    topic: str
    detail: str
    severity: float
    figure_ids: list[str] = Field(default_factory=list)
    source_id: str | None = None
    missing: bool = False
    quotes: list[str] = Field(
        default_factory=list
    )  # founder words the item quotes (allowed through the audit)


def fact_metric(name: str) -> str:
    """The metric a fact speaks to: forecasts are stored as `plan.<name>` (so they never overwrite a historical
    metric), but `plan.mrr` is still a plan for MRR."""
    base = re.sub(r"^(plan|forecast)[._]", "", name)
    return FACT_ALIASES.get(base, base)


def resolve_metric(metric: str) -> list[str]:
    m = metric.lower().strip().replace("_", " ")
    if m in METRIC_ALIASES:
        return METRIC_ALIASES[m]
    key = FACT_ALIASES.get(metric, metric)
    if key != metric:
        return [key]
    for alias, ids in sorted(METRIC_ALIASES.items(), key=lambda kv: -len(kv[0])):
        if alias in m:
            return ids
    return [metric]


ROUND_NUMBER_CAP = 0.05  # a round figure ("$1M") is never read as looser than ±5%


def _tolerance(claimed: float, unit: str, rel: float) -> float:
    """Absolute tolerance: ±rel of the value, or half the precision the founder stated (at most ±5%)."""
    scaled = claimed * 100 if unit == "pct" else claimed
    if scaled == 0:
        precision = 1.0
    else:
        mag = abs(scaled)
        digits = 0
        while digits < 4 and not math.isclose(round(mag, digits), mag, rel_tol=1e-9, abs_tol=1e-9):
            digits += 1
        precision = 10 ** (-digits)
        # Round numbers like 1.3M or 80K carry precision at their leading digits.
        if digits == 0 and mag >= 1000:
            s = f"{int(round(mag))}"
            trailing = len(s) - len(s.rstrip("0"))
            precision = min(10**trailing, 2 * mag * ROUND_NUMBER_CAP)
    half = precision / 2
    if unit == "pct":
        half /= 100
    return max(abs(claimed) * rel, half)


def _same_unit(figure_unit: str, claim_unit: str) -> bool:
    """ "money" and "$" are the reporting currency; an explicit code must be the figure's own currency."""
    if figure_unit in CURRENCY_UNITS and claim_unit in ("money", "$"):
        return True
    return figure_unit == claim_unit or not claim_unit


def check_claim(
    metric: str,
    value: float,
    unit: str,
    figures: dict[str, Figure | MissingFigure],
    period: str | None = None,
    is_forecast: bool = False,
    facts: list[Fact] | None = None,
    rel_tolerance: float = 0.02,
) -> ClaimCheck:
    ids = resolve_metric(metric)
    if period and ("12" in period or "l12m" in period.lower() or "year" in period.lower()):
        ids = sorted(ids, key=lambda i: 0 if "12m" in i or "l12m" in i else 1)
    unit = (unit or "").lower()
    unit = {"%": "pct", "percent": "pct", "month": "months", "mo": "months", "$": "money"}.get(unit, unit)
    if unit == "pct" and abs(value) > 1.5:
        value = value / 100  # "2" with unit % means 2%, i.e. 0.02
    # Non-metric facts (customer count, headcount …) are figures named fact.<id>.
    ids = ids + [f"fact.{i}" for i in ids if f"fact.{i}" in figures and i not in figures]
    candidates = [figures[i] for i in ids if isinstance(figures.get(i), Figure)]
    if not candidates:
        missing = next((figures[i] for i in ids if isinstance(figures.get(i), MissingFigure)), None)
        why = missing.reason if missing else f"No figure for {metric} in the source of truth"
        return ClaimCheck(status="unsupported", metric=metric, value=value, unit=unit, explanation=why)
    best: tuple[float, Figure] | None = None
    for f in candidates:
        if not _same_unit(f.unit, unit):
            continue
        tol = _tolerance(value, f.unit, rel_tolerance)
        diff = abs(value - f.value)
        if diff <= tol and f.kind in ("historical", "founder_claim"):
            return ClaimCheck(
                status="matches",
                metric=metric,
                value=value,
                unit=unit,
                figure=f.model_dump(mode="json"),
                figure_id=f.id,
                delta=value - f.value,
                explanation=f"Matches {f.label} ({f.display}).",
            )
        if best is None or diff < best[0]:
            best = (diff, f)
    if facts and not is_forecast:
        for fact in facts:
            if fact.kind == "forecast" and fact.status != "removed" and fact_metric(fact.name) in ids:
                if abs(value - fact.value) <= _tolerance(value, fact.unit, rel_tolerance):
                    return ClaimCheck(
                        status="forecast_as_fact",
                        metric=metric,
                        value=value,
                        unit=unit,
                        figure_id=ids[0],
                        explanation=f"{fmt_value(fact.value, fact.unit)} is the plan, not an actual ({fact.source.ref}).",
                    )
    if best is None:
        if unit in CURRENCY_UNITS and any(f.unit in CURRENCY_UNITS for f in candidates):
            have = next(f.unit for f in candidates if f.unit in CURRENCY_UNITS)
            return ClaimCheck(
                status="unsupported",
                metric=metric,
                value=value,
                unit=unit,
                explanation=f"The claim is in {unit.upper()}; {metric} is measured in {have.upper()}.",
            )
        return ClaimCheck(
            status="unsupported",
            metric=metric,
            value=value,
            unit=unit,
            explanation=f"The claim's unit ({unit}) doesn't match how {metric} is measured.",
        )
    f = best[1]
    if is_forecast:
        return ClaimCheck(
            status="unsupported",
            metric=metric,
            value=value,
            unit=unit,
            figure=f.model_dump(mode="json"),
            figure_id=f.id,
            delta=value - f.value,
            explanation=f"A forecast; history says {f.label} is {f.display}.",
        )
    return ClaimCheck(
        status="contradicts",
        metric=metric,
        value=value,
        unit=unit,
        figure=f.model_dump(mode="json"),
        figure_id=f.id,
        delta=value - f.value,
        explanation=f"Data says {f.label} is {f.display} ({f.formula}).",
    )


def _end_month(period: str | None) -> int | None:
    """The last month of a period label ("2026-Q4", "2026-09", the end of "2025-10..2026-09"), else None."""
    parsed = parse_period(period.split("..")[-1]) if period else None
    return period_end_month(parsed[0]) if parsed else None


PLAN_HORIZON_MONTHS = 12  # a plan further out than this is a long-range target, not the plan's next step


def _nearest_plan(plans: list[Fact], hist_period: str | None) -> Fact | None:
    """The plan for the first period after the latest history; an undated plan when no dated one is ahead of it.
    A plan only for periods already in the history is stale, and one more than PLAN_HORIZON_MONTHS past it is a
    long-range target ("$5.1M ARR by 2028"): neither is compared."""
    after = _end_month(hist_period)
    dated = [(m, f) for f in plans if (m := _end_month(f.period)) is not None]
    if after is not None:
        dated = [(m, f) for m, f in dated if after < m <= after + PLAN_HORIZON_MONTHS]
    if dated:
        return min(dated, key=lambda mf: mf[0])[1]
    return next((f for f in plans if not f.period), None)


def _src(topic: str, profile: dict) -> str | None:
    hits = cite_source(topic, profile)
    return hits[0]["id"] if hits else None


def _clip(x: float) -> float:
    return round(max(0.05, min(1.0, x)), 2)


def attack_list(
    figures: dict[str, Figure | MissingFigure],
    facts: list[Fact],
    profile: dict[str, Any],
    deck_checks: list[ClaimCheck] | None = None,
) -> list[AttackItem]:
    F = {k: v for k, v in figures.items() if isinstance(v, Figure)}
    items: list[AttackItem] = []

    def add(
        id_: str,
        lens: str,
        topic: str,
        detail: str,
        severity: float,
        figure_ids: list[str],
        src_topic: str | None = None,
    ):
        sid = _src(src_topic, profile) if src_topic else None
        items.append(
            AttackItem(
                id=id_,
                lens=lens,
                topic=topic,
                detail=detail,
                severity=_clip(severity),
                figure_ids=figure_ids,
                source_id=sid,
            )
        )

    # forecast / growth
    g12, gr = F.get("cmgr_12m"), F.get("cmgr_recent")
    if g12 and gr and g12.value > 0 and gr.value < 0.8 * g12.value:
        drop = 1 - gr.value / g12.value
        add(
            "growth_decel",
            "forecast",
            "Growth is slowing",
            f"{gr.display} a month recently against {g12.display} over 12 months.",
            0.55 + drop,
            ["cmgr_recent", "cmgr_12m"],
            "growth",
        )
    # runway
    rw = F.get("runway_months")
    if rw and rw.value < 18:
        add(
            "runway_short",
            "runway",
            "Runway before the next round",
            f"{rw.display} of runway at {F['burn'].display if 'burn' in F else 'current'} burn. Raises usually take 6+ months.",
            (18 - rw.value) / 14,
            ["runway_months", "burn", "cash_balance"],
            "runway",
        )
    # post-round runway (terms / runway)
    rs = profile.get("round_size")
    burn = F.get("burn")
    if rs and burn and burn.value > 0:
        months = float(rs) / burn.value
        add(
            "round_months",
            "terms_cap_table",
            "What the round buys",
            f"The raise covers about {months:.0f} months at today's burn of {burn.display}, before any new hires.",
            0.35 if months >= 18 else 0.6,
            ["burn"],
            "runway",
        )
    # concentration
    tc = F.get("top_customer_share")
    if tc and tc.value >= 0.08:
        add(
            "concentration",
            "concentration",
            "Largest customer dependence",
            f"The largest customer is {tc.display} of MRR.",
            0.3 + tc.value * 3,
            ["top_customer_share"],
            "concentration",
        )
    # retention
    nrr, grr = F.get("nrr"), F.get("grr")
    if nrr and nrr.value < 1.0:
        add(
            "nrr_low",
            "retention",
            "Net revenue retention below 100%",
            f"NRR is {nrr.display}: the installed base shrinks without new sales.",
            0.5 + (1 - nrr.value) * 3,
            ["nrr"],
            "nrr",
        )
    if grr and grr.value < 0.9:
        add(
            "grr_low",
            "retention",
            "Gross retention",
            f"GRR is {grr.display}.",
            0.45 + (0.9 - grr.value) * 3,
            ["grr"],
            "grr",
        )
    churn = F.get("logo_churn_rate") or F.get("revenue_churn_rate")
    if churn and churn.value >= 0.015:
        add(
            "churn",
            "retention",
            "Monthly churn",
            f"{churn.label} is {churn.display}.",
            0.4 + churn.value * 15,
            [churn.id],
            "churn",
        )
    # unit economics
    gm, gmcs = F.get("gross_margin"), F.get("gross_margin_incl_cs_l12m") or F.get("gross_margin_incl_cs")
    if gm and gmcs and gm.value - gmcs.value >= 0.08:
        add(
            "margin_gap",
            "unit_economics",
            "Margin once support is counted",
            f"{gm.display} as booked, {gmcs.display} once customer success is included.",
            0.35 + (gm.value - gmcs.value) * 2,
            ["gross_margin", gmcs.id],
            "gross_margin",
        )
    bm, bmx = F.get("burn_multiple"), F.get("burn_multiple_ex_credits")
    if bm and bm.value > 1.5:
        add(
            "burn_multiple",
            "unit_economics",
            "Capital efficiency",
            f"Burn multiple of {bm.display}.",
            0.4 + (bm.value - 1.5) / 3,
            ["burn_multiple"],
            "burn_multiple",
        )
    if bm and bmx and bmx.value > bm.value * 1.2:
        add(
            "credit_dependence",
            "governance",
            "Efficiency leans on tax credits",
            f"Burn multiple is {bm.display} with credits and {bmx.display} without them.",
            0.55,
            ["burn_multiple", "burn_multiple_ex_credits"],
            "burn_multiple",
        )
    pb = F.get("cac_payback_months")
    if pb and pb.value > 12:
        add(
            "payback",
            "unit_economics",
            "CAC payback",
            f"Payback is {pb.display}.",
            0.35 + (pb.value - 12) / 24,
            ["cac_payback_months", "cac"],
            "cac_payback",
        )
    # product/tech: services share of revenue (a figure, so the share is citable; both amounts from one period)
    share = F.get("one_time_revenue_share")
    if share and share.value >= 0.12:
        add(
            "services_mix",
            "product_tech",
            "Services revenue in the mix",
            f"About {share.display} of the latest period's revenue ({label_period(share.period or '')}) isn't recurring.",
            0.3 + share.value,
            ["one_time_revenue_share"],
        )
    # forecast vs history: one item per metric, against the NEAREST plan period after the latest history. A multi-year
    # growth plan is meant to exceed today's numbers, so only the next step of the plan is a fair test of it.
    plans: dict[str, list[Fact]] = {}
    for fact in facts:
        if fact.kind != "forecast" or fact.status == "removed":
            continue
        key = fact_metric(fact.name)
        hist = F.get(key)
        if hist and hist.value and hist.unit == fact.unit:
            plans.setdefault(key, []).append(fact)
    for key, fs in plans.items():
        hist = F[key]
        fact = _nearest_plan(fs, hist.period)
        if fact is None:
            continue
        ratio = fact.value / hist.value
        if ratio <= 0 or ratio > 1.25 or ratio < 0.75:
            # A plan of zero or of the opposite sign (burn planned while history is profitable) is the largest gap.
            sev = 0.95 if ratio <= 0 else 0.45 + min(abs(math.log(ratio)), 1.0) * 0.5
            parsed = parse_period(fact.period) if fact.period else None
            when = f" for {label_period(parsed[0]) if parsed else fact.period}" if fact.period else ""
            add(
                f"gap_{key}",
                "forecast",
                f"Plan vs history: {hist.label}",
                f"The plan assumes {fmt_value(fact.value, fact.unit)}{when}; history shows {hist.display}.",
                sev,
                [hist.id],
            )
    # deck claims that contradict the model
    for i, c in enumerate(deck_checks or []):
        if c.status in ("contradicts", "forecast_as_fact"):
            fig = F.get(c.figure_id or "")
            label = fig.label if fig else c.metric.replace("_", " ")
            said = f'The deck says "{c.text}"' if c.text else f"The deck's {_lc(label)} figure"
            if c.status == "contradicts" and fig:
                detail = f"{said}; the data says {_lc(label)} is {fig.display}."
            elif c.status == "forecast_as_fact":
                detail = f"{said}, but that number is the plan, not an actual."
            else:
                detail = c.explanation
            add(
                f"deck_{i + 1}",
                "claims",
                f"The deck's {_lc(label)}",
                detail,
                0.85 if c.status == "contradicts" else 0.7,
                [c.figure_id] if c.figure_id else [],
            )
            if c.text:
                items[-1].quotes = [c.text]
    # missing data becomes questions
    for mid, lens, topic in [
        ("nrr", "retention", "Retention isn't evidenced"),
        ("cash_balance", "runway", "No cash balance in the data"),
        ("cac", "unit_economics", "Acquisition cost isn't evidenced"),
        ("top_customer_share", "concentration", "Customer concentration unknown"),
    ]:
        mf = figures.get(mid)
        if isinstance(mf, MissingFigure) and "Recurring-revenue metric" not in mf.reason:
            items.append(
                AttackItem(
                    id=f"missing_{mid}",
                    lens=lens,
                    topic=topic,
                    detail=mf.reason,
                    severity=0.45,
                    figure_ids=[],
                    missing=True,
                )
            )
    # lenses the data can't speak to still get an item so the panel covers them
    covered = {i.lens for i in items}
    country = (profile.get("country") or "").upper()
    soft = {
        "team": (
            "Who does what after the raise",
            "The data has no hiring plan; expect questions on key hires and founder roles.",
            0.3,
        ),
        "market": (
            "Market size and how it's built",
            "No market sizing in the source of truth; expect a bottom-up question.",
            0.35,
        ),
        "governance": (
            "Finance function and controls",
            "Who owns the books, the board, and reporting after the round.",
            0.25,
        ),
        "impact": (
            "Mandate fit",
            f"Mandate-driven funds check fit with their rules{' for ' + country if country else ''}.",
            0.2,
        ),
        "claims": (
            "Every number in the pitch",
            "Each claim will be checked against the source of truth.",
            0.3,
        ),
        "terms_cap_table": ("Round structure", "Instrument, size and dilution will be probed.", 0.3),
        "product_tech": (
            "What is hard to copy",
            "Investors look for the hardest feature, not the slickest.",
            0.25,
        ),
    }
    for lens, (topic, detail, sev) in soft.items():
        if lens not in covered:
            items.append(
                AttackItem(
                    id=f"soft_{lens}", lens=lens, topic=topic, detail=detail, severity=sev, missing=True
                )
            )
    items.sort(key=lambda i: -i.severity)
    return items


_NUM = r"(\d[\d,]*(?:\.\d+)?)"


def _clause(text: str, start: int, end: int) -> str:
    """The founder's own words around a claim: its clause, cut at sentence/clause breaks, never mid-word."""
    breaks = [m.end() for m in re.finditer(r"[.!?;](?=\s)|,\s+(?:and|but|so)\s|\n", text[:start])]
    lo = breaks[-1] if breaks else 0
    nxt = re.search(r"[.!?;](?=\s|$)|,\s+(?:and|but|so)\s|\n", text[end:])
    hi = end + nxt.start() if nxt else len(text)
    clause = text[lo:hi].strip(" ,;")
    if len(clause) > 160:  # very long sentence: keep whole words around the claim
        a = text.rfind(" ", 0, max(0, start - 40)) + 1
        b = text.find(" ", min(len(text), end + 40))
        clause = text[a : b if b != -1 else len(text)].strip(" ,;")
    return clause


def quick_claims(text: str) -> list[dict]:
    """Deterministic claim extraction (offline path for the Flash-Lite extractor)."""
    out: list[dict] = []
    t = text.lower()
    patterns = [
        (
            rf"(?:growing|grow|growth(?: rate)?(?: of| is| at)?)\s*(?:about|around|roughly|~)?\s*{_NUM}\s*%\s*(?:a|per|each|every)?\s*(month|mo|year|yr|quarter)?",
            "growth",
        ),
        (rf"{_NUM}\s*%\s*(?:month[- ]over[- ]month|mom|monthly)\s*(?:growth)?", "growth"),
        (rf"(?:churn(?: rate)?(?: is| of| at)?)\s*(?:about|around|under|below|~)?\s*{_NUM}\s*%", "churn"),
        (rf"{_NUM}\s*%\s*(?:monthly\s+)?churn", "churn"),
        (
            rf"(?:nrr|net revenue retention|net retention|ndr)(?: is| of| at)?\s*(?:about|around|~)?\s*{_NUM}\s*%",
            "nrr",
        ),
        (rf"{_NUM}\s*%\s*(?:nrr|net revenue retention|net retention)", "nrr"),
        (rf"(?:grr|gross retention)(?: is| of| at)?\s*{_NUM}\s*%", "grr"),
        (
            rf"(?:gross margins?|margins?)(?: is| are| of| at)?\s*(?:about|around|~)?\s*{_NUM}\s*%",
            "gross margin",
        ),
        (rf"{_NUM}\s*%\s*(?:gross\s+)?margins?", "gross margin"),
        (rf"\$\s*{_NUM}\s*([kmb])?\s*(?:in\s+)?(?:arr|annual recurring revenue)", "arr"),
        (
            rf"(?:arr|annual recurring revenue)(?: is| of| at)?\s*(?:about|around|~)?\s*\$\s*{_NUM}\s*([kmb])?",
            "arr",
        ),
        (rf"\$\s*{_NUM}\s*([kmb])?\s*(?:in\s+)?(?:mrr|monthly recurring revenue)", "mrr"),
        (
            rf"(?:mrr|monthly recurring revenue)(?: is| of| at)?\s*(?:about|around|~)?\s*\$\s*{_NUM}\s*([kmb])?",
            "mrr",
        ),
        (
            rf"(?:burn(?:ing)?|burn rate)(?: is| of| at)?\s*(?:about|around|~)?\s*\$\s*{_NUM}\s*([kmb])?",
            "burn",
        ),
        (rf"\$\s*{_NUM}\s*([kmb])?\s*(?:a|per)\s*month\s*(?:burn|of burn)", "burn"),
        (rf"{_NUM}\s*months?\s*(?:of\s+)?runway", "runway"),
        (rf"runway(?: is| of)?\s*(?:about|around|~)?\s*{_NUM}\s*months?", "runway"),
        (
            rf"(?:payback|cac payback)(?: is| of| in)?\s*(?:about|around|under|~)?\s*{_NUM}\s*months?",
            "cac payback",
        ),
        (
            rf"(?:largest|biggest|top) customer (?:is|at|accounts for|=)?\s*(?:about|around|~|under)?\s*{_NUM}\s*%",
            "top customer",
        ),
        (rf"{_NUM}\s*(?:paying\s+)?customers", "customers"),
        (rf"burn multiple(?: is| of)?\s*(?:about|around|~)?\s*{_NUM}", "burn multiple"),
    ]
    seen = set()
    for pat, metric in patterns:
        for m in re.finditer(pat, t):
            num = float(m.group(1).replace(",", ""))
            mult = 1.0
            groups = [g for g in m.groups()[1:] if g]
            for g in groups:
                if g in ("k", "m", "b"):
                    mult = {"k": 1e3, "m": 1e6, "b": 1e9}[g]
            unit = (
                "pct"
                if "%" in m.group(0)
                else "months"
                if metric in ("runway", "cac payback")
                else "count"
                if metric == "customers"
                else "x"
                if metric == "burn multiple"
                else "money"
            )
            value = num / 100 if unit == "pct" else num * mult
            period = None
            if metric == "growth":
                per = next((g for g in groups if g in ("year", "yr", "quarter")), None)
                if per:
                    continue  # annual/quarterly growth isn't a monthly CMGR claim
            key = (metric, round(value, 6))
            if key in seen:
                continue
            seen.add(key)
            clause = _clause(text, m.start(), m.end())
            # Only the claim's own clause decides: "ARR is $3M today. Next year we will hire" is a fact, not a plan.
            is_forecast = bool(
                re.search(
                    r"\b(will|plan|projected|forecast|expect|by 20\d\d|next year|target)\b", clause.lower()
                )
            )
            out.append(
                {
                    "text": clause,
                    "metric": metric,
                    "value": value,
                    "unit": unit,
                    "period": period,
                    "is_forecast": is_forecast,
                }
            )
    return out


def _lc(label: str) -> str:
    """Lower-case a label for mid-sentence use, keeping acronyms (ARR, NRR, CAC) intact."""
    first, _, rest = label.partition(" ")
    if first.isupper() and len(first) > 1:
        return label
    return label[:1].lower() + label[1:]
