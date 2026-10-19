"""Terms: ownership and waterfall arithmetic on numbers the founder supplies. Never a valuation view.

Conventions (match `data/playbooks/term-sheets.md`):
- Priced round: post-money = pre-money + new money. The pre-money is fully diluted and includes
  converting SAFEs and the option pool target (the pool "shuffle": the new pool dilutes only
  holders before the round). SAFEs with a post-money cap convert at cap ÷ the capitalization
  before new money (existing shares + all capped SAFE shares), or at the round price if that is
  lower; SAFEs without a cap convert at the round price.
- Post-money SAFE round: each SAFE owns amount ÷ its post-money cap; an option pool increase
  counted in the capitalization dilutes only existing holders.
"""

import re

from vik.areopagus.kits._base import (
    Kit,
    Result,
    boolean,
    derived,
    dump,
    enum,
    fact_to_figure,
    fmt,
    founder_figure,
    missing,
    num,
    opt_num,
    pct,
    pct_arg,
    schema,
    tool,
)
from vik.model.context import TruthContext
from vik.model.figures import Figure

KIT = "Terms"
NOTE = "Arithmetic on the founder's own inputs. It is not a view on what the valuation or terms should be."


def _num_list(xs, name: str) -> list[float | None]:
    if not isinstance(xs, list):
        raise ValueError(f"{name} must be a list")
    out = []
    for x in xs:
        if x is None:
            out.append(None)
        elif isinstance(x, int | float) and not isinstance(x, bool) and x >= 0:
            out.append(float(x))
        else:
            raise ValueError(f"{name} entries must be non-negative numbers or null")
    return out


def priced_round(
    round_size: float, pre_money: float, pool: float, safes: list[tuple[float, float | None]]
) -> dict:
    """Ownership fractions after a priced round. Existing holders are normalized to 1 unit of shares."""
    post = pre_money + round_size
    capped = [i for i, (_, c) in enumerate(safes) if c]
    while True:
        f = sum(safes[i][0] / safes[i][1] for i in capped)  # type: ignore[operator]
        if f >= 1:
            raise ValueError(
                "capped SAFEs would own 100% or more before the round; check the amounts and caps"
            )
        cap_base = 1 / (1 - f)  # existing shares + capped SAFE shares
        uncapped = sum(a for i, (a, _) in enumerate(safes) if i not in capped)
        price = (pre_money - uncapped - pool * post) / cap_base
        if price <= 0:
            raise ValueError(
                "the pre-money is too small to hold the option pool and the SAFEs converting at the round price"
            )
        worse = [i for i in capped if safes[i][1] / cap_base > price]  # type: ignore[operator]
        if not worse:
            break
        capped = [i for i in capped if i not in worse]
    total = post / price
    shares = [
        (a / s_cap) * cap_base if i in capped and s_cap else a / price for i, (a, s_cap) in enumerate(safes)
    ]
    return {
        "existing": 1 / total,
        "safes": [s / total for s in shares],
        "investor": round_size / post,
        "pool": pool,
        "post": post,
        "converted_at_cap": [i in capped for i in range(len(safes))],
    }


def safe_round(round_size: float, cap: float, pool: float, safes: list[tuple[float, float | None]]) -> dict:
    owns = [a / (c or cap) for a, c in safes]
    new = round_size / cap
    existing = 1 - sum(owns) - new - pool
    if existing <= 0:
        raise ValueError("the SAFEs and pool would own 100% or more; check the amounts and caps")
    return {"existing": existing, "safes": owns, "investor": new, "pool": pool, "post": cap}


