"""Customer: who pays, how concentrated it is, and who left."""

from vik.areopagus.kits._base import (
    Kit,
    Result,
    cell_figure,
    derived,
    dumps,
    fact_series,
    get,
    missing,
    out,
    table_source,
    tool,
)
from vik.model.context import TruthContext
from vik.model.figures import Figure
from vik.model.loader import period_sort_key
from vik.model.metrics import label_period

KIT = "Customer"
TOP_N = 5


def _table_figure(
    ctx: TruthContext, fid: str, label: str, value: float, unit: str, formula: str, refstr: str, period: str
) -> Figure:
    return Figure(
        id=fid,
        label=label,
        value=value,
        unit=unit,
        formula=formula,
        source=table_source(ctx, "customer_mrr", refstr),
        period=period,
        group="kits",
    )


@tool(
    KIT,
    "customer_concentration",
    "Revenue concentration from the per-customer MRR table. Returns Figures: top_customer_share, total_mrr, "
    "customers_in_table, top3_share, top5_share, and the top customers each with mrr and share Figures.",
)
def concentration(ctx: TruthContext) -> Result:
    m = ctx.model
    parts: dict = {"top_customer_share": get(ctx, "top_customer_share")}
    if not m.customer_mrr:
        return out(
            [
                missing(
                    "customer.mrr_table",
                    "Per-customer MRR",
                    ["customer_mrr"],
                    "Upload MRR by customer for the latest period to see concentration",
                )
            ],
            **parts,
        )
    p = sorted(m.customer_mrr, key=period_sort_key)[-1]
    by_c = sorted(((c, v) for c, v in m.customer_mrr[p].items() if v > 0), key=lambda kv: -kv[1])
    total = sum(v for _, v in by_c)
    if total <= 0:
        return out(
            [
                missing(
                    "customer.mrr_table", "Per-customer MRR", ["customer_mrr"], "Customer MRR sums to zero"
                )
            ],
            **parts,
        )
    where = f"customer table · {label_period(p)}"
    tot = _table_figure(
        ctx,
        "customer.total_mrr",
        f"MRR across customers, {label_period(p)}",
        total,
        ctx.currency,
        f"Sum of {len(by_c)} customers' MRR in {label_period(p)}",
        where,
        p,
    )
    count = _table_figure(
        ctx,
        "customer.count_in_table",
        f"Customers with MRR, {label_period(p)}",
        float(len(by_c)),
        "count",
        f"Customers with positive MRR in {label_period(p)}",
        where,
        p,
    )
    parts.update(total_mrr=tot, customers_in_table=count)
    for n in (3, 5):
        if len(by_c) > n:
            top = sum(v for _, v in by_c[:n])
            parts[f"top{n}_share"] = derived(
                f"customer.top{n}_share",
                f"Top {n} customers' share of MRR",
                top / total,
                "pct",
                f"top {n} customers' MRR {top:,.0f} ÷ total {total:,.0f}",
                [tot],
                period=p,
            )
    top_list = []
    for i, (name, v) in enumerate(by_c[:TOP_N], start=1):
        mrr = _table_figure(
            ctx,
            f"customer.rank{i}_mrr",
            f"MRR of customer #{i} ({name})",
            v,
            ctx.currency,
            f"{name} MRR in {label_period(p)}",
            f"{where} · {name}",
            p,
        )
        share = derived(
            f"customer.rank{i}_share",
            f"{name}'s share of MRR",
            v / total,
            "pct",
            f"{mrr.display} ÷ total {tot.display}",
            [mrr, tot],
            period=p,
        )
        top_list.append(
            {"customer": name, "mrr": mrr.model_dump(mode="json"), "share": share.model_dump(mode="json")}
        )
    res = out(**parts)
    res["top_customers"] = top_list
    return res


