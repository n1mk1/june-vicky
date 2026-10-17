"""Column mapping: source columns → canonical fields.

`propose_heuristic` is the deterministic mapper (always available, also the offline path).
The Claude mapper in `vicky.agents.mapper` refines it; the founder confirms either way.
"""

import re

from pydantic import BaseModel

from vicky.model.canonical import FIELDS
from vicky.model.loader import ParsedDataset


class ColumnMapping(BaseModel):
    source_column: str
    canonical_field: str | None
    unit: str = ""
    confidence: float = 0.5
    note: str = ""


def _norm(name: str) -> str:
    s = name.lower().replace("&", " and ").replace("r&d", "rnd")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return f" {s.strip()} "


# (pattern, field, confidence). First match wins, so specific rules come first.
RULES: list[tuple[str, str | None, float]] = [
    (r"^ (month|period|date|quarter|qtr|year|fiscal period|month ending|period ending|line item) $", "period", 0.95),
    # totals
    (r" total (net )?revenue | total sales | revenue total | net revenue ", "revenue.total", 0.95),
    (r" total (cogs|cost of (revenue|sales|goods sold))| cost of (revenue|sales|goods sold) total |^ (cogs|cost of (revenue|sales|goods sold)) $", "cogs", 0.95),
    (r" total (operating )?(expenses|opex)| opex total | total opex ", "opex.total", 0.95),
    (r" gross (profit|margin dollars)", "gross_profit", 0.95),
    (r" ebitda | operating (income|profit|loss)| ebit ", "operating_income", 0.9),
    (r" net (income|profit|loss|earnings)| bottom line ", "net_income", 0.95),
    # non-dilutive
    (r" sr ?and ?ed | sred | srred | tax credit| r and d credit| rnd credit| grant| non dilutive| government (funding|assistance)| irap ", "non_dilutive_income", 0.9),
    # revenue lines
    (r" (subscription|recurring|saas|license|licence|platform|mrr|arr)\b.*(revenue|sales|income)?", "revenue.recurring", 0.85),
    (r" (onboarding|implementation|professional services|services|setup|set up|one time|consulting|project|training)\b.*", "revenue.one_time", 0.75),
    (r" (revenue|sales|turnover)$", "revenue.total", 0.6),
    # cost of revenue components
    (r" (hosting|infrastructure|cloud|aws|server|sms|telephony|payment processing|merchant fees|third party data|data costs|contractor costs|subcontract|cogs|cost of (revenue|sales|goods))", "cogs", 0.75),
    # opex categories
    (r" (customer success|customer support|support team|cs salaries|account management|support)", "opex.customer_success", 0.85),
    (r" (rnd|r and d|research|engineering|product|development|dev ) ?", "opex.r_and_d", 0.8),
    (r" (sales|marketing|go to market|gtm|commission|paid acquisition|advertising|demand gen|growth marketing|programs)", "opex.s_and_m", 0.85),
    (r" (g and a|ga |general|admin|office|rent|legal|accounting|bookkeeping|professional fees|software|insurance|overheads?|finance)", "opex.g_and_a", 0.8),
    (r" depreciation| amortization| amortisation| d and a ", "depreciation", 0.9),
    # balance sheet / operating metrics
    (r" (cash|bank balance|cash balance|cash on hand|cash at|ending cash)", "cash_balance", 0.9),
    (r" (headcount|employees|fte|staff count|team size)", "headcount.total", 0.9),
    (r" (new (logos|customers|accounts|clients)|customers added|logos added)", "customers.new", 0.9),
    (r" (churned|lost) (logos|customers|accounts|clients)|customer churn count| churned ", "customers.churned", 0.9),
    (r" (paying customers|customers|customer count|active customers|logos|accounts|clients)", "customers.count", 0.8),
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


def _unit_for(target: str | None, currency: str) -> str:
    if target is None or target == "period":
        return ""
    if target in ("value.mrr",):
        return currency.lower()
    f = FIELDS.get(target)
    if f is None:
        return ""
    return currency.lower() if f.kind == "money" else "count"


def propose_heuristic(ds: ParsedDataset, currency: str) -> list[ColumnMapping]:
    names = ds.column_names()
    if ds.table_kind in ("customer_mrr", "cohort_mrr"):
        dim_field = "dim.customer" if ds.table_kind == "customer_mrr" else "dim.cohort"
        out: list[ColumnMapping] = []
        value_done = False
        for c in ds.columns:
            if c.name == ds.period_axis:
                out.append(ColumnMapping(source_column=c.name, canonical_field="period", confidence=0.95))
            elif c.dtype in ("text", "period") and not any(m.canonical_field == dim_field for m in out):
                out.append(ColumnMapping(source_column=c.name, canonical_field=dim_field, confidence=0.9))
            elif c.dtype == "number" and not value_done and re.search(r"mrr|revenue|arr|amount|value", c.name, re.I):
                value_done = True
                out.append(ColumnMapping(source_column=c.name, canonical_field="value.mrr", unit=currency.lower(), confidence=0.9))
            else:
                out.append(ColumnMapping(source_column=c.name, canonical_field=None, confidence=0.5, note="kept as raw column"))
        return out

    proposals: list[ColumnMapping] = []
    for c in ds.columns:
        if c.name == "period" or c.name == ds.period_axis:
            proposals.append(ColumnMapping(source_column=c.name, canonical_field="period", confidence=0.95))
            continue
        target, conf = _rule_match(c.name)
        if c.dtype != "number" and target not in (None, "period"):
            conf = min(conf, 0.4)
        proposals.append(ColumnMapping(source_column=c.name, canonical_field=target, unit=_unit_for(target, currency),
                                       confidence=conf, note="" if target else "no canonical match; kept as raw column"))

    # A column named as the total wins; its components stay raw so they aren't double counted.
    totals = {p.canonical_field for p in proposals if p.confidence >= 0.95}
    for p in proposals:
        if p.canonical_field in COMPONENT_OF_TOTAL and p.canonical_field in totals and p.confidence < 0.95:
            p.note = f"component of {p.canonical_field}; the total column is used"
            p.canonical_field = None
            p.unit = ""
    if "revenue.total" in totals:
        for p in proposals:
            if p.canonical_field == "revenue.total" and p.confidence < 0.95:
                p.canonical_field, p.note = None, "kept raw; a total revenue column exists"
    _ = names
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