@tool(
    KIT,
    "terms_dilution",
    "Computes the ownership outcome of round numbers the founder supplies (round size, pre-money or SAFE cap, option "
    "pool, outstanding SAFEs); it never proposes or judges a valuation. Returns forecast Figures: ownership of "
    "existing holders, new investor, each SAFE and the pool, dilution of existing holders, implied post-money.",
    schema(
        instrument=enum(["priced_round", "post_money_safe"], "Round instrument"),
        round_size=num("New money in this round, in the company currency"),
        pre_money_or_cap=num(
            "Pre-money valuation for a priced round, or the post-money cap for a SAFE round, as the founder states it"
        ),
        option_pool_pct=num(
            "New or top-up option pool created for this round, percent of post-money (e.g. 10); 0 for none"
        ),
        safe_amounts={
            "type": "array",
            "items": {"type": "number"},
            "description": "Outstanding SAFE investments; [] if none",
        },
        safe_caps={
            "type": "array",
            "items": {"anyOf": [{"type": "number"}, {"type": "null"}]},
            "description": "Post-money cap per SAFE in the same order (null = no cap); [] for none",
        },
    ),
)
def dilution(
    ctx: TruthContext,
    instrument: str,
    round_size: float,
    pre_money_or_cap: float,
    option_pool_pct: float,
    safe_amounts: list,
    safe_caps: list,
) -> Result:
    if instrument not in ("priced_round", "post_money_safe"):
        raise ValueError("instrument must be priced_round or post_money_safe")
    if round_size < 0 or pre_money_or_cap <= 0:
        raise ValueError("round_size must be ≥ 0 and pre_money_or_cap > 0")
    pool = pct_arg(option_pool_pct, "option_pool_pct")
    if not 0 <= pool < 1:
        raise ValueError("option_pool_pct must be between 0 and 100")
    amounts = [a or 0.0 for a in _num_list(safe_amounts, "safe_amounts")]
    caps = _num_list(safe_caps, "safe_caps")
    if caps and len(caps) != len(amounts):
        raise ValueError("safe_caps must be empty or have one entry per SAFE")
    caps = caps or [None] * len(amounts)
    safes = list(zip(amounts, caps, strict=True))
    cur = ctx.currency
    r = (priced_round if instrument == "priced_round" else safe_round)(
        round_size, pre_money_or_cap, pool, safes
    )

    rs = founder_figure("terms.round_size", "Round size", round_size, cur)
    pm = founder_figure(
        "terms.pre_money_or_cap",
        "Pre-money" if instrument == "priced_round" else "SAFE post-money cap",
        pre_money_or_cap,
        cur,
    )
    pl = founder_figure("terms.option_pool", "New option pool", pool, "pct")
    ins = (
        [rs, pm, pl]
        + [
            founder_figure(f"terms.safe{i + 1}_amount", f"SAFE {i + 1} amount", a, cur)
            for i, a in enumerate(amounts)
        ]
        + [
            founder_figure(f"terms.safe{i + 1}_cap", f"SAFE {i + 1} post-money cap", c, cur)
            for i, c in enumerate(caps)
            if c
        ]
    )
    safe_desc = (
        ", ".join(f"{fmt(a, cur)}" + (f" capped at {fmt(c, cur)}" if c else " uncapped") for a, c in safes)
        or "none"
    )
    basis = (
        f"priced round: {fmt(round_size, cur)} on {fmt(pre_money_or_cap, cur)} pre-money "
        f"(post {fmt(r['post'], cur)}), pool {pct(pool)} of post created pre-money, SAFEs: {safe_desc}"
        if instrument == "priced_round"
        else f"post-money SAFE round: {fmt(round_size, cur)} at a {fmt(pre_money_or_cap, cur)} post-money cap, "
        f"pool {pct(pool)}, earlier SAFEs: {safe_desc}"
    )

    def own(fid: str, label: str, value: float, how: str) -> dict:
        return dump(derived(f"terms.{fid}", label, value, "pct", f"{how}; {basis}", ins, projection=True))

    res: Result = {
        "instrument": instrument,
        "inputs": [dump(f) for f in ins],
        "existing_holders": own(
            "existing_after",
            "Existing holders after the round",
            r["existing"],
            "100% minus everyone else's share",
        ),
        "new_investor": own(
            "new_investor",
            "New investor ownership" if instrument == "priced_round" else "New SAFE ownership",
            r["investor"],
            f"{fmt(round_size, cur)} ÷ {fmt(r['post'], cur)}",
        ),
        "option_pool": own(
            "option_pool_after", "New option pool after the round", r["pool"], "pool as given"
        ),
        "dilution_existing": own(
            "dilution_existing",
            "Dilution of existing holders",
            1 - r["existing"],
            "1 − existing holders' share after the round",
        ),
        "safes": [
            own(
                f"safe{i + 1}_after",
                f"SAFE {i + 1} ownership after the round",
                v,
                f"SAFE {i + 1} {fmt(safes[i][0], cur)}"
                + (
                    f" ÷ {fmt(safes[i][1] or pre_money_or_cap, cur)} cap"
                    if instrument == "post_money_safe"
                    else (
                        " converting at the cap price"
                        if r["converted_at_cap"][i]
                        else " converting at the round price"
                    )
                ),
            )
            for i, v in enumerate(r["safes"])
        ],
        "implied_post_money": dump(
            derived(
                "terms.post_money",
                "Post-money implied by the founder's inputs",
                r["post"],
                cur,
                f"{fmt(pre_money_or_cap, cur)} + {fmt(round_size, cur)}"
                if instrument == "priced_round"
                else "the post-money cap as given",
                ins,
                projection=True,
            )
        ),
        "note": NOTE,
    }
    return res


