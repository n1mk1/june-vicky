"""Product: how much of the revenue is services, and where custom work shows up."""

from statistics import median

from vicky.areopagus.kits._base import (
    Kit,
    Result,
    cell_figure,
    derived,
    dumps,
    get,
    missing,
    out,
    sum_figure,
    tool,
    window_label,
)
from vicky.model.context import TruthContext
from vicky.model.metrics import label_period

KIT = "Product"
SPIKE = 2.0  # a period's one-time revenue at 2× or more of its typical (median) level


def _split_periods(ctx: TruthContext) -> list[str]:
    m = ctx.model
    return [p for p in m.periods_with("revenue.one_time") if m.value("revenue.total", p)]


@tool(
    KIT,
    "product_services_share",
    "Services / one-time share of total revenue by period (last 12) and its trend: the latest 12 months against "
    "the 12 before (or the two halves of the window). Returns Figures: share_by_period[], share_recent, "
    "share_earlier, change.",
)
def services_share(ctx: TruthContext) -> Result:
    m = ctx.model
    ps = _split_periods(ctx)
    if not ps:
        return out(
            [
                missing(
                    "product.services_share",
                    "Services share of revenue",
                    ["revenue.one_time"],
                    "The data doesn't split services or one-time revenue from recurring revenue",
                )
            ]
        )
    by_period = []
    for p in ps[-max(1, 12 // m.months_per_period) :]:
        one, tot = cell_figure(ctx, "revenue.one_time", p), cell_figure(ctx, "revenue.total", p)
        by_period.append(
            derived(
                f"product.services_share.{p}",
                f"Services share of revenue, {label_period(p)}",
                one.value / tot.value,
                "pct",
                f"one-time {one.display} ÷ total {tot.display}",
                [one, tot],
                period=p,
            )
        )
    step = 12 // m.months_per_period
    if len(ps) >= 2 * step:
        recent, earlier = ps[-step:], ps[-2 * step : -step]
    else:
        half = len(ps) // 2
        recent, earlier = ps[half:], ps[:half]
    res: Result = {"share_by_period": dumps(by_period)}
    if earlier and recent:
        shares = []
        for tag, win in (("recent", recent), ("earlier", earlier)):
            one = sum_figure(
                ctx,
                "revenue.one_time",
                win,
                f"product.one_time_{tag}",
                f"One-time revenue, {window_label(win)}",
            )
            tot = sum_figure(
                ctx, "revenue.total", win, f"product.revenue_{tag}", f"Total revenue, {window_label(win)}"
            )
            s = derived(
                f"product.services_share_{tag}",
                f"Services share of revenue, {window_label(win)}",
                one.value / tot.value,
                "pct",
                f"one-time {one.display} ÷ total {tot.display}",
                [one, tot],
                period=f"{win[0]}..{win[-1]}",
            )
            res[f"share_{tag}"] = s.model_dump(mode="json")
            shares.append(s)
        ch = derived(
            "product.services_share_change",
            "Change in services share (points)",
            shares[0].value - shares[1].value,
            "pct",
            f"{shares[0].display} − {shares[1].display}",
            shares,
        )
        res["change"] = ch.model_dump(mode="json")
        res["trend"] = "rising" if ch.value > 0.01 else "falling" if ch.value < -0.01 else "flat"
    return res


@tool(
    KIT,
    "product_custom_work_signals",
    "Custom-work signals: periods where one-time revenue spikes to 2x or more of its median, plus the R&D share of "
    "opex. Returns Figures: median_one_time, spikes[].amount and spikes[].multiple, opex_share_r_and_d.",
)
def custom_work_signals(ctx: TruthContext) -> Result:
    m = ctx.model
    rd = get(ctx, "opex_share_r_and_d")
    ps = [p for p in m.periods_with("revenue.one_time") if (m.value("revenue.one_time", p) or 0) > 0]
    if len(ps) < 3:
        return out(
            [
                missing(
                    "product.custom_work",
                    "Custom-work signals",
                    ["revenue.one_time (3+ periods with values)"],
                    "Needs one-time / services revenue over several periods to spot spikes",
                )
            ],
            opex_share_r_and_d=rd,
        )
    values = [m.value("revenue.one_time", p) for p in ps]
    med = median(values)
    figs = [cell_figure(ctx, "revenue.one_time", p) for p in ps]
    medf = derived(
        "product.median_one_time",
        "Typical (median) one-time revenue in periods that have any",
        med,
        ctx.currency,
        f"median of {len(ps)} periods with one-time revenue, {window_label(ps)}",
        figs,
    )
    spikes = []
    for f in figs:
        if med > 0 and f.value >= SPIKE * med:
            mult = derived(
                f"product.spike_multiple.{f.period}",
                f"One-time revenue vs median, {label_period(f.period)}",
                f.value / med,
                "x",
                f"{f.display} ÷ median {medf.display}",
                [f, medf],
                period=f.period,
            )
            spikes.append(
                {
                    "period": f.period,
                    "amount": f.model_dump(mode="json"),
                    "multiple": mult.model_dump(mode="json"),
                }
            )
    res = out(median_one_time=medf, opex_share_r_and_d=rd)
    res["spikes"] = spikes
    res["reading"] = (
        (
            "Spikes can mean custom builds or large onboarding projects for one customer; ask what was built, "
            "for whom, and whether it shipped to everyone."
        )
        if spikes
        else "No one-time revenue spikes at 2x the median."
    )
    return res


PRODUCT = Kit(KIT, "Services revenue share and custom-work signals.", [services_share, custom_work_signals])
