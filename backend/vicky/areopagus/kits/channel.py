"""Channel: how much revenue depends on partners, and who owns the customer and the data."""

import re

from vicky.areopagus.kits._base import (
    Kit,
    Result,
    column_figure,
    derived,
    last_n_months,
    matching_columns,
    missing,
    out,
    sum_figure,
    tool,
)
from vicky.model.context import TruthContext

KIT = "Channel"

PARTNER = r"partner|resell|channel|referr|distributor|marketplace|affiliate|wholesale|\bvar\b|\boem\b"
COST = r"cost|commission|fee|expense|payout|cogs|rebate"

DATA_RIGHTS_QUESTIONS = [
    "Who owns the customer relationship on partner-sourced accounts: the company or the partner?",
    "Who owns the renewal on partner-sourced accounts, and who is paid when they renew?",
    "Which customer and usage data can the partner see, copy or export, and under which contract clause?",
    "Can the partner use customer data to build or sell a competing product?",
    "Does any partner contract grant exclusivity by segment, channel or geography?",
    "Does any partner or investor hold a right of first refusal or first notice on a sale of the company?",
    "Are there data-sharing side letters with a partner or strategic investor?",
    "If a partner terminates, can the company keep serving and billing the customers it brought in?",
    "Do customer contracts allow their data to be shared with partners at all?",
    "What revenue share or commission does each partner take, and is it on first-year or lifetime revenue?",
]


@tool(KIT, "channel_partner_share",
      "Partner / reseller / referral share of revenue when a data column suggests one; otherwise missing. Returns "
      "Figures per matching column: amount_l12m and share_of_revenue_l12m, plus the channels the founder listed.")
def partner_share(ctx: TruthContext) -> Result:
    cols = matching_columns(ctx, PARTNER)
    stated = [str(c) for c in ctx.profile.get("acquisition_channels") or []]
    res: Result = {"stated_channels": stated} if stated else {}
    ps = last_n_months(ctx, "revenue.total", 12)
    if not cols or not ps:
        res.update(out([missing("channel.partner_revenue", "Partner-sourced revenue", ["revenue by channel (partner vs direct)"],
                                "No column in the data separates partner or reseller revenue; ask for revenue by channel")]))
        return res
    rev = sum_figure(ctx, "revenue.total", ps, "channel.revenue_l12m", "Total revenue, last 12 months")
    found = []
    for i, (ds, col) in enumerate(cols, start=1):
        cost_like = bool(re.search(COST, col, re.I))
        what = "Partner costs" if cost_like else "Partner revenue"
        amt = column_figure(ctx, ds, col, ps, f"channel.col{i}_l12m", f"{what}: '{col}', last 12 months")
        if amt is None:
            continue
        item: Result = {"column": col, "reading": "cost" if cost_like else "revenue", "amount_l12m": amt.model_dump(mode="json")}
        if rev.value > 0:
            item["share_of_revenue_l12m"] = derived(
                f"channel.col{i}_share", f"'{col}' as a share of total revenue, last 12 months", amt.value / rev.value, "pct",
                f"{amt.display} ÷ total revenue {rev.display}", [amt, rev], period=amt.period).model_dump(mode="json")
        found.append(item)
    if not found:
        res.update(out([missing("channel.partner_revenue", "Partner-sourced revenue", ["revenue by channel (partner vs direct)"],
                                "Partner-looking columns have no values in the last 12 months")]))
        return res
    res["revenue_l12m"] = rev.model_dump(mode="json")
    res["columns"] = found
    return res


@tool(KIT, "channel_data_rights_checklist",
      "Questions on customer ownership, data rights, exclusivity and side letters in partner deals. Returns plain "
      "strings (no Figures).")
def data_rights_checklist(ctx: TruthContext) -> Result:
    return {"questions": list(DATA_RIGHTS_QUESTIONS),
            "note": "Questions to put to the founder; the answers live in contracts, not in the financial data."}


CHANNEL = Kit(KIT, "Partner revenue dependence and the data-rights questions that come with it.",
              [partner_share, data_rights_checklist])
