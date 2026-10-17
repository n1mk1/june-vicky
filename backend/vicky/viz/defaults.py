"""The default dashboard: which widgets a fresh engagement gets, and where they sit.

Widgets adapt to what the data supports (recurring vs other revenue, credits, cohort tables).
Key metrics the data can't support get a kpi widget that evaluates to status `missing`, so
the frontend shows a missing-data tile naming the upload that would unlock it.

Layout follows the wireframe (docs/design/wireframe.png, UI doc §2/§3.4) on a 12-column grid
where one wireframe row is 4 grid units: margin ring and ARR card stacked on the left, the
readiness orb in the centre (5 columns, two rows), trend chart and attack list on the right,
the prompt bar below the orb, then extra widgets flowing underneath.
"""

from pydantic import BaseModel

from vicky.model.canonical import OPEX_CATEGORIES
from vicky.model.context import TruthContext
from vicky.model.figures import Figure, MissingFigure
from vicky.viz.spec import Presentation, SeriesSpec, WidgetSpec, Window

GRID_COLUMNS = 12
ROW = 4  # grid units per wireframe row

OPEX_NAMES = {"opex.r_and_d": "R&D", "opex.s_and_m": "Sales & marketing", "opex.g_and_a": "G&A",
              "opex.customer_success": "Customer success", "opex.other": "Other"}

# Metrics worth a missing-data tile when the data can't support them.
KEY_MISSING = ["nrr", "cash_balance", "cac_payback_months", "top_customer_share"]

# Fixed slots for components that are not widgets (the frontend renders them itself).
RESERVED = [
    {"id": "readiness_orb", "x": 3, "y": 0, "w": 5, "h": 2 * ROW},
    {"id": "attack_list", "x": 8, "y": ROW, "w": 4, "h": ROW},
    {"id": "prompt_bar", "x": 3, "y": 2 * ROW, "w": 6, "h": 2},
]
_FIXED = {
    "margin_ring": {"x": 0, "y": 0, "w": 3, "h": ROW},
    "headline_kpi": {"x": 0, "y": ROW, "w": 3, "h": ROW},
    "trend": {"x": 8, "y": 0, "w": 4, "h": ROW},
}
_FLOW_START = 2 * ROW + 2
_FLOW_SIZE = {"chart": (6, 5), "kpi": (3, 4), "missing": (3, 3)}


class LayoutItem(BaseModel):
    widget_index: int
    x: int
    y: int
    w: int
    h: int


class DefaultDashboard(BaseModel):
    widgets: list[WidgetSpec]
    roles: list[str]
    layout: list[LayoutItem]
    reserved: list[dict]


def _fig(ctx: TruthContext, fid: str) -> Figure | None:
    f = ctx.figures.get(fid)
    return f if isinstance(f, Figure) else None


