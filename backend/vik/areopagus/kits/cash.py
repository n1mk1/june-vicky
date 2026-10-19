"""Cash: Paul Graham's default-alive test and the fatal-pinch date.

Default alive: with expenses held where they are and revenue growing at the recent rate,
revenue reaches expenses before the cash runs out. The fatal-pinch date here is the month
the cash would run out on that trajectory.
"""

from vik.areopagus.kits._base import (
    Kit,
    Result,
    add_months,
    boolean,
    cell_figure,
    derived,
    enum,
    fig,
    founder_figure,
    get,
    last_n_months,
    missing,
    opt_num,
    out,
    pct,
    pct_arg,
    recent_growth,
    schema,
    sum_figure,
    tool,
)
from vik.areopagus.kits.benchmark import sourced
from vik.model.context import TruthContext
from vik.model.figures import Figure, MissingFigure
from vik.model.metrics import label_period

KIT = "Cash"
HORIZON = 120  # months simulated


def simulate(cash: float, revenue: float, expenses: float, growth: float, horizon: int = HORIZON) -> dict:
    """Month-by-month cash with revenue compounding and expenses flat."""
    low = cash
    for t in range(1, horizon + 1):
        r = revenue * (1 + growth) ** t
        cash += r - expenses
        low = min(low, cash)
        if r >= expenses and cash >= 0:
            return {"verdict": "default_alive", "month": t, "low": low}
        if cash < 0:
            return {"verdict": "default_dead", "month": t, "low": low}
    return {"verdict": "undetermined", "month": horizon, "low": low}


def required_growth(cash: float, revenue: float, expenses: float) -> float | None:
    """Lowest constant monthly growth that makes the company default alive (bisection)."""
    if simulate(cash, revenue, expenses, 1.0)["verdict"] != "default_alive":
        return None
    lo, hi = -0.5, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if simulate(cash, revenue, expenses, mid)["verdict"] == "default_alive":
            hi = mid
        else:
            lo = mid
    return hi


def _monthly_expenses(ctx: TruthContext, p: str, include_credits: bool) -> Figure | MissingFigure:
    m = ctx.model
    mpp = m.months_per_period
    rev, oi = m.value("revenue.total", p), m.value("operating_income", p)
    if rev is None or oi is None:
        return missing(
            "cash.monthly_expenses",
            "Monthly expenses",
            ["revenue.total", "operating_income or costs"],
            "Needs revenue and costs for the latest period",
        )
    rf, of = cell_figure(ctx, "revenue.total", p), cell_figure(ctx, "operating_income", p)
    per = f" ÷ {mpp}" if mpp > 1 else ""
    inputs = [x for x in (rf, of) if x]
    value = (rev - oi) / mpp
    formula = f"(revenue {rf.display if rf else rev} − operating income {of.display if of else oi}) in {label_period(p)}{per}"
    if include_credits and m.has("non_dilutive_income"):
        ps = last_n_months(ctx, "non_dilutive_income", 12)
        cred = sum_figure(
            ctx, "non_dilutive_income", ps, "cash.credits_l12m", "Tax credits and grants, last 12 months"
        )
        months = len(ps) * mpp
        value -= cred.value / months
        formula += f" − credits {cred.display} ÷ {months} months"
        inputs.append(cred)
    return derived(
        "cash.monthly_expenses",
        "Monthly expenses" + (" net of credits" if include_credits else ""),
        value,
        ctx.currency,
        formula,
        inputs,
        period=p,
    )


