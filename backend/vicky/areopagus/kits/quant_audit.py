"""QuantAudit: the numbers a careful partner re-derives before believing the deck."""

from vicky.areopagus.kits._base import (
    Kit,
    Result,
    cell_figure,
    derived,
    fmt,
    get,
    last_n_months,
    latest_count,
    missing,
    num,
    out,
    schema,
    sum_figure,
    tool,
)
from vicky.model.context import TruthContext
from vicky.model.figures import Figure
from vicky.model.metrics import label_period

KIT = "QuantAudit"


@tool(KIT, "quant_arr_without_fees",
      "ARR from recurring revenue only, next to the total-revenue run rate that includes one-time fees. "
      "Returns Figures: arr, revenue_run_rate, run_rate_gap, one_time_latest, one_time_share_l12m.")
def arr_without_fees(ctx: TruthContext) -> Result:
    m = ctx.model
    arr, rev = get(ctx, "arr"), get(ctx, "revenue")
    parts: dict = {"arr": arr}
    miss = []
    if isinstance(rev, Figure):
        k = 12 // m.months_per_period
        run = derived("quant.revenue_run_rate", "Total revenue run rate (incl. one-time fees)", rev.value * k, ctx.currency,
                      f"{label_period(rev.period)} total revenue {rev.display} × {k}", [rev], period=rev.period)
        parts["revenue_run_rate"] = run
        if isinstance(arr, Figure):
            parts["run_rate_gap"] = derived(
                "quant.run_rate_gap", "Run rate minus ARR (one-time fees counted as recurring)", run.value - arr.value,
                ctx.currency, f"run rate {run.display} − ARR {arr.display}", [run, arr], period=rev.period)
    else:
        miss.append(rev)
    p = m.latest("revenue.one_time")
    if p is not None:
        parts["one_time_latest"] = cell_figure(ctx, "revenue.one_time", p, fid="quant.one_time_latest",
                                               label=f"One-time revenue, {label_period(p)}")
        ps = [q for q in last_n_months(ctx, "revenue.one_time", 12) if m.value("revenue.total", q)]
        if ps:
            one = sum_figure(ctx, "revenue.one_time", ps, "quant.one_time_l12m", "One-time revenue, last 12 months")
            tot = sum_figure(ctx, "revenue.total", ps, "quant.revenue_l12m", "Total revenue, last 12 months")
            if tot.value > 0:
                parts["one_time_share_l12m"] = derived(
                    "quant.one_time_share_l12m", "One-time share of revenue, last 12 months", one.value / tot.value, "pct",
                    f"one-time revenue {one.display} ÷ total revenue {tot.display}", [one, tot], period=one.period)
    else:
        miss.append(missing("quant.one_time_latest", "One-time revenue", ["revenue.one_time"],
                            "Map one-time / services / onboarding revenue separately to see what ARR excludes"))
    return out(miss, **parts)


@tool(KIT, "quant_retention",
      "Cohort retention passthrough from the engine. Returns Figures (or missing): nrr, grr, logo_churn_rate, "
      "revenue_churn_rate.")
def retention(ctx: TruthContext) -> Result:
    res = out(**{k: get(ctx, k) for k in ("nrr", "grr", "logo_churn_rate", "revenue_churn_rate")})
    res["cohort_table"] = "present" if ctx.model.cohort_mrr else "per-customer table" if ctx.model.customer_mrr else "absent"
    return res


@tool(KIT, "quant_burn_multiple",
      "Burn multiple with and without non-dilutive credits (tax credits, grants). Returns Figures: burn_multiple, "
      "burn_multiple_ex_credits, net_new_arr_l12m, credit_effect (difference between the two).")
