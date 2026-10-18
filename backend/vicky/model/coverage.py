"""Coverage checklist: which metric groups the source of truth supports and what unlocks the rest."""

from vicky.model.figures import Figure, MissingFigure

GROUPS: list[tuple[str, list[str]]] = [
    ("Revenue", ["revenue", "revenue_growth", "revenue_growth_yoy", "mrr", "arr"]),
    ("Growth", ["cmgr_12m", "cmgr_recent", "net_new_arr_l12m"]),
    ("Margins", ["gross_margin", "gross_margin_incl_cs", "gross_margin_incl_cs_l12m"]),
    ("Cash", ["burn", "burn_incl_credits", "cash_balance", "runway_months"]),
    (
        "Efficiency",
        ["burn_multiple", "burn_multiple_ex_credits", "magic_number", "cac", "cac_payback_months"],
    ),
    ("Retention", ["nrr", "grr", "logo_churn_rate", "revenue_churn_rate"]),
    ("Customers", ["top_customer_share"]),
]


def coverage(figures: dict[str, Figure | MissingFigure]) -> list[dict]:
    out = []
    for group, ids in GROUPS:
        for mid in ids:
            f = figures.get(mid)
            if f is None:
                continue
            if isinstance(f, Figure):
                out.append(
                    {
                        "group": group,
                        "metric_id": mid,
                        "label": f.label,
                        "available": True,
                        "needs": [],
                        "kind": f.kind,
                        "source_kind": f.source.kind,
                    }
                )
            else:
                out.append(
                    {
                        "group": group,
                        "metric_id": mid,
                        "label": f.label or mid,
                        "available": False,
                        "needs": f.needs,
                        "reason": f.reason,
                    }
                )
    return out
