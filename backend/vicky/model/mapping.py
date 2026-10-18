"""Column mapping: source columns → canonical fields.

`propose_heuristic` is the deterministic mapper (always available, also the offline path).
The Claude mapper in `vicky.agents.mapper` refines it; the founder confirms either way.
"""

import re

from pydantic import BaseModel

from vicky.model.canonical import FIELDS, SPECIAL_KINDS
from vicky.model.currencies import strip_currency
from vicky.model.loader import ColumnProfile, ParsedDataset, strip_scale


class ColumnMapping(BaseModel):
    source_column: str
    canonical_field: str | None
    unit: str = ""
    confidence: float = 0.5
    note: str = ""


def _norm(name: str) -> str:
    # "Revenue (USD)" and "Revenue ($000)" map like "Revenue"; the unit keeps the currency, the loader the scale.
    name = strip_currency(strip_scale(name))
    s = name.lower().replace("&", " and ").replace("r&d", "rnd")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return f" {s.strip()} "


# (pattern, field, confidence). First match wins, so specific rules come first.
RULES: list[tuple[str, str | None, float]] = [
    (r"^ (month|period|date|quarter|qtr|year|week|day|fiscal (period|year|month|quarter)|(month|period|week) (ending|end|start)|"
     r"line item|reporting (period|month|date)|billing (month|period|date)|as (of|at)( date)?|transaction date|posting date) $",
     "period", 0.95),
    # Lines that look like revenue/cash/customers but are derived metrics or balance-sheet items:
    # keep them raw rather than double count (ARR is 12× MRR; burn is not a cash balance).
    (r"^ (arr|annual recurring revenue|run rate|annual run rate) $", None, 0.6),
    (r" (mrr churn|revenue churn|churn rate|net revenue retention|gross revenue retention|nrr|grr|retention)\b", None, 0.6),
    (r" accounts (payable|receivable) | (deferred|unearned) revenue |^ (ap|ar) $", None, 0.6),
    (r" (cash burn|burn rate|net burn|operating cash flow|free cash flow|cash flow)\b", None, 0.6),
    (r"^ (net )?(revenue|sales|turnover|income from sales) $", "revenue.total", 0.9),
    (r"^ gross (revenue|sales|receipts) $", "revenue.total", 0.85),
    (r" (product|software) (revenue|sales)| (support|maintenance) (revenue|income|sales)", "revenue.recurring", 0.6),
    # totals
    (r" total (net )?revenue | total sales | revenue total | net revenue ", "revenue.total", 0.95),
    (r" total (cogs|cost of (revenue|sales|goods sold))| cost of (revenue|sales|goods sold) total |^ (cogs|cost of (revenue|sales|goods sold)) $", "cogs", 0.95),
    (r" total (operating )?(expenses|opex)| opex total | total opex ", "opex.total", 0.95),
    # "Total costs" may include cost of revenue: proposed with low confidence so the founder checks it.
    (r"^ total (costs|spend|spending|operating costs) $", "opex.total", 0.55),
    (r" gross (profit|margin dollars)", "gross_profit", 0.95),
    (r" ebitda | operating (income|profit|loss)| ebit ", "operating_income", 0.9),
    (r" net (income|profit|loss|earnings)| bottom line ", "net_income", 0.95),
    # non-dilutive
    (r" sr ?and ?ed | sred | srred | tax credit| r and d credit| rnd credit| grant| non dilutive| government (funding|assistance)| irap ", "non_dilutive_income", 0.9),
    # revenue lines
    (r" (subscription|recurring|saas|license|licence|platform|mrr)\b.*(revenue|sales|income)?", "revenue.recurring", 0.85),
    (r" (onboarding|implementation|professional services|services|setup|set up|one time|consulting|project|training)\b.*", "revenue.one_time", 0.75),
    (r" (revenue|sales|turnover) $", "revenue.total", 0.6),
    # cost of revenue components
    (r"^ direct (costs?|expenses) $| cost of (goods|services)", "cogs", 0.8),
    (r" (hosting|infrastructure|cloud|aws|server|sms|telephony|payment processing|merchant fees|third party data|data costs|contractor costs|subcontract|cogs|cost of (revenue|sales|goods))", "cogs", 0.75),
    # opex categories
    (r" (customer success|customer support|support team|cs salaries|account management|support)", "opex.customer_success", 0.85),
    (r" (rnd|r and d|research|engineering|product|development|dev ) ?", "opex.r_and_d", 0.8),
    (r" (sales|marketing|go to market|gtm|commission|paid acquisition|advertising|demand gen|growth marketing|programs|"
     r"ad spend|ads\b|paid media|media spend|seo\b|sem\b|events\b|sponsorships?|lead gen)", "opex.s_and_m", 0.85),
    (r" (g and a|ga |general|admin|office|rent|legal|accounting|bookkeeping|professional fees|software|insurance|overheads?|finance)", "opex.g_and_a", 0.8),
    (r" depreciation| amortization| amortisation| d and a ", "depreciation", 0.9),
    # balance sheet / operating metrics
    (r" (cash|bank balance|cash balance|cash on hand|cash at|ending cash)", "cash_balance", 0.9),
    (r" (headcount|employees|fte|staff count|team size)", "headcount.total", 0.9),
    (r" (new (logos|customers|accounts|clients)|customers added|logos added)", "customers.new", 0.9),
    (r" (churned|lost) (logos|customers|accounts|clients)|customer churn count| churned ", "customers.churned", 0.9),
    (r" (paying customers|customers|customer count|active customers|logos|accounts|clients)", "customers.count", 0.8),
    (r" (subscribers|paying (users|accounts|members)|members)", "customers.count", 0.7),
    (r" bookings ", "bookings", 0.85),
    (r" pipeline ", "pipeline", 0.85),
    (r" (salaries|payroll|wages|people costs)", "opex.other", 0.5),
    (r" other (expenses|opex)", "opex.other", 0.7),
]

