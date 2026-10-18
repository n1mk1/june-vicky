"""RedTeam: pre-mortem stress scenarios and plan-vs-history gaps."""

from vicky.areopagus.kits._base import (
    PERIOD_RX,
    UNITS,
    Kit,
    Result,
    cell_figure,
    derived,
    enum,
    fact_series,
    fact_to_figure,
    fig,
    fmt,
    get,
    latest_count,
    live_facts,
    missing,
    months_between,
    months_to_reach,
    out,
    pct,
    period_months,
    recent_growth,
    schema,
    tool,
)
from vicky.model.context import TruthContext
from vicky.model.figures import Fact, Figure, MissingFigure
from vicky.model.loader import period_sort_key
from vicky.model.metrics import FACT_ALIASES, label_period

KIT = "RedTeam"
HORIZON = 12
CURRENCIES = {"cad", "usd", "gbp", "eur", "aud"}
CHECKPOINTS = (3, 6, 9, 12)


def normalize_value(value: float, unit: str | None, target_unit: str) -> float:
    """Plan percentages written as 25 mean 25% when the history is a fraction."""
    if target_unit == "pct" and (unit in ("pct", "%", "percent", "", None)) and abs(value) > 1.5:
        return value / 100
    return value


def _growth_decay(ctx: TruthContext) -> Result:
    mrr, g_r, g_l = get(ctx, "mrr"), get(ctx, "cmgr_recent"), get(ctx, "cmgr_12m")
    miss = [f for f in (mrr, g_r, g_l) if isinstance(f, MissingFigure)]
    if miss:
        return out(miss)
    assert isinstance(mrr, Figure) and isinstance(g_r, Figure) and isinstance(g_l, Figure)
    window = 2 if ctx.model.months_per_period == 1 else 3
    k = 6 - window / 2  # months between the midpoints of the 12-month and the recent window
    decaying = g_r.value > 0 and g_l.value > 0 and g_r.value < g_l.value
    r = (g_r.value / g_l.value) ** (1 / k) if decaying else 1.0
    level, g = mrr.value, g_r.value
    path = []
    for t in range(1, HORIZON + 1):
        g = g_r.value * r**t
        level *= 1 + g
        if t in CHECKPOINTS:
            path.append((t, level, g))
    rule = (
        f"monthly growth starts at {pct(g_r.value)} and is multiplied by {r:.4f} each month "
        f"(({pct(g_r.value)} ÷ {pct(g_l.value)})^(1/{k:g}), the decay from the 12-month to the recent rate)"
        if decaying
        else f"monthly growth held at the recent {pct(g_r.value)} (it is not below the 12-month rate)"
    )
    pts = []
    for t, lv, _ in path:
        f = derived(
            f"redteam.decay_arr_m{t}",
            f"ARR in {t} months if growth keeps decaying",
            lv * 12,
            ctx.currency,
            f"MRR {mrr.display} compounded {t} months where {rule}; × 12",
            [mrr, g_r, g_l],
            projection=True,
        )
        pts.append({"month": t, "arr": f.model_dump(mode="json")})
    end_arr = pts[-1]["arr"]
    g_end = derived(
        "redteam.decay_growth_m12",
        "Monthly growth after 12 more months of decay",
        path[-1][2],
        "pct",
        f"{pct(g_r.value)} × {r:.4f}^{HORIZON}",
        [g_r, g_l],
        projection=True,
    )
    flat = derived(
        "redteam.flat_arr_m12",
        "ARR in 12 months if recent growth simply holds",
        mrr.value * (1 + g_r.value) ** HORIZON * 12,
        ctx.currency,
        f"MRR {mrr.display} × (1 + {pct(g_r.value)})^{HORIZON} × 12",
        [mrr, g_r],
        projection=True,
    )
    res = out(mrr=mrr, cmgr_recent=g_r, cmgr_12m=g_l, growth_after_12m=g_end, arr_if_recent_growth_holds=flat)
    res["arr_after_12m"] = end_arr
    res["path"] = pts
    res["scenario"] = "Growth keeps decaying at the recent trend for 12 months"
    return res


