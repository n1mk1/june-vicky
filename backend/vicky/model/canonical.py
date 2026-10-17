"""The canonical financial vocabulary every upload is mapped onto.

Flow fields sum over a period (revenue, costs); stock fields take the period-end value
(cash, customers, headcount). Money fields carry the company currency as their unit.
"""

from dataclasses import dataclass
from typing import Literal

Kind = Literal["money", "count"]
Agg = Literal["sum", "last"]


@dataclass(frozen=True)
class Field:
    id: str
    label: str
    kind: Kind
    agg: Agg
    group: str


FIELDS: dict[str, Field] = {
    f.id: f
    for f in [
        Field("revenue.recurring", "Recurring revenue", "money", "sum", "revenue"),
        Field("revenue.one_time", "One-time revenue", "money", "sum", "revenue"),
        Field("revenue.total", "Total revenue", "money", "sum", "revenue"),
        Field("cogs", "Cost of revenue", "money", "sum", "costs"),
        Field("gross_profit", "Gross profit", "money", "sum", "costs"),
        Field("opex.r_and_d", "R&D", "money", "sum", "opex"),
        Field("opex.s_and_m", "Sales & marketing", "money", "sum", "opex"),
        Field("opex.g_and_a", "General & admin", "money", "sum", "opex"),
        Field("opex.customer_success", "Customer success", "money", "sum", "opex"),
        Field("opex.other", "Other opex", "money", "sum", "opex"),
        Field("opex.total", "Total opex", "money", "sum", "opex"),
        Field("operating_income", "Operating income", "money", "sum", "profit"),
        Field("depreciation", "Depreciation", "money", "sum", "profit"),
        Field("non_dilutive_income", "Non-dilutive income (credits, grants)", "money", "sum", "profit"),
        Field("net_income", "Net income", "money", "sum", "profit"),
        Field("cash_balance", "Cash balance", "money", "last", "cash"),
        Field("headcount.total", "Headcount", "count", "last", "team"),
        Field("customers.count", "Customers", "count", "last", "customers"),
        Field("customers.new", "New customers", "count", "sum", "customers"),
        Field("customers.churned", "Churned customers", "count", "sum", "customers"),
        Field("bookings", "Bookings", "money", "sum", "pipeline"),
        Field("pipeline", "Pipeline", "money", "last", "pipeline"),
    ]
}

OPEX_CATEGORIES = ["opex.r_and_d", "opex.s_and_m", "opex.g_and_a", "opex.customer_success", "opex.other"]

# Dimension tables: rows keyed by a period and a dimension (customer or signup cohort).
TABLE_KINDS = ("series", "customer_mrr", "cohort_mrr", "raw")
TABLE_FIELDS = {
    "customer_mrr": ["dim.customer", "period", "value.mrr"],
    "cohort_mrr": ["dim.cohort", "period", "value.mrr"],
}

SPECIAL_TARGETS = {"period", "dim.customer", "dim.cohort", "value.mrr"}

ALL_TARGETS = sorted(set(FIELDS) | SPECIAL_TARGETS)

LENSES = [
    "claims",
    "forecast",
    "retention",
    "unit_economics",
    "concentration",
    "runway",
    "governance",
    "market",
    "team",
    "product_tech",
    "terms_cap_table",
    "impact",
]


def is_money(field_id: str) -> bool:
    f = FIELDS.get(field_id)
    return bool(f and f.kind == "money")