COMPONENT_OF_TOTAL = {"cogs": "cogs"}


def _rule_match(name: str) -> tuple[str | None, float]:
    n = _norm(name)
    for pattern, target, conf in RULES:
        if re.search(pattern, n):
            return target, conf
    return None, 0.3


def unit_for(target: str | None, currency: str, col: ColumnProfile | None = None) -> str:
    """The unit a column's values are in once it maps to `target`: the date axis is "date", a customer
    name "text", money its column's currency (read from the file) or `currency`, a count "count". A column
    kept raw says what its values are: "pct", "date", "text", a currency read from the file, or ""."""
    cur = ((col.currency if col else None) or currency).lower()
    if target in SPECIAL_KINDS:
        kind = SPECIAL_KINDS[target]
        return cur if kind == "money" else kind
    f = FIELDS.get(target or "")
    if f is not None:
        return cur if f.kind == "money" else "count"
    if col is None:
        return ""
    if col.unit_hint in ("pct", "date", "text"):
        return col.unit_hint
    return (col.currency or "").lower()


def propose_heuristic(ds: ParsedDataset, currency: str) -> list[ColumnMapping]:
    if ds.table_kind in ("customer_mrr", "cohort_mrr"):
        dim_field = "dim.customer" if ds.table_kind == "customer_mrr" else "dim.cohort"
        out: list[ColumnMapping] = []
        value_done = False
        for c in ds.columns:
            if c.name == ds.period_axis:
                out.append(ColumnMapping(source_column=c.name, canonical_field="period", unit="date", confidence=0.95))
            elif c.dtype in ("text", "period") and not any(m.canonical_field == dim_field for m in out):
                out.append(ColumnMapping(source_column=c.name, canonical_field=dim_field, unit=unit_for(dim_field, currency, c),
                                         confidence=0.9))
            elif c.dtype == "number" and not value_done and re.search(r"mrr|revenue|arr|amount|value", c.name, re.I):
                value_done = True
                out.append(ColumnMapping(source_column=c.name, canonical_field="value.mrr",
                                         unit=unit_for("value.mrr", currency, c), confidence=0.9))
            else:
                out.append(ColumnMapping(source_column=c.name, canonical_field=None, unit=unit_for(None, currency, c),
                                         confidence=0.5, note="kept as raw column"))
        return out

    proposals: list[ColumnMapping] = []
    for c in ds.columns:
        if c.name == "period" or c.name == ds.period_axis:
            proposals.append(ColumnMapping(source_column=c.name, canonical_field="period", unit="date", confidence=0.95))
            continue
        target, conf = _rule_match(c.name)
        note = "" if target else "no canonical match; kept as raw column"
        if target == "period":  # the date axis is set above; another date column stays raw
            target, conf, note = None, 0.9, "another date column; kept raw"
        elif target is not None and c.dtype != "number":
            conf = min(conf, 0.4)
        elif target is not None and c.unit_hint == "pct":
            target, conf, note = None, 0.8, "percentages; kept raw (Vicky computes ratios from the amounts)"
        proposals.append(ColumnMapping(source_column=c.name, canonical_field=target, unit=unit_for(target, currency, c),
                                       confidence=conf, note=note))

    # A column named as the total wins; its components stay raw so they aren't double counted.
    totals = {p.canonical_field for p in proposals if p.confidence >= 0.95}
    for p in proposals:
        if p.canonical_field in COMPONENT_OF_TOTAL and p.canonical_field in totals and p.confidence < 0.95:
            p.note = f"component of {p.canonical_field}; the total column is used"
            p.canonical_field = None  # still money: it keeps its unit
    if "revenue.total" in totals:
        for p in proposals:
            if p.canonical_field == "revenue.total" and p.confidence < 0.95:
                p.canonical_field, p.note = None, "kept raw; a total revenue column exists"
    return proposals


def merge_mappings(base: list[ColumnMapping], better: list[ColumnMapping]) -> list[ColumnMapping]:
    """Prefer `better` per column when it is at least as confident."""
    by_col = {m.source_column: m for m in better}
    out = []
    for m in base:
        b = by_col.get(m.source_column)
        out.append(b if b and b.confidence >= m.confidence - 0.05 else m)
    return out


def mapping_accuracy(proposed: list[ColumnMapping], expected: list[dict]) -> float:
    exp = {e["source_column"]: e.get("canonical_field") for e in expected}
    got = {m.source_column: m.canonical_field for m in proposed}
    keys = [k for k in exp if k in got or True]
    if not keys:
        return 0.0
    return sum(1 for k in keys if got.get(k) == exp[k]) / len(keys)