@tool(
    KIT,
    "customer_churn_events",
    "Churn events: churned-customer counts by period and customers whose MRR dropped to zero between the last two "
    "periods of the customer table. Returns Figures: logo_churn_rate, churned_by_period[], lost_customers[].lost_mrr.",
)
def churn_events(ctx: TruthContext) -> Result:
    m = ctx.model
    parts: dict = {"logo_churn_rate": get(ctx, "logo_churn_rate")}
    churned = [
        f
        for p in m.periods_with("customers.churned")[-12:]
        if (f := cell_figure(ctx, "customers.churned", p)) and f.value > 0
    ]
    if not churned:
        churned = [f for f in fact_series(ctx, "customers.churned")[-12:] if f.value > 0]
    lost = []
    periods = sorted(m.customer_mrr, key=period_sort_key)
    if len(periods) >= 2:
        a, b = periods[-2], periods[-1]
        for name, v in sorted(m.customer_mrr[a].items(), key=lambda kv: -kv[1]):
            if v > 0 and not m.customer_mrr[b].get(name):
                f = _table_figure(
                    ctx,
                    f"customer.lost.{name}",
                    f"MRR lost when {name} left",
                    v,
                    ctx.currency,
                    f"{name} MRR in {label_period(a)}, absent or zero in {label_period(b)}",
                    f"customer table · {label_period(a)}–{label_period(b)} · {name}",
                    b,
                )
                lost.append({"customer": name, "left_in": b, "lost_mrr": f.model_dump(mode="json")})
    res = out(**parts)
    if churned:
        res["churned_by_period"] = dumps(churned)
    if lost:
        res["lost_customers"] = lost
    if not churned and not lost:
        res.setdefault("missing", []).append(
            missing(
                "customer.churn_events",
                "Churn events",
                ["customers.churned", "customer_mrr (two or more periods)"],
                "Add churned-customer counts or per-customer MRR over time to see who left and when",
            ).model_dump(mode="json")
        )
    return res


@tool(
    KIT,
    "customer_count_trend",
    "Customer count over the last 12 periods with new and churned customers. Returns Figures: customers[], "
    "new_customers[], churned_customers[], change (latest minus first), change_pct.",
)
def count_trend(ctx: TruthContext) -> Result:
    m = ctx.model
    ps = m.periods_with("customers.count")[-12:]
    if ps:
        counts = [cell_figure(ctx, "customers.count", p) for p in ps]
        flows = {
            k: [f for p in ps if (f := cell_figure(ctx, k, p))]
            for k in ("customers.new", "customers.churned")
        }
    else:
        counts = fact_series(ctx, "customers.count")[-12:]
        flows = {k: fact_series(ctx, k)[-12:] for k in ("customers.new", "customers.churned")}
    if not counts:
        return out(
            [
                missing(
                    "customers.count",
                    "Customers",
                    ["customers.count"],
                    "Add customer counts by period to see the trend",
                )
            ]
        )
    res: Result = {"customers": dumps(counts)}
    for key, field_id in (("new_customers", "customers.new"), ("churned_customers", "customers.churned")):
        if flows[field_id]:
            res[key] = dumps(flows[field_id])
    first, last = counts[0], counts[-1]
    ps = [f.period or "" for f in counts]
    if len(counts) > 1:
        ch = derived(
            "customer.count_change",
            f"Change in customers, {label_period(ps[0])} → {label_period(ps[-1])}",
            last.value - first.value,
            "count",
            f"{last.display} − {first.display}",
            [last, first],
            period=ps[-1],
        )
        res["change"] = ch.model_dump(mode="json")
        if first.value > 0:
            res["change_pct"] = derived(
                "customer.count_change_pct",
                "Customer growth over the window",
                last.value / first.value - 1,
                "pct",
                f"{last.display} ÷ {first.display} − 1",
                [last, first],
                period=ps[-1],
            ).model_dump(mode="json")
    return res


CUSTOMER = Kit(
    KIT,
    "Concentration, churn events and customer count trend from customer-level data.",
    [concentration, churn_events, count_trend],
)