@tool(
    KIT,
    "terms_waterfall",
    "Computes who gets what at an exit value the founder or panel supplies, for one preferred investor with a "
    "liquidation preference; never judges the terms. Returns forecast Figures: investor_proceeds, common_proceeds, "
    "investor_share_of_exit, and whether the investor converts.",
    schema(
        exit_value=num("Sale price of the company to test, in the company currency"),
        invested=num("Amount the preferred investor put in"),
        investor_ownership_pct=num("Investor's as-converted ownership, percent (e.g. 20)"),
        liquidation_multiple=num("Preference multiple, e.g. 1 for 1x"),
        participating=boolean("True if the preference is participating (double dip)"),
        participation_cap_multiple=opt_num(
            "Cap on participating proceeds as a multiple of invested; null for no cap"
        ),
    ),
)
def waterfall(
    ctx: TruthContext,
    exit_value: float,
    invested: float,
    investor_ownership_pct: float,
    liquidation_multiple: float,
    participating: bool,
    participation_cap_multiple: float | None,
) -> Result:
    if exit_value < 0 or invested < 0 or liquidation_multiple < 0:
        raise ValueError("exit_value, invested and liquidation_multiple must be ≥ 0")
    own = pct_arg(investor_ownership_pct, "investor_ownership_pct")
    if not 0 <= own <= 1:
        raise ValueError("investor_ownership_pct must be between 0 and 100")
    cur = ctx.currency
    pref = min(exit_value, invested * liquidation_multiple)
    as_converted = own * exit_value
    if participating:
        take = pref + own * (exit_value - pref)
        if participation_cap_multiple:
            take = min(take, invested * participation_cap_multiple)
        converts = as_converted > take
        investor = max(take, as_converted)
        how = (
            f"participating: preference {fmt(pref, cur)} + {pct(own)} × ({fmt(exit_value, cur)} − {fmt(pref, cur)})"
            + (
                f", capped at {participation_cap_multiple:g}x {fmt(invested, cur)}"
                if participation_cap_multiple
                else ""
            )
            + f"; or convert for {pct(own)} × exit = {fmt(as_converted, cur)}, whichever is more"
        )
    else:
        converts = as_converted > pref
        investor = max(pref, as_converted)
        how = (
            f"non-participating: greater of preference {liquidation_multiple:g}x {fmt(invested, cur)} "
            f"(limited to the exit) = {fmt(pref, cur)} or {pct(own)} × {fmt(exit_value, cur)} = {fmt(as_converted, cur)}"
        )
    ins: list[Figure] = [
        founder_figure("terms.exit_value", "Exit value tested", exit_value, cur),
        founder_figure("terms.invested", "Preferred investment", invested, cur),
        founder_figure("terms.investor_ownership", "Investor as-converted ownership", own, "pct"),
        founder_figure(
            "terms.liquidation_multiple", "Liquidation preference multiple", liquidation_multiple, "x"
        ),
    ]
    inv = derived(
        "terms.investor_proceeds", "Investor proceeds at this exit", investor, cur, how, ins, projection=True
    )
    com = derived(
        "terms.common_proceeds",
        "Proceeds to everyone else at this exit",
        exit_value - investor,
        cur,
        f"exit {fmt(exit_value, cur)} − investor {inv.display}",
        [ins[0], inv],
        projection=True,
    )
    res: Result = {
        "inputs": [dump(f) for f in ins],
        "investor_proceeds": dump(inv),
        "common_proceeds": dump(com),
        "investor_converts": converts,
        "participating": participating,
        "note": NOTE,
    }
    if exit_value > 0:
        res["investor_share_of_exit"] = dump(
            derived(
                "terms.investor_share_of_exit",
                "Investor share of the exit",
                investor / exit_value,
                "pct",
                f"{inv.display} ÷ {fmt(exit_value, cur)}",
                [inv, ins[0]],
                projection=True,
            )
        )
    return res


CAP_TABLE = re.compile(r"^(safe|cap_table|option_pool|round_size|convertible|note)", re.I)


@tool(
    KIT,
    "terms_known_instruments",
    "Round and cap-table facts already in the source of truth (SAFEs and their caps, cap-table shares, round size) "
    "so the founder can feed them into terms_dilution. Returns Figures from the facts; no computation.",
)
def known_instruments(ctx: TruthContext) -> Result:
    figs = [fact_to_figure(ctx, f) for f in ctx.facts if f.status != "removed" and CAP_TABLE.search(f.name)]
    if not figs:
        return {
            "instruments": [],
            "missing": [
                dump(
                    missing(
                        "terms.instruments",
                        "Round and cap-table facts",
                        ["SAFE amounts and caps", "cap table"],
                        "No SAFE or cap-table facts in the source of truth",
                    )
                )
            ],
        }
    return {"instruments": [dump(f) for f in figs], "note": NOTE}


TERMS = Kit(
    KIT,
    "Dilution and waterfall arithmetic from founder-supplied inputs; never valuation advice.",
    [dilution, waterfall, known_instruments],
)
