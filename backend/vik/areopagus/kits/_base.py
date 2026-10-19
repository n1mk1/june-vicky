"""Shared plumbing for the kits: tool definitions, schema helpers and Figure builders.

Result convention for every kit tool:
- every number is inside a `Figure` dict (`Figure.model_dump(mode="json")`): engine figures
  pass through unchanged; anything a kit computes is a new Figure with `source.kind`
  "derived", a formula stating the arithmetic with the actual inputs, and `inputs` pointing
  at the engine figures or model cells used. Projections are `kind="forecast"`.
- inputs the founder types into a tool become Figures with `source.kind="founder_stated"`.
- whatever can't be computed is listed under `"missing"` as `MissingFigure` dicts naming
  the data that would unlock it.
- the only bare numbers allowed are integer offsets under the key `"month"` (path indices).
"""

import math
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from vik.model.canonical import FIELDS, is_money
from vik.model.context import TruthContext
from vik.model.figures import UNITS, Fact, Figure, FigureRef, MissingFigure, Source, fmt_value
from vik.model.financials import column_currency
from vik.model.fx import SOURCE_NAME
from vik.model.loader import period_sort_key, quarter_of
from vik.model.metrics import label_period

Result = dict[str, Any]


@dataclass(frozen=True)
class ToolDef:
    name: str
    description: str
    input_schema: dict
    fn: Callable[..., Result]
    kit: str = ""

    def to_tool(self) -> dict:
        """Gemini function declaration (JSON schema parameters)."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters_json_schema": self.input_schema,
        }

    def run(self, ctx: TruthContext, args: dict | None = None) -> Result:
        """Call the tool; bad inputs come back as a recoverable error message, not an exception."""
        try:
            return self.fn(ctx, **(args or {}))
        except (ValueError, TypeError) as e:
            return {"error": f"{self.name}: {e}"}


@dataclass
class Kit:
    name: str
    description: str
    tools: list[ToolDef] = field(default_factory=list)


# ---------------------------------------------------------------- schemas (strict-compatible)


def schema(**props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def num(desc: str) -> dict:
    return {"type": "number", "description": desc}


def opt_num(desc: str) -> dict:
    return {"anyOf": [{"type": "number"}, {"type": "null"}], "description": desc}


def integer(desc: str) -> dict:
    return {"type": "integer", "description": desc}


def boolean(desc: str) -> dict:
    return {"type": "boolean", "description": desc}


def enum(values: list[str], desc: str) -> dict:
    return {"type": "string", "enum": values, "description": desc}


def tool(kit: str, name: str, description: str, input_schema: dict | None = None) -> Callable:
    """Decorator turning a kit function into a ToolDef."""

    def wrap(fn: Callable[..., Result]) -> ToolDef:
        return ToolDef(
            name=name, description=description, input_schema=input_schema or schema(), fn=fn, kit=kit
        )

    return wrap


# ---------------------------------------------------------------- figure builders


def dump(f: Figure | MissingFigure) -> dict:
    return f.model_dump(mode="json")


def dumps(fs: Iterable[Figure | MissingFigure]) -> list[dict]:
    return [dump(f) for f in fs]


def ref(f: Figure) -> FigureRef:
    return FigureRef(figure_id=f.id, value=f.value, period=f.period)


def missing(fid: str, label: str, needs: list[str], reason: str, group: str = "kits") -> MissingFigure:
    return MissingFigure(id=fid, label=label, needs=needs, reason=reason, group=group)


def get(ctx: TruthContext, fid: str) -> Figure | MissingFigure:
    f = ctx.figures.get(fid)
    if f is None:
        return missing(fid, fid, [fid], f"The engine has no figure '{fid}' for this company")
    return f


def fig(ctx: TruthContext, fid: str) -> Figure | None:
    f = ctx.figures.get(fid)
    return f if isinstance(f, Figure) else None


def derived(
    fid: str,
    label: str,
    value: float,
    unit: str,
    formula: str,
    inputs: Iterable[Figure | FigureRef],
    *,
    projection: bool = False,
    period: str | None = None,
    group: str = "kits",
) -> Figure:
    """A kit-computed Figure. Kind: forecast for projections or forecast inputs; founder_claim if it rests on one."""
    inputs = list(inputs)
    figs = [x for x in inputs if isinstance(x, Figure)]
    refs = [ref(x) if isinstance(x, Figure) else x for x in inputs]
    if projection or any(f.kind == "forecast" for f in figs):
        kind = "forecast"
    elif any(f.kind == "founder_claim" or f.source.kind == "founder_stated" for f in figs):
        kind = "founder_claim"
    else:
        kind = "historical"
    names = [r.figure_id or ".".join(x for x in (r.column, r.period) if x) for r in refs]
    src = Source(
        kind="derived", ref="derived from " + ", ".join(n for n in names if n) if names else "derived"
    )
    return Figure(
        id=fid,
        label=label,
        value=float(value),
        unit=unit,
        formula=formula,
        inputs=refs,
        source=src,
        kind=kind,
        period=period,
        group=group,
    )


def founder_figure(
    fid: str,
    label: str,
    value: float,
    unit: str,
    where: str = "supplied by the founder in this session",
    group: str = "kits",
) -> Figure:
    return Figure(
        id=fid,
        label=label,
        value=float(value),
        unit=unit,
        formula=f"{label}, as {where}",
        source=Source(kind="founder_stated", ref=where),
        kind="founder_claim",
        group=group,
    )


def profile_figure(ctx: TruthContext, key: str, label: str, unit: str) -> Figure | None:
    """A number the founder gave in the company profile, or a confirmed fact with that name."""
    f = fig(ctx, f"fact.{key}")
    if f is not None:
        return f
    v = ctx.profile.get(key)
    if isinstance(v, int | float) and not isinstance(v, bool) and v > 0:
        fx = ctx.profile.get(f"{key}_fx")
        return founder_figure(
            f"profile.{key}",
            label,
            float(v),
            unit,
            where=f"stated in the company profile ({key})" + (f" · converted {fx}" if fx else ""),
        )
    return None


PERIOD_RX = re.compile(r"^\d{4}(-(Q[1-4]|\d{2}))?$")


def fact_to_figure(
    ctx: TruthContext, fact: Fact, fid: str | None = None, unit: str | None = None, value: float | None = None
) -> Figure:
    u = unit or (
        fact.unit if fact.unit in UNITS else ctx.currency if fact.unit in ("money", "$") else "count"
    )
    kind = "founder_claim" if fact.source.kind == "founder_stated" else fact.kind
    return Figure(
        id=fid or (f"fact.{fact.name}" + (f".{fact.period}" if fact.period else "")),
        label=fact.label or fact.name,
        value=fact.value if value is None else value,
        unit=u,
        formula=fact.label or fact.name,
        source=fact.source,
        kind=kind,
        period=fact.period,
        group="facts",
    )


def live_facts(ctx: TruthContext, name: str, *, forecast: bool | None = None) -> list[Fact]:
    """Confirmed (or pending) facts with this name, oldest period first; forecast=None keeps both kinds."""
    out_ = [
        f
        for f in ctx.facts
        if f.status != "removed"
        and f.name == name
        and (forecast is None or (f.kind == "forecast") == forecast)
    ]
    return sorted(
        out_, key=lambda f: period_sort_key(f.period) if f.period and PERIOD_RX.match(f.period) else (0, 0)
    )


def fact_series(ctx: TruthContext, name: str) -> list[Figure]:
    """Historical facts for one name that carry a real period (YYYY-MM, YYYY-Qn, YYYY), as Figures."""
    return [
        fact_to_figure(ctx, f)
        for f in live_facts(ctx, name, forecast=False)
        if f.period and PERIOD_RX.match(f.period)
    ]


def latest_count(ctx: TruthContext, field_id: str, label: str) -> Figure | None:
    """Latest value of a stock field: model cell first, else the most recent historical fact."""
    p = ctx.model.latest(field_id)
    if p is not None:
        return cell_figure(ctx, field_id, p, fid=field_id, label=label)
    f = fig(ctx, field_id)
    if f is not None:
        return f
    series = fact_series(ctx, field_id)
    return series[-1] if series else None


def months_between(a: str, b: str) -> int:
    ya, ma = period_sort_key(a)
    yb, mb = period_sort_key(b)
    return (yb * 12 + mb) - (ya * 12 + ma)


def period_months(p: str) -> int:
    return 3 if "-Q" in p else 1 if "-" in p else 12


def money_unit(ctx: TruthContext) -> str:
    return ctx.currency


def cell_figure(
    ctx: TruthContext,
    field_id: str,
    period: str,
    fid: str | None = None,
    label: str | None = None,
    group: str = "kits",
) -> Figure | None:
    m = ctx.model
    c = m.cell(field_id, period)
    if c is None:
        return None
    ds, refstr, kind = m.source_ref(field_id, [period])
    name = FIELDS[field_id].label if field_id in FIELDS else field_id
    unit = ctx.currency if is_money(field_id) else "count"
    formula = f"{name} in {label_period(period)}" + (f" ({c.derived})" if c.derived else "")
    return Figure(
        id=fid or f"{field_id}.{period}",
        label=label or f"{name}, {label_period(period)}",
        value=c.value,
        unit=unit,
        formula=formula,
        inputs=[FigureRef(dataset_id=c.dataset_id, column=field_id, period=period, value=c.value)],
        source=Source(kind=kind if kind in ("csv", "xlsx") else "derived", ref=refstr, dataset_id=ds),
        period=period,
        group=group,
    )


def sum_figure(
    ctx: TruthContext, field_id: str, periods: list[str], fid: str, label: str, group: str = "kits"
) -> Figure:
    m = ctx.model
    total = sum(m.value(field_id, p) or 0.0 for p in periods)
    ds, refstr, kind = m.source_ref(field_id, periods)
    name = FIELDS[field_id].label if field_id in FIELDS else field_id
    window = window_label(periods)
    return Figure(
        id=fid,
        label=label,
        value=total,
        unit=ctx.currency if is_money(field_id) else "count",
        formula=f"Sum of {name.lower()} over {window} ({len(periods)} periods)",
        inputs=[
            FigureRef(dataset_id=ds, column=field_id, period=p, value=m.value(field_id, p)) for p in periods
        ],
        source=Source(kind=kind if kind in ("csv", "xlsx") else "derived", ref=refstr, dataset_id=ds),
        period=f"{periods[0]}..{periods[-1]}",
        group=group,
    )


def table_source(ctx: TruthContext, table_kind: str, refstr: str) -> Source:
    ds = ctx.model.table_sources.get(table_kind)
    dsi = ctx.model.datasets.get(ds or "")
    kind = dsi.upload_kind if dsi and dsi.upload_kind in ("csv", "xlsx") else "csv"
    return Source(kind=kind, ref=refstr + ctx.model.table_fx.get(table_kind, ""), dataset_id=ds)


def column_series(ctx: TruthContext, ds_id: str, col: str) -> dict[str, float]:
    """One source column of a series dataset, aligned to the model's periods (months summed into quarters)."""
    m = ctx.model
    d = m.datasets.get(ds_id)
    if d is None or d.table_kind != "series":
        return {}
    mapping = next((x for x in d.mapping if x.get("source_column") == col), {})
    src = column_currency(mapping, m.currency)
    agg = FIELDS[mapping["canonical_field"]].agg if mapping.get("canonical_field") in FIELDS else "sum"
    out: dict[str, float] = {}
    for row in d.rows:
        v = row.get(col)
        if not isinstance(v, int | float) or isinstance(v, bool):
            continue
        conv = m.convert(
            float(v), src, row["period"], agg
        )  # a column in another currency, at its period's rate
        if conv is None:
            continue
        v = conv[0]
        p = row["period"]
        if d.granularity != m.granularity:
            if d.granularity == "month" and m.granularity == "quarter":
                p = quarter_of(p)
            else:
                continue
        out[p] = out.get(p, 0.0) + float(v)
    return dict(sorted(out.items(), key=lambda kv: period_sort_key(kv[0])))


