"""Market: TAM claims against what the source of truth supports, and a bottom-up build."""

import re

from vicky.areopagus.kits._base import (
    Kit,
    Result,
    derived,
    fig,
    founder_figure,
    get,
    latest_count,
    missing,
    num,
    out,
    pct_arg,
    schema,
    tool,
)
from vicky.areopagus.kits.benchmark import clean_source, sourced
from vicky.model.context import TruthContext
from vicky.model.figures import Figure

KIT = "Market"
MARKET = re.compile(r"\b(tam|sam|som)\b|market[_ ]?(size|sizing)|addressable|total[_ ]market", re.I)
UNITS = ("cad", "usd", "gbp", "eur", "aud", "pct", "count")

BOTTOM_UP_FIELDS = [
    ("target_accounts", "Number of target accounts: who they are, where, and the size band, with a cited count"),
    ("annual_value_per_account", "Annual contract value per account (price × units such as seats or sites)"),
    ("reachable_share_pct", "Share of those accounts reachable through today's channels"),
    ("account_count_source", "Where the account count comes from (census, registry, association, paid list)"),
]


def _claims(ctx: TruthContext) -> list[Figure]:
    out_: list[Figure] = []
    for f in ctx.facts:
        if f.status == "removed" or not MARKET.search(f"{f.name} {f.label}".replace("_", " ")):
            continue
        out_.append(Figure(id=f"fact.{f.name}", label=f.label or f.name, value=f.value,
                           unit=f.unit if f.unit in UNITS else ctx.currency, formula=f.label or f.name,
                           source=f.source, kind="founder_claim" if f.source.kind == "founder_stated" else f.kind,
                           period=f.period, group="facts"))
    return out_


@tool(KIT, "market_tam_claims",
      "Market-size claims in the source of truth (TAM / SAM / SOM facts) with their sources, any sourced market "
      "entries, and the bottom-up fields still needed. Returns Figures: claims[], arr, cmgr_recent, arpa; else missing.")
def tam_claims(ctx: TruthContext) -> Result:
    claims = _claims(ctx)
    sources = {str(s.get("id")): clean_source(s)[0] for s in sourced(["market_size", "acv"], ctx.profile)}
    res = out(arr=get(ctx, "arr"), cmgr_recent=get(ctx, "cmgr_recent"))
    if claims:
        res["claims"] = [c.model_dump(mode="json") for c in claims]
        res["unsourced_claims"] = [c.id for c in claims if c.source.kind == "founder_stated"]
    else:
        res.setdefault("missing", []).append(missing(
            "market.tam", "Market size", ["a sourced TAM / SAM figure or a bottom-up build"],
            "Nothing in the source of truth sizes the market; ask for a bottom-up build").model_dump(mode="json"))
    if sources:
        res["sources"] = list(sources.values())
    arr, customers = fig(ctx, "arr"), latest_count(ctx, "customers.count", "Customers")
    if arr is not None and customers is not None and customers.value > 0:
        res["arpa"] = derived("market.annual_value_per_customer", "ARR per customer today", arr.value / customers.value,
                              ctx.currency, f"ARR {arr.display} ÷ customers {customers.display}", [arr, customers],
                              period=arr.period).model_dump(mode="json")
    res["bottom_up_fields"] = [{"field": k, "needed": d} for k, d in BOTTOM_UP_FIELDS]
    return res


@tool(KIT, "market_bottom_up",
      "Computes a bottom-up market size from numbers the founder supplies and ties it back to today's ARR. Returns "
      "Figures: tam (accounts × annual value), sam (× reachable share), arr_share_of_sam, plus the inputs.",
      schema(target_accounts=num("Number of target accounts the founder states"),
             annual_value_per_account=num("Annual revenue per account the founder states, in the company currency"),
             reachable_share_pct=num("Percent of accounts reachable through current channels, e.g. 30 for 30%")))
def bottom_up(ctx: TruthContext, target_accounts: float, annual_value_per_account: float, reachable_share_pct: float) -> Result:
    if target_accounts <= 0 or annual_value_per_account <= 0:
        raise ValueError("target_accounts and annual_value_per_account must be positive")
    share = pct_arg(reachable_share_pct, "reachable_share_pct")
    if not 0 < share <= 1:
        raise ValueError("reachable_share_pct must be between 0 and 100")
    acc = founder_figure("market.target_accounts", "Target accounts", target_accounts, "count")
    acv = founder_figure("market.annual_value_per_account", "Annual value per account", annual_value_per_account, ctx.currency)
    reach = founder_figure("market.reachable_share", "Reachable share of accounts", share, "pct")
    tam = derived("market.tam_bottom_up", "Bottom-up market size", acc.value * acv.value, ctx.currency,
                  f"{acc.display} accounts × {acv.display} a year", [acc, acv])
    sam = derived("market.sam_bottom_up", "Reachable market", tam.value * share, ctx.currency,
                  f"{tam.display} × {reach.display} reachable", [tam, reach])
    parts: dict = {"target_accounts": acc, "annual_value_per_account": acv, "reachable_share": reach, "tam": tam, "sam": sam}
    arr = get(ctx, "arr")
    parts["arr"] = arr
    if isinstance(arr, Figure) and sam.value > 0:
        parts["arr_share_of_sam"] = derived("market.arr_share_of_sam", "Today's ARR as a share of the reachable market",
                                            arr.value / sam.value, "pct", f"ARR {arr.display} ÷ {sam.display}", [arr, sam])
    res = out(**parts)
    res["note"] = "Outcome of the founder's inputs; each input needs its own source before it goes in a deck."
    return res


MARKET_KIT = Kit(KIT, "Market-size claims against the source of truth, and a bottom-up build from founder inputs.",
                 [tam_claims, bottom_up])