def _largest_leaves(ctx: TruthContext) -> Result:
    share, mrr = get(ctx, "top_customer_share"), get(ctx, "mrr")
    miss = [f for f in (share, mrr) if isinstance(f, MissingFigure)]
    if miss:
        return out(miss)
    assert isinstance(share, Figure) and isinstance(mrr, Figure)
    lost = derived(
        "redteam.largest_customer_mrr",
        "MRR from the largest customer",
        share.value * mrr.value,
        ctx.currency,
        f"share {share.display} × MRR {mrr.display}",
        [share, mrr],
        period=mrr.period,
    )
    arr_after = derived(
        "redteam.arr_without_largest",
        "ARR if the largest customer leaves",
        (mrr.value - lost.value) * 12,
        ctx.currency,
        f"(MRR {mrr.display} − {lost.display}) × 12",
        [mrr, lost],
        projection=True,
    )
    parts: dict = {"top_customer_share": share, "mrr": mrr, "lost_mrr": lost, "arr_after": arr_after}
    miss_after: list[MissingFigure] = []
    g = fig(ctx, "cmgr_recent")
    if g is not None and share.value < 1:
        mo = months_to_reach(mrr.value - lost.value, mrr.value, g.value)
        if mo is not None:
            parts["months_to_recover"] = derived(
                "redteam.months_to_recover_largest",
                "Months of recent growth needed to replace the largest customer",
                mo,
                "months",
                f"ln({fmt(mrr.value, ctx.currency)} ÷ {fmt(mrr.value - lost.value, ctx.currency)}) ÷ ln(1 + {pct(g.value)})",
                [mrr, lost, g],
                projection=True,
            )
    burn, cash = fig(ctx, "burn"), fig(ctx, "cash_balance")
    gm = fig(ctx, "gross_margin_incl_cs") or fig(ctx, "gross_margin")
    if burn is not None:
        margin = gm.value if gm else 1.0
        burn_after = derived(
            "redteam.burn_without_largest",
            "Monthly burn if the largest customer leaves",
            burn.value + lost.value * margin,
            ctx.currency,
            f"burn {burn.display} + lost MRR {lost.display} × gross margin "
            f"{gm.display if gm else '100% (no margin figure, worst case)'}",
            [burn, lost] + ([gm] if gm else []),
            projection=True,
        )
        parts["burn_after"] = burn_after
        if cash is not None and burn_after.value > 0:
            parts["runway_after"] = derived(
                "redteam.runway_without_largest",
                "Runway if the largest customer leaves",
                cash.value / burn_after.value,
                "months",
                f"cash {cash.display} ÷ burn {burn_after.display}",
                [cash, burn_after],
                projection=True,
            )
        elif cash is None:
            cash_missing = get(ctx, "cash_balance")
            if isinstance(cash_missing, MissingFigure):
                miss_after.append(cash_missing)
    res = out(miss_after, **parts)
    res["scenario"] = "The largest customer leaves next month"
    return res


@tool(
    KIT,
    "redteam_stress",
    "Stress scenarios: growth keeps decaying at the recent CMGR trend for 12 months; the largest customer leaves. "
    "Returns forecast Figures: arr_after_12m, path[].arr, growth_after_12m, arr_if_recent_growth_holds; lost_mrr, "
    "arr_after, months_to_recover, burn_after, runway_after.",
    schema(
        scenario=enum(
            ["all", "growth_decay", "largest_customer_leaves"], "Which scenario to run; 'all' runs both"
        )
    ),
)
def stress(ctx: TruthContext, scenario: str) -> Result:
    runs = {"growth_decay": _growth_decay, "largest_customer_leaves": _largest_leaves}
    if scenario not in (*runs, "all"):
        raise ValueError("scenario must be one of all, growth_decay, largest_customer_leaves")
    names = list(runs) if scenario == "all" else [scenario]
    return {"scenarios": {n: runs[n](ctx) for n in names}}


