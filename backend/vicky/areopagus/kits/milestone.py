"""Milestone: what the round buys in months, and where ARR lands by then (projections)."""

from vicky.areopagus.kits._base import (
    Kit,
    Result,
    derived,
    fact_to_figure,
    fig,
    fmt,
    founder_figure,
    get,
    integer,
    missing,
    months_to_reach,
    num,
    opt_num,
    out,
    pct,
    pct_arg,
    profile_figure,
    recent_growth,
    schema,
    tool,
)
from vicky.model.context import TruthContext
from vicky.model.figures import Figure, MissingFigure

KIT = "Milestone"
LONG_HORIZON = 36
CURRENCIES = {"cad", "usd", "gbp", "eur", "aud"}


def _round(ctx: TruthContext, round_size: float | None) -> Figure | MissingFigure:
    if round_size is not None and round_size > 0:
        return founder_figure("milestone.round_size", "Round size", round_size, ctx.currency)
    return profile_figure(ctx, "round_size", "Round size", ctx.currency) or missing(
        "milestone.round_size",
        "Round size",
        ["round_size"],
        "No round size in the profile or facts; ask the founder",
    )


def _arr_or_run_rate(ctx: TruthContext) -> Figure | MissingFigure:
    arr = get(ctx, "arr")
    if isinstance(arr, Figure):
        return arr
    rev = fig(ctx, "revenue")
    if rev is None:
        return arr
    k = 12 // ctx.model.months_per_period
    return derived(
        "milestone.revenue_run_rate",
        "Revenue run rate",
        rev.value * k,
        ctx.currency,
        f"latest-period revenue {rev.display} × {k}",
        [rev],
        period=rev.period,
    )


@tool(
    KIT,
    "milestone_use_of_funds",
    "Months the round buys at current burn and at a higher burn, with and without today's cash, and ARR at the end of "
    "that runway if recent monthly growth holds (projection). Returns Figures: round_size, burn, months_current_burn, "
    "months_higher_burn, total_runway_*, arr_at_runway_end_*.",
    schema(
        round_size=opt_num("Round size the founder states; null to use the company profile"),
        burn_increase_pct=num(
            "Percent increase in monthly burn after the raise, e.g. 50 for a hiring plan; 0 for none"
        ),
    ),
)
def use_of_funds(ctx: TruthContext, round_size: float | None, burn_increase_pct: float) -> Result:
    up = pct_arg(burn_increase_pct, "burn_increase_pct")
    if up < 0:
        raise ValueError("burn_increase_pct must be ≥ 0")
    rnd, burn, cash = _round(ctx, round_size), get(ctx, "burn"), fig(ctx, "cash_balance")
    parts: dict = {"round_size": rnd, "burn": burn}
    miss: list[MissingFigure] = []
    if isinstance(burn, Figure) and burn.value <= 0:
        miss.append(
            missing(
                "milestone.months",
                "Months the round buys",
                ["net_income"],
                "The company is not burning cash, so the round's months don't apply",
            )
        )
        return out(miss, **parts)
    if not isinstance(rnd, Figure) or not isinstance(burn, Figure):
        return out(miss, **parts)
    if cash is None:
        cm = get(ctx, "cash_balance")
        if isinstance(cm, MissingFigure):
            miss.append(cm)
    else:
        parts["cash_balance"] = cash
    arr, g = _arr_or_run_rate(ctx), recent_growth(ctx, "recent")
    for m in (arr, g):
        if isinstance(m, MissingFigure):
            miss.append(m)
    scenarios = [("current_burn", 1.0, "at current burn")]
    if up > 0:
        scenarios.append(("higher_burn", 1 + up, f"at burn +{burn_increase_pct:g}%"))
    for key, factor, words in scenarios:
        b = burn.value * factor
        bdesc = f"burn {burn.display}" + (f" × {factor:g} = {fmt(b, ctx.currency)}" if factor != 1 else "")
        months = derived(
            f"milestone.months_{key}",
            f"Months the round buys {words}",
            rnd.value / b,
            "months",
            f"round {rnd.display} ÷ {bdesc}",
            [rnd, burn],
            projection=True,
        )
        parts[f"months_{key}"] = months
        horizon = months
        if cash is not None:
            horizon = derived(
                f"milestone.total_runway_{key}",
                f"Runway with today's cash plus the round, {words}",
                (cash.value + rnd.value) / b,
                "months",
                f"(cash {cash.display} + round {rnd.display}) ÷ {bdesc}",
                [cash, rnd, burn],
                projection=True,
            )
            parts[f"total_runway_{key}"] = horizon
        if isinstance(arr, Figure) and isinstance(g, Figure):
            parts[f"arr_at_runway_end_{key}"] = derived(
                f"milestone.arr_at_runway_end_{key}",
                f"{arr.label} at the end of that runway if recent growth holds",
                arr.value * (1 + g.value) ** horizon.value,
                ctx.currency,
                f"{arr.display} × (1 + {pct(g.value)})^{horizon.value:.1f} months",
                [arr, g, horizon],
                projection=True,
            )
    if isinstance(arr, Figure):
        parts["arr"] = arr
    if isinstance(g, Figure):
        parts["growth"] = g
    res = out(miss, **parts)
    uses = _use_of_funds(ctx, rnd)
    if uses:
        res["use_of_funds"] = uses
    notes = []
    if cash is None:
        notes.append("No cash balance in the data: months shown are the round alone, not total runway.")
    if rnd.value / burn.value > LONG_HORIZON:
        notes.append(
            f"Today's burn stretches the round past {LONG_HORIZON} months; compounding recent growth that long is "
            "a mechanical extrapolation. Test the post-raise burn with burn_increase_pct."
        )
    if notes:
        res["notes"] = notes
    return res