def burn_multiple(ctx: TruthContext) -> Result:
    bm, bmx, nna = get(ctx, "burn_multiple"), get(ctx, "burn_multiple_ex_credits"), get(ctx, "net_new_arr_l12m")
    parts: dict = {"burn_multiple": bm, "burn_multiple_ex_credits": bmx, "net_new_arr_l12m": nna}
    if isinstance(bm, Figure) and isinstance(bmx, Figure):
        parts["credit_effect"] = derived("quant.burn_multiple_credit_effect", "Burn multiple added by removing credits",
                                         bmx.value - bm.value, "x", f"{bmx.display} without credits − {bm.display} with them",
                                         [bmx, bm], period=bm.period)
    return out(**parts)


@tool(KIT, "quant_cac_payback",
      "CAC payback on gross margin including customer support (engine), and on margin as booked for comparison. "
      "Returns Figures: cac_payback_months, cac, gross_margin_incl_cs, gross_margin, arpa, payback_on_booked_margin.")
def cac_payback(ctx: TruthContext) -> Result:
    pb, cac, gmcs, gm, mrr = (get(ctx, k) for k in ("cac_payback_months", "cac", "gross_margin_incl_cs", "gross_margin", "mrr"))
    parts: dict = {"cac_payback_months": pb, "cac": cac, "gross_margin_incl_cs": gmcs, "gross_margin": gm}
    customers = latest_count(ctx, "customers.count", "Customers")
    miss = []
    if customers is None:
        miss.append(missing("customers.count", "Customers", ["customers.count"], "Add customer counts by period"))
    if isinstance(mrr, Figure) and customers is not None and customers.value > 0:
        arpa = derived("quant.arpa", "MRR per customer", mrr.value / customers.value, ctx.currency,
                       f"MRR {mrr.display} ÷ customers {customers.display}", [mrr, customers], period=mrr.period)
        parts["arpa"] = arpa
        if isinstance(cac, Figure) and isinstance(gm, Figure) and gm.value > 0:
            parts["payback_on_booked_margin"] = derived(
                "quant.cac_payback_booked_margin", "CAC payback on margin as booked (support excluded)",
                cac.value / (arpa.value * gm.value), "months",
                f"CAC {cac.display} ÷ (MRR per customer {arpa.display} × gross margin as booked {gm.display})",
                [cac, arpa, gm], period=mrr.period)
    return out(miss, **parts)


@tool(KIT, "quant_runway_sensitivity",
      "Runway at current burn and with burn lower and higher by the given percent. Returns Figures: cash_balance, "
      "burn, runway_months, runway_burn_down, runway_burn_up.",
      schema(burn_change_pct=num("Percent change in monthly burn to test both ways; use 20 for the standard ±20% test")))
def runway_sensitivity(ctx: TruthContext, burn_change_pct: float) -> Result:
    x = abs(float(burn_change_pct)) / 100.0
    if x <= 0 or x >= 0.95:
        raise ValueError("burn_change_pct must be between 0 and 95 (percent)")
    cash, burn, runway = get(ctx, "cash_balance"), get(ctx, "burn"), get(ctx, "runway_months")
    parts: dict = {"cash_balance": cash, "burn": burn, "runway_months": runway}
    if isinstance(cash, Figure) and isinstance(burn, Figure) and burn.value > 0:
        tag = f"{burn_change_pct:g}".replace(".", "_").lstrip("-")
        for key, sign, word in (("runway_burn_down", -1, "lower"), ("runway_burn_up", 1, "higher")):
            factor = 1 + sign * x
            parts[key] = derived(f"quant.runway_burn_{'minus' if sign < 0 else 'plus'}_{tag}",
                                 f"Runway with burn {abs(burn_change_pct):g}% {word}", cash.value / (burn.value * factor), "months",
                                 f"cash {cash.display} ÷ (burn {burn.display} × {factor:g}) = cash ÷ {fmt(burn.value * factor, ctx.currency)}",
                                 [cash, burn], projection=True, period=cash.period)
    return out(**parts)


QUANT_AUDIT = Kit(KIT, "Re-derives ARR, retention, burn multiple, CAC payback and runway sensitivity from the data.",
                  [arr_without_fees, retention, burn_multiple, cac_payback, runway_sensitivity])