PREFIXES = ("plan.", "plan_", "forecast.", "forecast_")
RATE_ALIASES = {
    "logo_churn_monthly": "logo_churn_rate",
    "revenue_churn_monthly": "revenue_churn_rate",
    "churn_monthly": "logo_churn_rate",
    "growth_monthly": "cmgr_recent",
    "mrr_growth_monthly": "cmgr_recent",
    "runway": "runway_months",
}
LOWER_IS_BETTER = {
    "logo_churn_rate",
    "revenue_churn_rate",
    "burn",
    "burn_incl_credits",
    "burn_multiple",
    "cac",
    "cac_payback_months",
    "top_customer_share",
}
REVENUE_LEVELS = {"mrr": "mrr", "arr": "arr", "revenue": "revenue", "revenue.total": "revenue"}
COUNT_LEVELS = {"customers.count", "customers", "headcount.total", "headcount"}
FLOW_LEVELS = {"revenue", "revenue.total"}
NOT_COMPARABLE = {"cash_balance", "net_income", "round_size"}  # plan values that include the raise itself
MAX_PER_METRIC = 2  # first and last plan period of each level metric


def _plan_name(name: str) -> str:
    for p in PREFIXES:
        if name.startswith(p):
            return name[len(p) :]
    return name


def _sort_key(f: Fact) -> tuple[int, int]:
    return period_sort_key(f.period) if f.period and PERIOD_RX.match(f.period) else (0, 0)


def _count_growth(ctx: TruthContext, field_id: str) -> Figure | MissingFigure:
    m = ctx.model
    pts = [cell_figure(ctx, field_id, p) for p in m.periods_with(field_id)] or fact_series(ctx, field_id)
    pts = [f for f in pts if f is not None and f.period and f.value > 0]
    fid = f"redteam.{field_id}_cmgr"
    label = f"Monthly growth in {field_id.split('.')[0]}, history"
    if len(pts) < 2:
        return missing(fid, label, [field_id], f"Needs {field_id} at two or more dates")
    last = pts[-1]
    first = next((f for f in pts if months_between(f.period, last.period) <= 12), pts[0])
    n = months_between(first.period, last.period)
    if n <= 0:
        return missing(fid, label, [field_id], "Needs counts at two different dates")
    return derived(
        fid,
        label,
        (last.value / first.value) ** (1 / n) - 1,
        "pct",
        f"({last.display} in {label_period(last.period)} ÷ {first.display} in {label_period(first.period)})^(1/{n}) − 1",
        [first, last],
        period=f"{first.period}..{last.period}",
    )


def _level_gaps(ctx: TruthContext, key: str, facts: list[Fact]) -> list[Result]:
    hist_l: Figure | MissingFigure | None = None
    if key in REVENUE_LEVELS:
        actual: Figure | MissingFigure | None = get(ctx, REVENUE_LEVELS[key])
        hist_g = recent_growth(ctx, "recent")
        hist_l = recent_growth(ctx, "l12m")
    else:
        field_id = "customers.count" if key.startswith("customers") else "headcount.total"
        actual = latest_count(ctx, field_id, field_id)
        hist_g = _count_growth(ctx, field_id)
    if not isinstance(actual, Figure) or not actual.period or not PERIOD_RX.match(actual.period):
        return []
    ahead = [
        f
        for f in facts
        if f.period and PERIOD_RX.match(f.period) and months_between(actual.period, f.period) > 0
    ]
    if not ahead:
        return []
    picks = [ahead[0]] + ([ahead[-1]] if len(ahead) > 1 else [])
    flow = key in FLOW_LEVELS
    a_eq = actual.value / ctx.model.months_per_period if flow else actual.value
    points = []
    for fact in picks[:MAX_PER_METRIC]:
        fc = fact_to_figure(ctx, fact, unit=actual.unit)
        n = months_between(actual.period, fact.period)
        p_eq = fact.value / period_months(fact.period) if flow else fact.value
        if a_eq <= 0 or p_eq <= 0:
            continue
        per = " (monthly equivalents)" if flow else ""
        implied = derived(
            f"redteam.plan_growth.{key}.{fact.period}",
            f"Monthly growth the plan needs to reach {fc.display}",
            (p_eq / a_eq) ** (1 / n) - 1,
            "pct",
            f"(plan {fc.display} in {label_period(fact.period)} ÷ actual {actual.display} in "
            f"{label_period(actual.period)}{per})^(1/{n}) − 1",
            [fc, actual],
            projection=True,
        )
        point: Result = {
            "forecast": fc.model_dump(mode="json"),
            "implied_growth": implied.model_dump(mode="json"),
        }
        for tag, g in (("recent", hist_g), ("l12m", hist_l)):
            if isinstance(g, Figure):
                point[f"gap_vs_{tag}"] = derived(
                    f"redteam.plan_growth_gap.{key}.{fact.period}.{tag}",
                    f"Plan growth minus {g.label.lower()}",
                    implied.value - g.value,
                    "pct",
                    f"{implied.display} − {g.display}",
                    [implied, g],
                    projection=True,
                ).model_dump(mode="json")
        if isinstance(hist_g, Figure) and not key.startswith("headcount"):
            point["plan_is_kinder"] = implied.value > hist_g.value
        points.append(point)
    if not points:
        return []
    item: Result = {
        "metric": key,
        "kind": "level",
        "history": actual.model_dump(mode="json"),
        "points": points,
    }
    for tag, g in (("recent", hist_g), ("l12m", hist_l)):
        if isinstance(g, Figure):
            item[f"history_growth_{tag}"] = g.model_dump(mode="json")
    return [item]