def column_figure(
    ctx: TruthContext, ds_id: str, col: str, periods: list[str], fid: str, label: str, group: str = "kits"
) -> Figure | None:
    series = column_series(ctx, ds_id, col)
    ps = [p for p in periods if p in series]
    if not ps:
        return None
    d = ctx.model.datasets[ds_id]
    total = sum(series[p] for p in ps)
    kind = d.upload_kind if d.upload_kind in ("csv", "xlsx") else "csv"
    what = f"Sum of '{col}' over {window_label(ps)}" if len(ps) > 1 else f"'{col}' in {label_period(ps[0])}"
    return Figure(
        id=fid,
        label=label,
        value=total,
        unit=ctx.currency,
        formula=what,
        inputs=[FigureRef(dataset_id=ds_id, column=col, period=p, value=series[p]) for p in ps],
        source=Source(
            kind=kind, ref=f"{d.name} · {col} · {window_label(ps)}{_column_fx(ctx, d, col)}", dataset_id=ds_id
        ),
        period=ps[0] if len(ps) == 1 else f"{ps[0]}..{ps[-1]}",
        group=group,
    )


def _column_fx(ctx: TruthContext, d, col: str) -> str:
    mapping = next((x for x in d.mapping if x.get("source_column") == col), {})
    src = column_currency(mapping, ctx.currency)
    return (
        ""
        if src == ctx.currency
        else f" · converted {src.upper()}→{ctx.currency.upper()} at {SOURCE_NAME} rates for each period"
    )