def _use_of_funds(ctx: TruthContext, rnd: Figure) -> list[dict]:
    """Use-of-funds lines from the facts (names containing 'use_of_funds'), each with its share of the round."""
    out_ = []
    for f in ctx.facts:
        if f.status == "removed" or "use_of_funds" not in f.name or f.unit not in CURRENCIES:
            continue
        line = fact_to_figure(ctx, f)
        share = derived(
            f"milestone.share.{f.name}",
            f"{line.label}: share of the round",
            line.value / rnd.value,
            "pct",
            f"{line.display} ÷ round {rnd.display}",
            [line, rnd],
        )
        out_.append({"line": line.model_dump(mode="json"), "share_of_round": share.model_dump(mode="json")})
    return out_


@tool(
    KIT,
    "milestone_arr_projection",
    "ARR after N months at the recent and the 12-month monthly growth rate, and months to reach a target ARR the "
    "founder names (projections). Returns Figures: arr, arr_at_horizon_recent, arr_at_horizon_12m, "
    "months_to_target_recent, months_to_target_12m.",
    schema(
        months=integer("Projection horizon in months, e.g. 18"),
        target_arr=opt_num("Target ARR the founder names (e.g. for the next round); null for none"),
    ),
)
def arr_projection(ctx: TruthContext, months: int, target_arr: float | None) -> Result:
    if not isinstance(months, int | float) or months <= 0 or months > 120:
        raise ValueError("months must be between 1 and 120")
    arr = _arr_or_run_rate(ctx)
    if isinstance(arr, MissingFigure):
        return out([arr])
    horizon = founder_figure(
        "milestone.horizon",
        "Projection horizon",
        float(months),
        "months",
        where="horizon requested in this session",
    )
    parts: dict = {"arr": arr, "horizon": horizon}
    miss: list[MissingFigure] = []
    target = (
        founder_figure("milestone.target_arr", "Target ARR", target_arr, ctx.currency)
        if target_arr and target_arr > 0
        else None
    )
    if target is not None:
        parts["target_arr"] = target
    for basis in ("recent", "12m"):
        g = recent_growth(ctx, "recent" if basis == "recent" else "l12m")
        if isinstance(g, MissingFigure):
            miss.append(g)
            continue
        parts[f"growth_{basis}"] = g
        parts[f"arr_at_horizon_{basis}"] = derived(
            f"milestone.arr_m{int(months)}_{basis}",
            f"{arr.label} in {int(months)} months at {g.label.lower()}",
            arr.value * (1 + g.value) ** months,
            ctx.currency,
            f"{arr.display} × (1 + {pct(g.value)})^{int(months)}",
            [arr, g, horizon],
            projection=True,
        )
        if target is not None:
            mo = months_to_reach(arr.value, target.value, g.value)
            if mo is not None:
                parts[f"months_to_target_{basis}"] = derived(
                    f"milestone.months_to_target_{basis}",
                    f"Months to {target.display} at {g.label.lower()}",
                    mo,
                    "months",
                    f"ln({target.display} ÷ {arr.display}) ÷ ln(1 + {pct(g.value)})",
                    [target, arr, g],
                    projection=True,
                )
            else:
                miss.append(
                    missing(
                        f"milestone.months_to_target_{basis}",
                        "Months to target",
                        ["positive growth", "target above today's ARR"],
                        "Growth is not positive or the target is not above today's figure",
                    )
                )
    return out(miss, **parts)


MILESTONE = Kit(
    KIT,
    "Use of funds: months the round buys, and ARR at the end of runway (projections).",
    [use_of_funds, arr_projection],
)