def _history_for(ctx: TruthContext, name: str) -> Figure | None:
    for cand in (FACT_ALIASES.get(name), RATE_ALIASES.get(name), name):
        if cand and isinstance(f := ctx.figures.get(cand), Figure) and f.kind != "forecast":
            return f
    for cand in (f"{name}_historical", name):
        series = live_facts(ctx, cand, forecast=False)
        if series:
            return fact_to_figure(ctx, series[-1])
    return None


def _compatible(a: str, b: str) -> bool:
    return a == b or (a in CURRENCIES and b in CURRENCIES)


@tool(
    KIT,
    "redteam_forecast_gaps",
    "Plan assumptions (facts of kind forecast) against history. Levels (MRR, ARR, revenue, customers, headcount): "
    "the monthly growth the plan needs vs historical growth. Rates (churn, ramp, margins): plan vs history. Returns "
    "Figures: forecast, history, implied_growth, gap_vs_recent / gap_vs_l12m, or gap (plan ÷ history − 1).",
)
def forecast_gaps(ctx: TruthContext) -> Result:
    plans: dict[str, list[Fact]] = {}
    for fact in ctx.facts:
        if fact.status != "removed" and fact.kind == "forecast":
            plans.setdefault(_plan_name(fact.name), []).append(fact)
    if not plans:
        return out(
            [
                missing(
                    "redteam.forecast_gaps",
                    "Plan vs history",
                    ["forecast / plan facts"],
                    "No plan or forecast figures in the source of truth; upload the financial plan to compare",
                )
            ]
        )
    levels, rates, unmatched = [], [], []
    for key, facts in plans.items():
        facts.sort(key=_sort_key)
        if key in REVENUE_LEVELS or key in COUNT_LEVELS:
            got = _level_gaps(ctx, key, facts)
            levels += got
            if not got:
                unmatched.append(key)
            continue
        if key in NOT_COMPARABLE:
            unmatched.append(key)
            continue
        hist = _history_for(ctx, key)
        fact = facts[-1]
        if hist is None or not hist.value:
            unmatched.append(key)
            continue
        value = normalize_value(fact.value, fact.unit, hist.unit)
        unit = fact.unit if fact.unit in UNITS else hist.unit
        if not _compatible(unit, hist.unit):
            unmatched.append(key)
            continue
        fc = fact_to_figure(ctx, fact, unit=hist.unit, value=value)
        gap = derived(
            f"redteam.gap.{key}",
            f"Plan vs history: {fact.label or key}",
            value / hist.value - 1,
            "pct",
            f"plan {fc.display} ÷ history {hist.display} − 1",
            [fc, hist],
            projection=True,
        )
        item: Result = {
            "metric": key,
            "kind": "rate",
            "forecast": fc.model_dump(mode="json"),
            "history": hist.model_dump(mode="json"),
            "gap": gap.model_dump(mode="json"),
        }
        hist_id = RATE_ALIASES.get(key) or FACT_ALIASES.get(key) or hist.id
        if hist_id in LOWER_IS_BETTER or key.endswith(("_ramp_months", "churn_monthly")):
            item["plan_is_kinder"] = value < hist.value
        rates.append(item)
    return {"levels": levels, "rates": rates, "unmatched_plan_items": sorted(set(unmatched))}


RED_TEAM = Kit(KIT, "Pre-mortem stress tests and plan-vs-history gaps.", [stress, forecast_gaps])