def series_columns(ctx: TruthContext) -> list[tuple[str, str]]:
    """(dataset id, source column) for every numeric column of every series dataset."""
    out = []
    for ds_id, d in ctx.model.datasets.items():
        if d.table_kind != "series":
            continue
        cols: list[str] = []
        for row in d.rows:
            for k, v in row.items():
                if k != "period" and isinstance(v, int | float) and not isinstance(v, bool) and k not in cols:
                    cols.append(k)
        out += [(ds_id, c) for c in cols]
    return out


def matching_columns(ctx: TruthContext, pattern: str, exclude: str | None = None) -> list[tuple[str, str]]:
    rx, ex = re.compile(pattern, re.I), re.compile(exclude, re.I) if exclude else None
    return [(d, c) for d, c in series_columns(ctx) if rx.search(c) and not (ex and ex.search(c))]


# ---------------------------------------------------------------- periods and arithmetic


def window_label(periods: list[str]) -> str:
    if not periods:
        return ""
    if len(periods) == 1:
        return label_period(periods[0])
    return f"{label_period(periods[0])} → {label_period(periods[-1])}"


def last_n_months(ctx: TruthContext, field_id: str, months: int) -> list[str]:
    steps = max(1, months // ctx.model.months_per_period)
    return ctx.model.periods_with(field_id)[-steps:]


def add_months(period: str, n: int) -> str:
    """Calendar month (YYYY-MM) n months after the end of a period."""
    y, m = period_sort_key(period)
    t = y * 12 + (m - 1) + n
    return f"{t // 12}-{t % 12 + 1:02d}"


def pct_arg(x: float, name: str) -> float:
    """Tool inputs give percentages as percent numbers (20 means 20%)."""
    if not isinstance(x, int | float) or isinstance(x, bool) or math.isnan(x):
        raise ValueError(f"{name} must be a number of percent, e.g. 20 for 20%")
    return float(x) / 100.0


def fmt(v: float, unit: str) -> str:
    return fmt_value(v, unit)


def pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def compound(start: float, rate: float, months: float) -> float:
    return start * (1 + rate) ** months


def months_to_reach(start: float, target: float, rate: float) -> float | None:
    if start <= 0 or target <= start or rate <= 0:
        return None
    return math.log(target / start) / math.log(1 + rate)


def recent_growth(ctx: TruthContext, basis: str = "recent") -> Figure | MissingFigure:
    """Engine CMGR when the company is recurring; otherwise CMGR of total revenue derived here."""
    engine_id = "cmgr_recent" if basis == "recent" else "cmgr_12m"
    f = fig(ctx, engine_id)
    if f is not None:
        return f
    m = ctx.model
    months = 3 if basis == "recent" else 12
    steps = max(1, months // m.months_per_period)
    ps = m.periods_with("revenue.total")
    fid = f"kits.revenue_cmgr_{'recent' if basis == 'recent' else '12m'}"
    label = f"Monthly growth of total revenue, last {steps * m.months_per_period} months"
    if len(ps) < steps + 1:
        return missing(fid, label, ["revenue.total"], f"Needs at least {steps + 1} periods of revenue")
    a, b = ps[-steps - 1], ps[-1]
    va, vb = m.value("revenue.total", a), m.value("revenue.total", b)
    if not va or not vb or va <= 0 or vb <= 0:
        return missing(fid, label, ["revenue.total"], "Revenue must be positive at both ends of the window")
    n = steps * m.months_per_period
    rate = (vb / va) ** (1 / n) - 1
    fa, fb = cell_figure(ctx, "revenue.total", a), cell_figure(ctx, "revenue.total", b)
    return derived(
        fid,
        label,
        rate,
        "pct",
        f"(total revenue {label_period(b)} {fmt(vb, ctx.currency)} ÷ {label_period(a)} {fmt(va, ctx.currency)})^(1/{n}) − 1",
        [x for x in (fa, fb) if x],
        period=f"{a}..{b}",
    )


def split(results: Iterable[Figure | MissingFigure]) -> tuple[list[Figure], list[MissingFigure]]:
    figs, miss = [], []
    for r in results:
        (figs if isinstance(r, Figure) else miss).append(r)
    return figs, miss


def out(missing_list: list[MissingFigure] | None = None, **parts: Any) -> Result:
    """Assemble a result: Figures are dumped, MissingFigures are collected under 'missing'."""
    res: Result = {}
    miss = list(missing_list or [])
    for k, v in parts.items():
        if isinstance(v, MissingFigure):
            miss.append(v)
        elif isinstance(v, Figure):
            res[k] = dump(v)
        elif v is not None:
            res[k] = v
    seen: set[str] = set()
    uniq = []
    for mf in miss:
        if mf.id not in seen:
            seen.add(mf.id)
            uniq.append(dump(mf))
    if uniq:
        res["missing"] = uniq
    return res