@tool(
    KIT,
    "cash_default_alive",
    "Paul Graham's default-alive test: expenses flat, revenue growing at the recent (or 12-month) rate or the "
    "founder's downside rate, from today's cash. Returns Figures: cash_balance, monthly_revenue, monthly_expenses, "
    "growth, months_to_breakeven or months_to_zero (forecast), cash_low_point, required_growth; verdict and "
    "fatal_pinch_month as text.",
    schema(
        growth_basis=enum(["recent", "l12m"], "Which historical monthly growth rate to use"),
        growth_override_pct=opt_num(
            "Founder's own downside monthly growth in percent (e.g. 2); null to use history"
        ),
        include_credits=boolean("True to net average monthly tax credits and grants off expenses"),
    ),
)
def default_alive(
    ctx: TruthContext, growth_basis: str, growth_override_pct: float | None, include_credits: bool
) -> Result:
    m = ctx.model
    cash = get(ctx, "cash_balance")
    p = m.latest("revenue.total")
    if not isinstance(cash, Figure) or p is None:
        miss = [cash] if isinstance(cash, MissingFigure) else []
        if p is None:
            miss.append(
                missing("cash.monthly_revenue", "Monthly revenue", ["revenue.total"], "Map a revenue column")
            )
        return out(miss)
    rf = cell_figure(ctx, "revenue.total", p)
    mpp = m.months_per_period
    rev = derived(
        "cash.monthly_revenue",
        "Monthly revenue",
        rf.value / mpp,
        ctx.currency,
        f"total revenue {rf.display} in {label_period(p)}" + (f" ÷ {mpp}" if mpp > 1 else ""),
        [rf],
        period=p,
    )
    exp = _monthly_expenses(ctx, p, include_credits)
    if growth_override_pct is not None:
        g: Figure | MissingFigure = founder_figure(
            "cash.growth_assumption",
            "Founder's downside monthly growth",
            pct_arg(growth_override_pct, "growth_override_pct"),
            "pct",
        )
    else:
        g = recent_growth(ctx, "recent" if growth_basis == "recent" else "l12m")
    miss = [x for x in (exp, g) if isinstance(x, MissingFigure)]
    parts: dict = {
        "cash_balance": cash,
        "monthly_revenue": rev,
        "monthly_expenses": exp,
        "growth": g,
        "burn": get(ctx, "burn"),
    }
    if miss:
        return out(miss, **parts)
    assert isinstance(exp, Figure) and isinstance(g, Figure)
    if rev.value >= exp.value:
        res = out(**parts)
        res["verdict"] = "profitable_now"
        res["explanation"] = (
            "Revenue already covers expenses in the latest period, so the company is default alive today."
        )
        return res
    sim = simulate(cash.value, rev.value, exp.value, g.value)
    rule = (
        f"cash {cash.display} + Σ(revenue {rev.display} × (1 + {pct(g.value)})^t − expenses {exp.display}) "
        f"month by month"
    )
    ins = [cash, rev, exp, g]
    if sim["verdict"] == "default_alive":
        parts["months_to_breakeven"] = derived(
            "cash.months_to_breakeven",
            "Months until revenue covers expenses",
            sim["month"],
            "months",
            f"first month t where revenue ≥ expenses; {rule}",
            ins,
            projection=True,
        )
        parts["breakeven_month"] = add_months(p, sim["month"])
    elif sim["verdict"] == "default_dead":
        parts["months_to_zero"] = derived(
            "cash.months_to_zero",
            "Months until cash runs out",
            sim["month"],
            "months",
            f"first month t where cash < 0 before revenue covers expenses; {rule}",
            ins,
            projection=True,
        )
        parts["fatal_pinch_month"] = add_months(p, sim["month"])
    parts["cash_low_point"] = derived(
        "cash.low_point",
        "Lowest cash balance on this trajectory",
        sim["low"],
        ctx.currency,
        f"minimum of {rule}",
        ins,
        projection=True,
    )
    need = required_growth(cash.value, rev.value, exp.value)
    if need is not None:
        parts["required_growth"] = derived(
            "cash.required_growth",
            "Monthly growth needed to be default alive",
            need,
            "pct",
            f"lowest constant monthly growth g at which {rule} reaches break-even before zero",
            [cash, rev, exp],
            projection=True,
        )
    res = out(**parts)
    res["verdict"] = sim["verdict"]
    method = [s.get("id") for s in sourced(["default_alive"], ctx.profile)]
    if method:
        res["method_sources"] = [str(x) for x in method]
    res["explanation"] = {
        "default_alive": "On this trajectory revenue reaches expenses before the cash runs out.",
        "default_dead": "On this trajectory the cash runs out before revenue reaches expenses (the fatal pinch).",
        "undetermined": f"Neither break-even nor zero cash within {HORIZON // 12} years on this trajectory.",
    }[sim["verdict"]]
    return res


@tool(
    KIT,
    "cash_burn_profile",
    "Burn with and without credits, cash and runway from the engine, plus the latest period's net income. Returns "
    "Figures: burn, burn_incl_credits, cash_balance, runway_months, burn_multiple, net_income_latest.",
)
def burn_profile(ctx: TruthContext) -> Result:
    parts: dict = {
        k: get(ctx, k)
        for k in ("burn", "burn_incl_credits", "cash_balance", "runway_months", "burn_multiple")
    }
    p = ctx.model.latest("net_income")
    if p:
        parts["net_income_latest"] = cell_figure(ctx, "net_income", p, fid="cash.net_income_latest")
    elif fig(ctx, "burn") is None:
        parts["net_income_latest"] = missing(
            "cash.net_income_latest", "Net income", ["net_income"], "Map net income"
        )
    return out(**parts)


CASH = Kit(KIT, "Default-alive test, fatal-pinch date and the burn profile.", [default_alive, burn_profile])