def _build(ctx: TruthContext) -> list[tuple[str, str, WidgetSpec]]:
    """(role, size class, spec) in display order."""
    m = ctx.model
    out: list[tuple[str, str, WidgetSpec]] = []
    recurring = _fig(ctx, "arr") is not None
    credits = m.has("non_dilutive_income")
    monthly = m.granularity == "month"

    # 1. Gross margin ring: booked, plus incl. customer success when it can be computed
    rings = [SeriesSpec(ref="gross_margin", label="As booked")]
    incl = next((fid for fid in ("gross_margin_incl_cs", "gross_margin_incl_cs_l12m") if _fig(ctx, fid)), None)
    if incl:
        rings.append(SeriesSpec(ref=incl, label="Incl. customer success"))
    out.append(("margin_ring", "kpi", WidgetSpec(template="gauge_ring", title="Gross margin", series=rings)))

    # 2. Headline KPI card with a 2×2 of secondaries
    if recurring:
        kpi = [SeriesSpec(ref="arr", label="ARR"), SeriesSpec(ref="cmgr_12m", label="Growth, 12 months"),
               SeriesSpec(ref="cmgr_recent", label="Growth, recent"), SeriesSpec(ref="burn", label="Burn"),
               SeriesSpec(ref="runway_months", label="Runway")]
        title = "ARR"
    else:
        kpi = [SeriesSpec(ref="revenue", label="Revenue"), SeriesSpec(ref="revenue_growth", label="Growth"),
               SeriesSpec(ref="burn", label="Burn"), SeriesSpec(ref="runway_months", label="Runway")]
        title = "Revenue"
    out.append(("headline_kpi", "kpi", WidgetSpec(template="kpi", title=title, series=kpi)))

    # 3. Trend: MRR (or revenue) solid on the left, burn dashed on the right
    lead = SeriesSpec(ref="mrr", label="MRR") if recurring else SeriesSpec(ref="revenue", label="Revenue")
    trend = [lead]
    if m.has("net_income"):
        trend.append(SeriesSpec(ref="burn", label="Burn ex-credits" if credits else "Burn", axis="right", style="dashed"))
    out.append(("trend", "chart", WidgetSpec(
        template="line", title=f"{lead.label} and burn" if len(trend) > 1 else lead.label or "Revenue", series=trend,
        presentation=Presentation(dual_axis=len(trend) > 1))))

    # 4. Burn excluding credits as a share of revenue, by quarter
    if credits:
        out.append(("burn_ex_credits", "chart", WidgetSpec(
            template="combo_bar_line", title="Burn excluding credits, % of revenue by quarter",
            series=[SeriesSpec(ref="burn_ex_non_dilutive", label="Burn ex-credits"),
                    SeriesSpec(ref="pct_of(burn_ex_non_dilutive, revenue)", label="% of revenue", axis="right")],
            group_by="quarter" if m.granularity in ("month", "quarter") else None)))

    # 5. Opex mix by category
    cats = [c for c in OPEX_CATEGORIES if m.has(c)]
    if cats:
        out.append(("opex_mix", "chart", WidgetSpec(
            template="stacked_bar", title="Operating expenses by category",
            series=[SeriesSpec(ref=c, label=OPEX_NAMES[c]) for c in cats],
            group_by="quarter" if monthly else None, window=Window(last_n=8),
            presentation=Presentation(stack=True))))

    # 6. Retention: cohort heatmap and NRR/GRR card
    if m.cohort_mrr:
        out.append(("cohort_retention", "chart", WidgetSpec(
            template="heatmap", title="Revenue retention by cohort", series=[SeriesSpec(ref="cohort_retention")])))
    if _fig(ctx, "nrr"):
        nrr = [SeriesSpec(ref="nrr", label="NRR")] + ([SeriesSpec(ref="grr", label="GRR")] if _fig(ctx, "grr") else [])
        out.append(("nrr", "kpi", WidgetSpec(template="kpi", title="Net revenue retention", series=nrr)))

    # 7. Missing-data tiles for key metrics the data can't support yet
    shown = {s.ref for _, _, w in out for s in w.series}
    for fid in KEY_MISSING:
        f = ctx.figures.get(fid)
        if not isinstance(f, MissingFigure) or fid in shown or "Recurring-revenue metric" in f.reason:
            continue
        out.append((f"missing:{fid}", "missing", WidgetSpec(template="kpi", title=f.label or fid,
                                                             series=[SeriesSpec(ref=fid)])))
    return out


def default_widgets(ctx: TruthContext) -> list[WidgetSpec]:
    """The default widget specs for this engagement, in display order."""
    return [w for _, _, w in _build(ctx)]


def _layout(items: list[tuple[str, str, WidgetSpec]]) -> list[LayoutItem]:
    out: list[LayoutItem] = []
    x, y, row_h = 0, _FLOW_START, 0
    for i, (role, size, _) in enumerate(items):
        if role in _FIXED:
            out.append(LayoutItem(widget_index=i, **_FIXED[role]))
            continue
        w, h = _FLOW_SIZE[size]
        if x + w > GRID_COLUMNS:
            x, y, row_h = 0, y + row_h, 0
        out.append(LayoutItem(widget_index=i, x=x, y=y, w=w, h=h))
        x += w
        row_h = max(row_h, h)
    return out


def default_dashboard(ctx: TruthContext) -> DefaultDashboard:
    """Widgets plus the default layout `[{widget_index, x, y, w, h}]` and the reserved non-widget slots."""
    items = _build(ctx)
    return DefaultDashboard(widgets=[w for _, _, w in items], roles=[r for r, _, _ in items], layout=_layout(items),
                            reserved=[dict(r) for r in RESERVED])


def default_layout(ctx: TruthContext) -> list[dict]:
    return [li.model_dump() for li in default_dashboard(ctx).layout]
