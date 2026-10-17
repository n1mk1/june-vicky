"""Availability-aware metric definitions. Code computes every number.

Each metric needs canonical fields; with the inputs present it returns a `Figure`, otherwise a
`MissingFigure` that names the upload that would unlock it. Confirmed facts (data-pack
summaries, document facts, founder statements) fill gaps the datasets can't, and a figure is
only as strong as its weakest input: anything resting on a founder statement is a
`founder_claim`, anything resting on a summary keeps the summary as its source.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from vicky.model.canonical import OPEX_CATEGORIES
from vicky.model.figures import Fact, Figure, FigureRef, MissingFigure, Source
from vicky.model.financials import CanonicalModel
from vicky.model.loader import period_sort_key

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Aliases so facts named in different ways land on the metric they describe.
FACT_ALIASES: dict[str, str] = {
    "net_revenue_retention": "nrr", "nrr": "nrr", "ndr": "nrr", "net_dollar_retention": "nrr",
    "gross_revenue_retention": "grr", "grr": "grr",
    "cac": "cac", "customer_acquisition_cost": "cac", "fully_loaded_cac": "cac", "cac_fully_loaded": "cac",
    "cac_payback": "cac_payback_months", "cac_payback_months": "cac_payback_months", "payback_months": "cac_payback_months",
    "logo_churn": "logo_churn_rate", "logo_churn_rate": "logo_churn_rate", "monthly_logo_churn": "logo_churn_rate",
    "revenue_churn": "revenue_churn_rate", "mrr_churn": "revenue_churn_rate", "revenue_churn_rate": "revenue_churn_rate",
    "monthly_revenue_churn": "revenue_churn_rate", "gross_mrr_churn": "revenue_churn_rate",
    "top_customer_share": "top_customer_share", "largest_customer_share": "top_customer_share",
    "customer_concentration": "top_customer_share",
    "runway": "runway_months", "runway_months": "runway_months",
    "cash": "cash_balance", "cash_balance": "cash_balance", "cash_in_bank": "cash_balance",
    "customers": "customers.count", "customer_count": "customers.count", "customers_count": "customers.count",
    "customers.count": "customers.count", "paying_customers": "customers.count",
    "new_customers": "customers.new", "customers.new": "customers.new",
    "headcount": "headcount.total", "headcount.total": "headcount.total",
}


def label_period(p: str) -> str:
    if "-Q" in p:
        y, q = p.split("-Q")
        return f"Q{q} {y}"
    if "-" in p:
        y, m = p.split("-")
        return f"{MONTH_NAMES[int(m) - 1]} {y[2:]}"
    return p


@dataclass
class Ctx:
    model: CanonicalModel
    facts: dict[str, Fact]
    profile: dict[str, Any]
    out: dict[str, Figure | MissingFigure]

    @property
    def unit(self) -> str:
        return self.model.currency

    @property
    def mpp(self) -> int:
        return self.model.months_per_period

    def fig(self, fid: str) -> Figure | None:
        f = self.out.get(fid)
        return f if isinstance(f, Figure) else None

    def fact(self, metric_id: str) -> Fact | None:
        return self.facts.get(metric_id)


def _src(ctx: Ctx, fid: str, periods: list[str]) -> Source:
    ds, ref, kind = ctx.model.source_ref(fid, periods)
    k = kind if kind in ("csv", "xlsx") else "derived"
    return Source(kind=k, ref=ref, dataset_id=ds)


def _weakest(primary: Source, inputs: list[Figure]) -> tuple[Source, str]:
    kinds = {f.source.kind for f in inputs}
    fig_kinds = {f.kind for f in inputs}
    if "founder_stated" in kinds or "founder_claim" in fig_kinds:
        src = next(f.source for f in inputs if f.source.kind == "founder_stated" or f.kind == "founder_claim")
        return src, "founder_claim"
    if "forecast" in fig_kinds:
        return primary, "forecast"
    for k in ("pack_summary", "pdf", "docx", "md"):
        if k in kinds:
            return next(f.source for f in inputs if f.source.kind == k), "historical"
    return primary, "historical"


def _fact_figure(ctx: Ctx, metric_id: str, label: str, unit: str, group: str, why: str) -> Figure | None:
    fact = ctx.fact(metric_id)
    if fact is None:
        return None
    kind = "founder_claim" if fact.source.kind == "founder_stated" else fact.kind
    return Figure(id=metric_id, label=label, value=fact.value, unit=unit if unit else fact.unit,
                  formula=why or (fact.label or fact.name), inputs=[], source=fact.source, kind=kind,
                  period=fact.period, group=group)


def _missing(fid: str, label: str, needs: list[str], reason: str, group: str) -> MissingFigure:
    return MissingFigure(id=fid, label=label, needs=needs, reason=reason, group=group)


def _window(model: CanonicalModel, fid: str, n: int) -> list[str]:
    return model.periods_with(fid)[-n:]


def _cmgr(start: float, end: float, months: float) -> float | None:
    if start <= 0 or end <= 0 or months <= 0:
        return None
    return (end / start) ** (1 / months) - 1


# ---------------------------------------------------------------- recurring set

def m_mrr(ctx: Ctx) -> Figure | MissingFigure:
    m = ctx.model
    p = m.latest("revenue.recurring")
    if p is None:
        return _fact_figure(ctx, "mrr", "MRR", ctx.unit, "recurring", "") or _missing(
            "mrr", "MRR", ["revenue.recurring"], "Map a subscription/recurring revenue column to unlock MRR and ARR", "recurring")
    v = m.value("revenue.recurring", p) / ctx.mpp
    per = " ÷ 3" if ctx.mpp == 3 else ""
    return Figure(id="mrr", label="MRR", value=v, unit=ctx.unit,
                  formula=f"{label_period(p)} recurring revenue{per}",
                  inputs=[FigureRef(dataset_id=m.cell('revenue.recurring', p).dataset_id, column="revenue.recurring", period=p,
                                    value=m.value("revenue.recurring", p))],
                  source=_src(ctx, "revenue.recurring", [p]), period=p, group="recurring")


def m_arr(ctx: Ctx) -> Figure | MissingFigure:
    mrr = ctx.fig("mrr")
    if mrr is None:
        return _fact_figure(ctx, "arr", "ARR", ctx.unit, "recurring", "") or _missing(
            "arr", "ARR", ["revenue.recurring"], "Map a recurring revenue column to unlock ARR", "recurring")
    return Figure(id="arr", label="ARR", value=mrr.value * 12, unit=ctx.unit,
                  formula=f"MRR {mrr.display} × 12 (recurring only; one-time fees excluded)",
                  inputs=[FigureRef(figure_id="mrr", value=mrr.value)], source=mrr.source, kind=mrr.kind,
                  period=mrr.period, group="recurring")


def _growth(ctx: Ctx, fid: str, label: str, months: int, field: str = "revenue.recurring") -> Figure | MissingFigure:
    m = ctx.model
    steps = max(1, months // ctx.mpp)
    ps = m.periods_with(field)
    if len(ps) < steps + 1:
        return _missing(fid, label, [field], f"Needs at least {steps + 1} periods of {field.split('.')[-1]} revenue", "recurring")
    start_p, end_p = ps[-steps - 1], ps[-1]
    rate = _cmgr(m.value(field, start_p), m.value(field, end_p), steps * ctx.mpp)
    if rate is None:
        return _missing(fid, label, [field], "Revenue must be positive at both ends of the window", "recurring")
    return Figure(id=fid, label=label, value=rate, unit="pct",
                  formula=f"Compound monthly growth of {field.split('.')[-1]} revenue, {label_period(start_p)} → {label_period(end_p)} "
                          f"(({m.value(field, end_p):,.0f} ÷ {m.value(field, start_p):,.0f})^(1/{steps * ctx.mpp}) − 1)",
                  inputs=[FigureRef(column=field, period=start_p, value=m.value(field, start_p)),
                          FigureRef(column=field, period=end_p, value=m.value(field, end_p))],
                  source=_src(ctx, field, [start_p, end_p]), period=f"{start_p}..{end_p}", group="recurring")


def m_cmgr_12m(ctx: Ctx) -> Figure | MissingFigure:
    return _growth(ctx, "cmgr_12m", "Monthly growth, last 12 months", 12)


def m_cmgr_recent(ctx: Ctx) -> Figure | MissingFigure:
    months = 2 if ctx.mpp == 1 else 3
    return _growth(ctx, "cmgr_recent", f"Monthly growth, last {months} months", months)


def m_net_new_arr(ctx: Ctx) -> Figure | MissingFigure:
    m = ctx.model
    steps = 12 // ctx.mpp
    ps = m.periods_with("revenue.recurring")
    if len(ps) < steps + 1:
        return _missing("net_new_arr_l12m", "Net new ARR, last 12 months", ["revenue.recurring"],
                        "Needs 13 months (or 5 quarters) of recurring revenue", "recurring")
    a, b = ps[-steps - 1], ps[-1]
    v = (m.value("revenue.recurring", b) - m.value("revenue.recurring", a)) / ctx.mpp * 12
    return Figure(id="net_new_arr_l12m", label="Net new ARR, last 12 months", value=v, unit=ctx.unit,
                  formula=f"(MRR {label_period(b)} − MRR {label_period(a)}) × 12",
                  inputs=[FigureRef(column="revenue.recurring", period=a, value=m.value("revenue.recurring", a)),
                          FigureRef(column="revenue.recurring", period=b, value=m.value("revenue.recurring", b))],
                  source=_src(ctx, "revenue.recurring", [a, b]), period="L12M", group="recurring")


def _l12m_sum(ctx: Ctx, field: str) -> tuple[float, list[str]] | None:
    steps = 12 // ctx.mpp
    ps = _window(ctx.model, field, steps)
    if len(ps) < steps:
        return None
    return sum(ctx.model.value(field, p) for p in ps), ps


def _burn_multiple(ctx: Ctx, fid: str, label: str, include_credits: bool) -> Figure | MissingFigure:
    nna = ctx.fig("net_new_arr_l12m")
    ni = _l12m_sum(ctx, "net_income")
    if nna is None or ni is None:
        return _missing(fid, label, ["revenue.recurring", "net_income"], "Needs 12 months of net income and recurring revenue", "recurring")
    total, ps = ni
    credits = 0.0
    if not include_credits:
        nd = _l12m_sum(ctx, "non_dilutive_income")
        credits = nd[0] if nd else 0.0
    burn = -(total - credits)
    if nna.value <= 0:
        return _missing(fid, label, ["revenue.recurring"], "Net new ARR is not positive over the window, so the burn multiple is undefined", "recurring")
    note = "including" if include_credits else "excluding"
    return Figure(id=fid, label=label, value=burn / nna.value, unit="x",
                  formula=f"Net burn {note} non-dilutive credits over the last 12 months ({burn:,.0f}) ÷ net new ARR ({nna.value:,.0f})",
                  inputs=[FigureRef(figure_id="net_new_arr_l12m", value=nna.value), FigureRef(column="net_income", period="L12M", value=total)],
                  source=_src(ctx, "net_income", ps), period="L12M", group="recurring")


def m_burn_multiple(ctx: Ctx) -> Figure | MissingFigure:
    return _burn_multiple(ctx, "burn_multiple", "Burn multiple", True)


def m_burn_multiple_ex_credits(ctx: Ctx) -> Figure | MissingFigure:
    if not ctx.model.has("non_dilutive_income"):
        return _missing("burn_multiple_ex_credits", "Burn multiple excluding credits", ["non_dilutive_income"],
                        "No tax-credit or grant income in the data, so there is nothing to exclude", "recurring")
    return _burn_multiple(ctx, "burn_multiple_ex_credits", "Burn multiple excluding credits", False)


def _retention(ctx: Ctx, fid: str, label: str, gross: bool) -> Figure | MissingFigure:
    m = ctx.model
    if m.cohort_mrr or m.customer_mrr:
        table = m.cohort_mrr or {}
        if not table and m.customer_mrr:
            # pivot customer → period
            table = {}
            for p, by_c in m.customer_mrr.items():
                for c, v in by_c.items():
                    table.setdefault(c, {})[p] = v
        periods = sorted({p for by_p in table.values() for p in by_p}, key=period_sort_key)
        steps = 12 // max(1, 3 if periods and "-Q" in periods[-1] else 1)
        if len(periods) > steps:
            start, end = periods[-steps - 1], periods[-1]
            base = now = 0.0
            for by_p in table.values():
                s = by_p.get(start)
                if not s:
                    continue
                e = by_p.get(end, 0.0)
                base += s
                now += min(e, s) if gross else e
            if base > 0:
                src_ds = m.table_sources.get("cohort_mrr") or m.table_sources.get("customer_mrr")
                kind = "csv"
                return Figure(id=fid, label=label, value=now / base, unit="pct",
                              formula=f"MRR in {label_period(end)} from customers active in {label_period(start)}"
                                      f"{', each capped at its starting MRR (no expansion)' if gross else ''} ÷ their MRR in {label_period(start)}",
                              inputs=[FigureRef(column="cohort_mrr", period=start, value=base), FigureRef(column="cohort_mrr", period=end, value=now)],
                              source=Source(kind=kind, ref=f"cohort table {label_period(start)} → {label_period(end)}", dataset_id=src_ds),
                              period="L12M", group="recurring")
    f = _fact_figure(ctx, fid, label, "pct", "recurring", "")
    return f or _missing(fid, label, ["cohort_mrr"], "Upload a cohort or per-customer MRR table to unlock NRR and GRR", "recurring")


def m_nrr(ctx: Ctx) -> Figure | MissingFigure:
    return _retention(ctx, "nrr", "Net revenue retention", gross=False)


def m_grr(ctx: Ctx) -> Figure | MissingFigure:
    return _retention(ctx, "grr", "Gross revenue retention", gross=True)


def _count_fig(ctx: Ctx, fid: str) -> Figure | None:
    m = ctx.model
    p = m.latest(fid)
    if p is not None:
        return Figure(id=fid, label=fid, value=m.value(fid, p), unit="count", formula=f"{fid} in {label_period(p)}",
                      source=_src(ctx, fid, [p]), period=p, group="customers")
    fact = ctx.fact(fid)
    if fact:
        return Figure(id=fid, label=fact.label or fid, value=fact.value, unit="count", formula=fact.label or fid,
                      source=fact.source, kind="founder_claim" if fact.source.kind == "founder_stated" else fact.kind,
                      period=fact.period, group="customers")
    return None


def m_cac(ctx: Ctx) -> Figure | MissingFigure:
    m = ctx.model
    steps = max(1, 6 // ctx.mpp)
    ps_new = _window(m, "customers.new", steps)
    ps_sm = _window(m, "opex.s_and_m", steps)
    if len(ps_new) == steps and ps_new == ps_sm:
        new = sum(m.value("customers.new", p) for p in ps_new)
        sm = sum(m.value("opex.s_and_m", p) for p in ps_sm)
        if new > 0:
            return Figure(id="cac", label="Customer acquisition cost", value=sm / new, unit=ctx.unit,
                          formula=f"Sales & marketing spend ÷ new customers, {label_period(ps_sm[0])} → {label_period(ps_sm[-1])}",
                          inputs=[FigureRef(column="opex.s_and_m", period="window", value=sm),
                                  FigureRef(column="customers.new", period="window", value=new)],
                          source=_src(ctx, "opex.s_and_m", ps_sm), period=f"{ps_sm[0]}..{ps_sm[-1]}", group="recurring")
    return _fact_figure(ctx, "cac", "Customer acquisition cost", ctx.unit, "recurring", "") or _missing(
        "cac", "Customer acquisition cost", ["opex.s_and_m", "customers.new"],
        "Add new-customer counts by period to unlock CAC and payback", "recurring")


def m_cac_payback(ctx: Ctx) -> Figure | MissingFigure:
    cac, mrr = ctx.fig("cac"), ctx.fig("mrr")
    customers = _count_fig(ctx, "customers.count")
    gm = ctx.fig("gross_margin_incl_cs") or ctx.fig("gross_margin")
    if cac and mrr and customers and gm and customers.value > 0 and gm.value > 0:
        arpa = mrr.value / customers.value
        v = cac.value / (arpa * gm.value)
        src, kind = _weakest(cac.source, [cac, mrr, customers, gm])
        return Figure(id="cac_payback_months", label="CAC payback", value=v, unit="months",
                      formula=f"CAC {cac.display} ÷ (MRR per customer {arpa:,.0f} × gross margin incl. support {gm.display})",
                      inputs=[FigureRef(figure_id=f.id, value=f.value) for f in (cac, mrr, customers, gm)],
                      source=src, kind=kind, period=mrr.period, group="recurring")
    return _fact_figure(ctx, "cac_payback_months", "CAC payback", "months", "recurring", "") or _missing(
        "cac_payback_months", "CAC payback", ["customers.count", "customers.new", "opex.s_and_m"],
        "Needs customer counts and new-customer counts", "recurring")


def m_logo_churn(ctx: Ctx) -> Figure | MissingFigure:
    m = ctx.model
    ps = m.periods_with("customers.churned")
    if ps and m.has("customers.count"):
        p = ps[-1]
        prev = [q for q in m.periods_with("customers.count") if period_sort_key(q) < period_sort_key(p)]
        if prev:
            start = m.value("customers.count", prev[-1])
            if start and start > 0:
                v = m.value("customers.churned", p) / start / ctx.mpp
                return Figure(id="logo_churn_rate", label="Logo churn, monthly", value=v, unit="pct",
                              formula=f"Customers churned in {label_period(p)} ÷ customers at the start ({start:,.0f})"
                                      + (" ÷ 3 months" if ctx.mpp == 3 else ""),
                              source=_src(ctx, "customers.churned", [p]), period=p, group="recurring")
    return _fact_figure(ctx, "logo_churn_rate", "Logo churn, monthly", "pct", "recurring", "") or _missing(
        "logo_churn_rate", "Logo churn, monthly", ["customers.churned", "customers.count"],
        "Add churned-customer counts to unlock logo churn", "recurring")


def m_revenue_churn(ctx: Ctx) -> Figure | MissingFigure:
    return _fact_figure(ctx, "revenue_churn_rate", "Revenue churn, monthly", "pct", "recurring", "") or _missing(
        "revenue_churn_rate", "Revenue churn, monthly", ["cohort_mrr"],
        "Upload per-customer MRR by month to unlock revenue churn", "recurring")


def m_magic_number(ctx: Ctx) -> Figure | MissingFigure:
    m = ctx.model
    q = 3 // ctx.mpp if ctx.mpp < 3 else 1
    ps = m.periods_with("revenue.recurring")
    sm = m.periods_with("opex.s_and_m")
    if len(ps) >= 2 * q + 1 and len(sm) >= 2 * q:
        end = ps[-1]
        mid = ps[-1 - q]
        prev_sm_periods = [p for p in sm if period_sort_key(p) <= period_sort_key(mid)][-q:]
        if len(prev_sm_periods) == q:
            delta_arr = (m.value("revenue.recurring", end) - m.value("revenue.recurring", mid)) / ctx.mpp * 12
            spend = sum(m.value("opex.s_and_m", p) for p in prev_sm_periods)
            if spend > 0:
                return Figure(id="magic_number", label="Magic number", value=delta_arr / spend, unit="x",
                              formula=f"Net new ARR in the last quarter ({delta_arr:,.0f}) ÷ sales & marketing in the prior quarter ({spend:,.0f})",
                              source=_src(ctx, "opex.s_and_m", prev_sm_periods), period=end, group="recurring")
    return _missing("magic_number", "Magic number", ["revenue.recurring", "opex.s_and_m"],
                    "Needs two quarters of recurring revenue and sales & marketing spend", "recurring")


# ---------------------------------------------------------------- generic set

def m_revenue(ctx: Ctx) -> Figure | MissingFigure:
    m = ctx.model
    p = m.latest("revenue.total")
    if p is None:
        return _missing("revenue", "Revenue", ["revenue.total"], "Map a revenue column", "generic")
    return Figure(id="revenue", label=f"Revenue, {label_period(p)}", value=m.value("revenue.total", p), unit=ctx.unit,
                  formula=f"Total revenue in {label_period(p)}", source=_src(ctx, "revenue.total", [p]), period=p, group="generic")


def m_revenue_growth(ctx: Ctx) -> Figure | MissingFigure:
    m = ctx.model
    ps = m.periods_with("revenue.total")
    if len(ps) < 2:
        return _missing("revenue_growth", "Revenue growth", ["revenue.total"], "Needs at least two periods of revenue", "generic")
    a, b = ps[-2], ps[-1]
    va, vb = m.value("revenue.total", a), m.value("revenue.total", b)
    if not va:
        return _missing("revenue_growth", "Revenue growth", ["revenue.total"], "Prior-period revenue is zero", "generic")
    per = "quarter over quarter" if ctx.mpp == 3 else "month over month"
    return Figure(id="revenue_growth", label=f"Revenue growth, {per}", value=vb / va - 1, unit="pct",
                  formula=f"Total revenue {label_period(b)} ({vb:,.0f}) ÷ {label_period(a)} ({va:,.0f}) − 1",
                  source=_src(ctx, "revenue.total", [a, b]), period=b, group="generic")


def m_revenue_growth_yoy(ctx: Ctx) -> Figure | MissingFigure:
    m = ctx.model
    steps = 12 // ctx.mpp
    ps = m.periods_with("revenue.total")
    if len(ps) < steps + 1:
        return _missing("revenue_growth_yoy", "Revenue growth, year over year", ["revenue.total"], "Needs 13 months (or 5 quarters) of revenue", "generic")
    a, b = ps[-steps - 1], ps[-1]
    va, vb = m.value("revenue.total", a), m.value("revenue.total", b)
    if not va:
        return _missing("revenue_growth_yoy", "Revenue growth, year over year", ["revenue.total"], "Year-ago revenue is zero", "generic")
    return Figure(id="revenue_growth_yoy", label="Revenue growth, year over year", value=vb / va - 1, unit="pct",
                  formula=f"Total revenue {label_period(b)} ÷ {label_period(a)} − 1",
                  source=_src(ctx, "revenue.total", [a, b]), period=b, group="generic")


def _margin(ctx: Ctx, fid: str, label: str, with_cs: bool, l12m: bool) -> Figure | MissingFigure:
    m = ctx.model
    needs = ["revenue.total", "cogs"] + (["opex.customer_success"] if with_cs else [])
    if with_cs and not m.has("opex.customer_success"):
        return _missing(fid, label, needs, "Map a customer success / support cost line to see margin including support", "generic")
    steps = 12 // ctx.mpp if l12m else 1
    ps = [p for p in m.periods_with("revenue.total") if m.value("cogs", p) is not None]
    if with_cs:
        ps = [p for p in ps if m.value("opex.customer_success", p) is not None]
    if len(ps) < steps:
        return _missing(fid, label, needs, "Needs revenue and cost of revenue for the window", "generic")
    ps = ps[-steps:]
    rev = sum(m.value("revenue.total", p) for p in ps)
    cost = sum(m.value("cogs", p) for p in ps) + (sum(m.value("opex.customer_success", p) for p in ps) if with_cs else 0)
    if rev <= 0:
        return _missing(fid, label, needs, "Revenue is zero over the window", "generic")
    window = f"{label_period(ps[0])} → {label_period(ps[-1])}" if l12m else label_period(ps[-1])
    cs = " − customer success" if with_cs else ""
    return Figure(id=fid, label=label, value=(rev - cost) / rev, unit="pct",
                  formula=f"(revenue − cost of revenue{cs}) ÷ revenue, {window}",
                  inputs=[FigureRef(column="revenue.total", period=window, value=rev), FigureRef(column="costs", period=window, value=cost)],
                  source=_src(ctx, "revenue.total", ps), period="L12M" if l12m else ps[-1], group="generic")


def m_gross_margin(ctx: Ctx) -> Figure | MissingFigure:
    return _margin(ctx, "gross_margin", "Gross margin, as booked", False, False)


def m_gross_margin_incl_cs(ctx: Ctx) -> Figure | MissingFigure:
    return _margin(ctx, "gross_margin_incl_cs", "Gross margin incl. customer success", True, False)


def m_gross_margin_incl_cs_l12m(ctx: Ctx) -> Figure | MissingFigure:
    return _margin(ctx, "gross_margin_incl_cs_l12m", "Gross margin incl. customer success, last 12 months", True, True)


def _burn(ctx: Ctx, fid: str, label: str, exclude_credits: bool) -> Figure | MissingFigure:
    m = ctx.model
    steps = max(1, 6 // ctx.mpp)
    ps = _window(m, "net_income", steps)
    if not ps:
        return _missing(fid, label, ["net_income"], "Map net income (or revenue and costs) to unlock burn", "generic")
    burns = []
    for p in ps:
        ni = m.value("net_income", p)
        nd = (m.value("non_dilutive_income", p) or 0) if exclude_credits else 0
        burns.append(-(ni - nd))
    avg = sum(burns) / len(burns) / ctx.mpp
    note = "excluding non-dilutive credits" if exclude_credits else "including non-dilutive credits"
    return Figure(id=fid, label=label, value=avg, unit=ctx.unit,
                  formula=f"Average monthly net loss {note}, {label_period(ps[0])} → {label_period(ps[-1])}",
                  inputs=[FigureRef(column="net_income", period=p, value=m.value("net_income", p)) for p in ps],
                  source=_src(ctx, "net_income", ps), period=f"{ps[0]}..{ps[-1]}", group="generic")


def m_burn(ctx: Ctx) -> Figure | MissingFigure:
    return _burn(ctx, "burn", "Average monthly burn", True)


def m_burn_incl_credits(ctx: Ctx) -> Figure | MissingFigure:
    if not ctx.model.has("non_dilutive_income"):
        return _missing("burn_incl_credits", "Average monthly burn incl. credits", ["non_dilutive_income"],
                        "No credits or grants in the data", "generic")
    return _burn(ctx, "burn_incl_credits", "Average monthly burn incl. credits", False)


def m_cash(ctx: Ctx) -> Figure | MissingFigure:
    m = ctx.model
    p = m.latest("cash_balance")
    if p is not None:
        return Figure(id="cash_balance", label="Cash", value=m.value("cash_balance", p), unit=ctx.unit,
                      formula=f"Cash at the end of {label_period(p)}", source=_src(ctx, "cash_balance", [p]), period=p, group="generic")
    return _fact_figure(ctx, "cash_balance", "Cash", ctx.unit, "generic", "") or _missing(
        "cash_balance", "Cash", ["cash_balance"], "Add a cash balance (bank statement or balance sheet) to unlock runway", "generic")


def m_runway(ctx: Ctx) -> Figure | MissingFigure:
    cash, burn = ctx.fig("cash_balance"), ctx.fig("burn")
    if cash and burn:
        if burn.value <= 0:
            return _missing("runway_months", "Runway", ["net_income"], "Not burning cash over the window, so runway doesn't apply", "generic")
        src, kind = _weakest(burn.source, [cash, burn])
        return Figure(id="runway_months", label="Runway", value=cash.value / burn.value, unit="months",
                      formula=f"Cash {cash.display} ÷ average monthly burn {burn.display}",
                      inputs=[FigureRef(figure_id="cash_balance", value=cash.value), FigureRef(figure_id="burn", value=burn.value)],
                      source=src, kind=kind, period=cash.period, group="generic")
    return _fact_figure(ctx, "runway_months", "Runway", "months", "generic", "") or _missing(
        "runway_months", "Runway", ["cash_balance", "net_income"], "Add a cash balance to unlock runway", "generic")


def m_top_customer(ctx: Ctx) -> Figure | MissingFigure:
    m = ctx.model
    if m.customer_mrr:
        p = sorted(m.customer_mrr, key=period_sort_key)[-1]
        by_c = m.customer_mrr[p]
        total = sum(by_c.values())
        if total > 0:
            name, top = max(by_c.items(), key=lambda kv: kv[1])
            return Figure(id="top_customer_share", label="Largest customer's share of MRR", value=top / total, unit="pct",
                          formula=f"Largest customer's MRR in {label_period(p)} ({top:,.0f}) ÷ total ({total:,.0f})",
                          source=Source(kind="csv", ref=f"customer table · {label_period(p)}", dataset_id=m.table_sources.get("customer_mrr")),
                          period=p, group="generic")
    return _fact_figure(ctx, "top_customer_share", "Largest customer's share of MRR", "pct", "generic", "") or _missing(
        "top_customer_share", "Largest customer's share of MRR", ["customer_mrr"],
        "Upload per-customer MRR to unlock concentration", "generic")


def m_opex_mix(ctx: Ctx) -> list[Figure | MissingFigure]:
    m = ctx.model
    steps = 12 // ctx.mpp
    out: list[Figure | MissingFigure] = []
    present = [c for c in OPEX_CATEGORIES if m.has(c)]
    if not present:
        return [_missing("opex_mix", "Operating expense mix", OPEX_CATEGORIES, "Map expense lines to categories to see the mix", "generic")]
    ps = m.periods[-steps:]
    totals = {c: sum(m.value(c, p) or 0 for p in ps) for c in present}
    whole = sum(totals.values())
    if whole <= 0:
        return out
    names = {"opex.r_and_d": "R&D", "opex.s_and_m": "Sales & marketing", "opex.g_and_a": "G&A",
             "opex.customer_success": "Customer success", "opex.other": "Other"}
    for c in present:
        out.append(Figure(id=f"opex_share_{c.split('.')[-1]}", label=f"{names[c]} share of opex", value=totals[c] / whole, unit="pct",
                          formula=f"{names[c]} ÷ categorised opex, {label_period(ps[0])} → {label_period(ps[-1])}",
                          source=_src(ctx, c, [p for p in ps if m.value(c, p) is not None]), period="L12M", group="generic"))
    return out


Metric = Callable[[Ctx], Figure | MissingFigure]

RECURRING: list[Metric] = [m_mrr, m_arr, m_cmgr_12m, m_cmgr_recent, m_net_new_arr, m_burn_multiple, m_burn_multiple_ex_credits,
                           m_nrr, m_grr, m_cac, m_logo_churn, m_revenue_churn, m_magic_number]
GENERIC: list[Metric] = [m_revenue, m_revenue_growth, m_revenue_growth_yoy, m_gross_margin, m_gross_margin_incl_cs,
                         m_gross_margin_incl_cs_l12m, m_burn, m_burn_incl_credits, m_cash, m_runway, m_top_customer]
RECURRING_IDS = ["mrr", "arr", "cmgr_12m", "cmgr_recent", "net_new_arr_l12m", "burn_multiple", "burn_multiple_ex_credits",
                 "nrr", "grr", "cac", "cac_payback_months", "logo_churn_rate", "revenue_churn_rate", "magic_number"]


def facts_by_metric(facts: list[Fact]) -> dict[str, Fact]:
    out: dict[str, Fact] = {}
    for f in facts:
        if f.status == "removed":
            continue
        key = FACT_ALIASES.get(f.name, f.name)
        prev = out.get(key)
        if prev is None or (f.period or "") >= (prev.period or ""):
            out[key] = f
    return out


def compute_metrics(model: CanonicalModel, facts: list[Fact], profile: dict[str, Any]) -> dict[str, Figure | MissingFigure]:
    ctx = Ctx(model=model, facts=facts_by_metric(facts), profile=profile, out={})
    recurring = profile.get("business_model", "recurring") == "recurring" and (model.has("revenue.recurring") or "mrr" in ctx.facts)
    for fn in GENERIC:
        f = fn(ctx)
        ctx.out[f.id] = f
    for f in m_opex_mix(ctx):
        ctx.out[f.id] = f
    if recurring:
        for fn in RECURRING:
            f = fn(ctx)
            ctx.out[f.id] = f
        f = m_cac_payback(ctx)
        ctx.out[f.id] = f
    else:
        reason = "Recurring-revenue metric; the company profile is not recurring" if profile.get("business_model") == "other" \
            else "No recurring revenue in the data"
        for mid in RECURRING_IDS:
            ctx.out[mid] = _missing(mid, mid, ["revenue.recurring"], reason, "recurring")
    _apply_fact_overrides(ctx)
    return ctx.out


def _apply_fact_overrides(ctx: Ctx) -> None:
    """Facts for metrics the engine couldn't compute become figures (labelled with their source)."""
    for key, fact in ctx.facts.items():
        current = ctx.out.get(key)
        if isinstance(current, MissingFigure) and "Recurring-revenue metric" not in current.reason:
            unit = fact.unit if fact.unit else "count"
            kind = "founder_claim" if fact.source.kind == "founder_stated" else fact.kind
            ctx.out[key] = Figure(id=key, label=current.label or fact.label or key, value=fact.value, unit=unit,
                                  formula=fact.label or fact.name, source=fact.source, kind=kind, period=fact.period,
                                  group=current.group)


def fact_figures(facts: list[Fact], exclude: set[str]) -> list[Figure]:
    """Confirmed facts that are not metrics still become citable figures (e.g. round size, plan assumptions)."""
    out = []
    for f in facts:
        if f.status == "removed":
            continue
        fid = FACT_ALIASES.get(f.name, f.name)
        if fid in exclude:
            continue
        unit = f.unit if f.unit in ("cad", "usd", "gbp", "eur", "aud", "pct", "months", "count", "ratio", "x") else "count"
        out.append(Figure(id=f"fact.{f.name}", label=f.label or f.name, value=f.value, unit=unit, formula=f.label or f.name,
                          source=f.source, kind="founder_claim" if f.source.kind == "founder_stated" else f.kind,
                          period=f.period, group="facts"))
    return out
