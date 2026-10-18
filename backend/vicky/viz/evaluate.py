"""Evaluate a WidgetSpec against a TruthContext.

Every number in the result is computed here from the canonical model or from engine figures,
and every point carries its provenance: a formula with the actual numbers, the input cells
(field, period, value, dataset, row ref) and a source. Specs (and so LLMs) never supply values.

Series are computed on a period frame: the model's native periods, optionally regrouped
month → quarter → year (flow fields sum over the group, stock fields take the period-end
value; partial groups are left empty rather than summed short). Functions that look back
(lag, yoy, cmgr, rolling) see the whole history; the window only decides what is shown.
"""

import math
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from vicky.model.canonical import FIELDS
from vicky.model.context import TruthContext
from vicky.model.figures import CURRENCY_UNITS, Figure, MissingFigure, Source, fmt_value
from vicky.model.loader import period_sort_key, quarter_of
from vicky.model.metrics import label_period
from vicky.viz.dsl import (
    HELPER_LABELS,
    HELPERS,
    METRIC_IDS,
    Bin,
    Call,
    DSLError,
    Name,
    Neg,
    Node,
    Num,
    Raw,
    name_kind,
    names,
    parse,
    to_source,
)
from vicky.viz.spec import SCALAR_TEMPLATES, SeriesSpec, WidgetSpec, Window, spec_hash

Status = Literal["ok", "missing", "error"]
Role = Literal["value", "compare", "waterfall_base", "waterfall_up", "waterfall_down"]

COHORT_REFS = {"cohort_retention", "cohort_mrr"}
MAX_INPUTS = 48
_RANK = {"month": 0, "quarter": 1, "year": 2}
_MONTHS = {"month": 1, "quarter": 3, "year": 12}


# ---------------------------------------------------------------- result shapes

class InputRef(BaseModel):
    field: str | None = None
    figure_id: str | None = None
    raw: str | None = None
    period: str | None = None
    value: float | None = None
    dataset_id: str | None = None
    ref: str | None = None


class PointSource(BaseModel):
    kind: str
    ref: str = ""
    dataset_id: str | None = None


class Point(BaseModel):
    period: str
    label: str
    value: float | None
    formula: str
    inputs: list[InputRef] = Field(default_factory=list)
    source: PointSource | None = None


class EvaluatedSeries(BaseModel):
    label: str
    ref: str
    unit: str | None
    axis: Literal["left", "right"] = "left"
    style: Literal["solid", "dashed"] = "solid"
    role: Role = "value"
    points: list[Point]


class KpiItem(BaseModel):
    id: str
    label: str
    value: float | None = None
    unit: str | None = None
    display: str = ""
    formula: str = ""
    inputs: list[InputRef] = Field(default_factory=list)
    source: PointSource | None = None
    kind: str = "historical"
    period: str | None = None
    missing: MissingFigure | None = None


class Kpi(BaseModel):
    primary: KpiItem
    secondary: list[KpiItem] = Field(default_factory=list)


class MarkLineValue(BaseModel):
    label: str
    value: float
    unit: str | None
    formula: str
    source: PointSource | None = None


class EvaluatedWidget(BaseModel):
    status: Status
    template: str
    title: str
    spec_hash: str = ""
    currency: str = ""
    granularity: str = ""
    periods: list[str] = Field(default_factory=list)
    period_labels: list[str] = Field(default_factory=list)
    series: list[EvaluatedSeries] = Field(default_factory=list)
    kpi: Kpi | None = None
    mark_lines: list[MarkLineValue] = Field(default_factory=list)
    missing: MissingFigure | None = None
    missing_series: list[MissingFigure] = Field(default_factory=list)
    error: str | None = None
    notes: list[str] = Field(default_factory=list)

    def numbers(self) -> set[float]:
        """Every number this result contains (tests use it to check charts invent nothing)."""
        out = {p.value for s in self.series for p in s.points if p.value is not None}
        out |= {m.value for m in self.mark_lines}
        if self.kpi:
            out |= {k.value for k in [self.kpi.primary, *self.kpi.secondary] if k.value is not None}
        return out


# ---------------------------------------------------------------- formatting

def _fmt(v: float | None, unit: str | None = None) -> str:
    if v is None or not math.isfinite(v):
        return "n/a"
    if unit == "pct":
        return f"{v * 100:.1f}%"
    if v == int(v) or abs(v) >= 100:
        return f"{v:,.0f}"
    return f"{v:,.4g}"


def _lower(label: str) -> str:
    return label if label[:2].isupper() else label[:1].lower() + label[1:]


def _dedupe(items: list) -> list:
    out = []
    for x in items:
        if x not in out:
            out.append(x)
    return out


# ---------------------------------------------------------------- internal values

@dataclass
class P:
    value: float | None
    text: str
    inputs: list[InputRef] = field(default_factory=list)
    defs: list[str] = field(default_factory=list)
    note: str | None = None
    boxed: bool = False  # text already ends with the value (function results)


OUT_OF_RANGE = "result out of range"


def _finite(v: float | None) -> bool:
    return v is not None and math.isfinite(v)


@dataclass
class SV:
    """A series over the frame's periods."""
    pts: dict[str, P]


@dataclass
class CV:
    """One number (a constant, a figure or a reduction over the window)."""
    pt: P


Val = SV | CV


def _merge(*pts: P) -> tuple[list[InputRef], list[str]]:
    inputs: list[InputRef] = []
    defs: list[str] = []
    for p in pts:
        for i in p.inputs:
            if len(inputs) >= MAX_INPUTS:
                break
            if i not in inputs:
                inputs.append(i)
        for d in p.defs:
            if d not in defs:
                defs.append(d)
    return inputs, defs


# ---------------------------------------------------------------- the period frame

class Frame:
    """The model's periods, optionally regrouped to a coarser granularity."""

    def __init__(self, ctx: TruthContext, group_by: str | None):
        self.ctx = ctx
        self.model = ctx.model
        native = self.model.granularity if self.model.granularity in _RANK else "month"
        target = group_by or native
        self.notes: list[str] = []
        if _RANK[target] < _RANK[native]:
            self.notes.append(f"The data is {native}ly, so it can't be shown by {target}; showing by {native}.")
            target = native
        self.native, self.target = native, target
        self.groups: dict[str, list[str]] = {}
        for p in self.model.periods:
            self.groups.setdefault(self.out_period(p), []).append(p)
        self.periods = sorted(self.groups, key=period_sort_key)
        expected = _MONTHS[target] // _MONTHS[native]
        self.complete = {g: len(ms) == expected for g, ms in self.groups.items()}
        if not all(self.complete.values()) and target != native:
            partial = [label_period(g) for g, ok in self.complete.items() if not ok]
            self.notes.append(f"Partial {target}s are left empty rather than summed short: {', '.join(partial)}.")
        self._cache: dict[Any, dict[str, P]] = {}
        self._refs: dict[tuple[str, str], str] = {}

    @property
    def months(self) -> int:
        return _MONTHS[self.target]

    def out_period(self, p: str) -> str:
        if self.target == self.native:
            return p
        if self.target == "quarter":
            return quarter_of(p)
        return p[:4]

    def index(self, p: str) -> int:
        return self.periods.index(p)

    def cell_ref(self, fid: str, p: str) -> str:
        key = (fid, p)
        if key not in self._refs:
            self._refs[key] = self.model.source_ref(fid, [p])[1]
        return self._refs[key]

    def field(self, fid: str, zero_fill: bool = False) -> dict[str, P]:
        key = ("field", fid, zero_fill)
        if key in self._cache:
            return self._cache[key]
        f = FIELDS[fid]
        label = _lower(f.label)
        out: dict[str, P] = {}
        for g in self.periods:
            members = self.groups[g]
            cells = [(p, self.model.cell(fid, p)) for p in members]
            if any(c is not None and not math.isfinite(c.value) for _, c in cells):
                out[g] = P(None, f"{label} n/a", note=f"a {label} value for {label_period(g)} is out of range")
                continue
            if not self.complete[g]:
                out[g] = P(None, f"{label} n/a", note=f"{label_period(g)} is a partial {self.target}")
                continue
            if any(c is None for _, c in cells) and not zero_fill:
                out[g] = P(None, f"{label} n/a", note=f"no {label} for {label_period(g)}")
                continue
            present = [(p, c) for p, c in cells if c is not None]
            inputs = [InputRef(field=fid, period=p, value=c.value, dataset_id=c.dataset_id, ref=self.cell_ref(fid, p))
                      for p, c in present]
            if f.agg == "last":
                v = present[-1][1].value if present and present[-1][0] == members[-1] else None
                defs = [f"{label} at the end of {label_period(members[-1])}"] if len(members) > 1 else []
                out[g] = P(v, f"{label} {_fmt(v, self.unit_of_field(fid))}", inputs[-1:], defs)
                continue
            v = sum(c.value for _, c in present) if present else 0.0
            if not math.isfinite(v):
                out[g] = P(None, f"{label} n/a", inputs, note=OUT_OF_RANGE)
                continue
            defs = []
            if len(members) > 1:
                parts = " + ".join(_fmt(c.value if c else 0.0) for _, c in cells)
                defs.append(f"{label} {label_period(g)} = {parts} ({label_period(members[0])}–{label_period(members[-1])})")
            out[g] = P(v, f"{label} {_fmt(v)}", inputs, defs)
        self._cache[key] = out
        return out

    def raw(self, key: str) -> dict[str, P]:
        ck = ("raw", key)
        if ck in self._cache:
            return self._cache[ck]
        by_p = self.model.raw.get(key, {})
        ds, col = self.model.raw_source.get(key, (None, key))
        dsi = self.model.datasets.get(ds or "")
        ref = f"{dsi.name if dsi else key.split(':')[0]} · {col}"
        out: dict[str, P] = {}
        for g in self.periods:
            members = self.groups[g]
            if not self.complete[g] or any(p not in by_p for p in members):
                out[g] = P(None, f"{col} n/a")
                continue
            if not all(math.isfinite(by_p[p]) for p in members):
                out[g] = P(None, f"{col} n/a", note=f"a {col} value for {label_period(g)} is out of range")
                continue
            v = sum(by_p[p] for p in members)
            if not math.isfinite(v):
                out[g] = P(None, f"{col} n/a", note=OUT_OF_RANGE)
                continue
            inputs = [InputRef(raw=key, period=p, value=by_p[p], dataset_id=ds, ref=ref) for p in members]
            out[g] = P(v, f"{col} {_fmt(v)}", inputs)
        self._cache[ck] = out
        return out

    def unit_of_field(self, fid: str) -> str:
        return "money" if FIELDS[fid].kind == "money" else "count"


# ---------------------------------------------------------------- evaluator

class Evaluator:
    def __init__(self, ctx: TruthContext, frame: Frame, window: list[str]):
        self.ctx = ctx
        self.frame = frame
        self.window = window
        self.unit_hint: str | None = None

    # ---- units (static over the AST)
    def unit(self, node: Node) -> str | None:
        if isinstance(node, Num):
            return None
        if isinstance(node, Name):
            k = name_kind(node.id)
            if k == "field":
                return self.frame.unit_of_field(node.id)
            if k == "helper":
                return "pct" if node.id.startswith("gross_margin") else "money"
            f = self.ctx.figures.get(node.id)
            if isinstance(f, Figure):
                return "money" if f.unit in CURRENCY_UNITS else f.unit
            return None
        if isinstance(node, Raw):
            ds, col = self.ctx.model.raw_source.get(node.key, (None, ""))
            dsi = self.ctx.model.datasets.get(ds or "")
            unit = next((m.get("unit") for m in (dsi.mapping if dsi else []) if m.get("source_column") == col), None)
            return "money" if unit in CURRENCY_UNITS else ("count" if unit == "count" else None)
        if isinstance(node, Neg):
            return self.unit(node.operand)
        if isinstance(node, Bin):
            lu, ru = self.unit(node.left), self.unit(node.right)
            if node.op in "+-":
                return lu or ru
            if node.op == "*":
                if lu and ru and "pct" in (lu, ru):
                    return ru if lu == "pct" else lu
                return lu or ru
            if lu and lu == ru:
                return "pct"
            if lu and (ru is None or ru == "pct" or (lu == "money" and ru == "count")):
                return lu
            return None
        if node.fn in ("pct_of", "yoy", "mom", "cmgr"):
            return "pct"
        return next((u for u in (self.unit(a) for a in node.args) if u), None)

    # ---- evaluation
    def ev(self, node: Node) -> Val:
        if isinstance(node, Num):
            return CV(P(node.value, _fmt(node.value)))
        if isinstance(node, Raw):
            return SV(self.frame.raw(node.key))
        if isinstance(node, Name):
            return self.name(node.id)
        if isinstance(node, Neg):
            v = self.ev(node.operand)
            return self.map1(v, lambda p: P(None if p.value is None else -p.value, f"−({p.text})", p.inputs, p.defs,
                                            p.note))
        if isinstance(node, Bin):
            if node.op == "*":
                self._no_percent_scaling(node)
            return self.binary(node.op, self.ev(node.left), self.ev(node.right))
        return self.call(node)

    def _no_percent_scaling(self, node: Bin) -> None:
        """`gross_margin * 100` would keep the pct unit and show "9255%": percent series are fractions."""
        for series, factor in ((node.left, node.right), (node.right, node.left)):
            if isinstance(factor, Num) and abs(factor.value) == 100 and self.unit(series) == "pct":
                src = to_source(series)
                raise DSLError(f"{src} is a percentage stored as a fraction (0.92 shows as 92%), so multiplying it by "
                               f"100 would show it 100 times too large. Use {src} on its own.")

    def name(self, nid: str) -> Val:
        kind = name_kind(nid)
        if kind == "field":
            return SV(self.frame.field(nid))
        if kind == "helper":
            return SV(self.helper(nid))
        f = self.ctx.figures.get(nid)
        if not isinstance(f, Figure):
            raise DSLError(f"'{nid}' is not available for this company")
        inp = InputRef(figure_id=f.id, period=f.period, value=f.value, dataset_id=f.source.dataset_id, ref=f.source.ref)
        return CV(P(f.value, f"{_lower(f.label)} {f.display}", [inp], [f"{_lower(f.label)} = {f.formula}"]))

    def helper(self, hid: str) -> dict[str, P]:
        fr = self.frame
        key = ("helper", hid)
        if key in fr._cache:
            return fr._cache[key]
        lbl = HELPER_LABELS[hid]
        out: dict[str, P] = {}
        for g in fr.periods:
            if hid == "revenue":
                r = fr.field("revenue.total")[g]
                out[g] = P(r.value, f"revenue {_fmt(r.value)}", r.inputs, r.defs, r.note)
                continue
            if hid in ("burn", "burn_ex_non_dilutive"):
                ni = fr.field("net_income")[g]
                nd = fr.field("non_dilutive_income", zero_fill=True)[g] if hid != "burn" else None
                parts = [ni] + ([nd] if nd else [])
                if any(p.value is None for p in parts):
                    out[g] = P(None, f"{lbl} n/a", note=next(p.note for p in parts if p.value is None))
                    continue
                inputs, defs = _merge(*parts)
                if nd is None:
                    v = -ni.value
                    defs.append(f"burn = −net income {_fmt(ni.value)}")
                else:
                    v = -(ni.value - nd.value)
                    defs.append(f"burn ex non-dilutive = −(net income {_fmt(ni.value)} − non-dilutive income {_fmt(nd.value)})")
                if not math.isfinite(v):
                    out[g] = P(None, f"{lbl} n/a", inputs, note=OUT_OF_RANGE)
                    continue
                out[g] = P(v, f"{lbl} {_fmt(v)}", inputs, defs)
                continue
            if hid in ("mrr", "arr"):
                rec = fr.field("revenue.recurring")[g]
                if rec.value is None:
                    out[g] = P(None, f"{lbl} n/a", note=rec.note)
                    continue
                mrr = rec.value / fr.months
                inputs, defs = _merge(rec)
                per = f" ÷ {fr.months} months" if fr.months > 1 else ""
                defs.append(f"MRR = recurring revenue {_fmt(rec.value)}{per}")
                v = mrr * 12 if hid == "arr" else mrr
                if hid == "arr":
                    defs.append(f"ARR = MRR {_fmt(mrr)} × 12")
                if not math.isfinite(v):
                    out[g] = P(None, f"{lbl} n/a", inputs, note=OUT_OF_RANGE)
                    continue
                out[g] = P(v, f"{lbl} {_fmt(v)}", inputs, defs)
                continue
            # gross margins
            parts = [fr.field("revenue.total")[g], fr.field("cogs")[g]]
            if hid == "gross_margin_incl_cs":
                parts.append(fr.field("opex.customer_success")[g])
            if any(p.value is None for p in parts):
                out[g] = P(None, f"{lbl} n/a", note=next(p.note for p in parts if p.value is None))
                continue
            rev, cost = parts[0].value, sum(p.value for p in parts[1:])
            inputs, defs = _merge(*parts)
            cs = f" − customer success {_fmt(parts[2].value)}" if len(parts) == 3 else ""
            if rev == 0:
                out[g] = P(None, f"{lbl} n/a", inputs, defs, note="revenue is zero")
                continue
            v = (rev - cost) / rev
            if not math.isfinite(v):
                out[g] = P(None, f"{lbl} n/a", inputs, note=OUT_OF_RANGE)
                continue
            defs.append(f"{lbl} = (revenue {_fmt(rev)} − cost of revenue {_fmt(parts[1].value)}{cs}) ÷ revenue {_fmt(rev)}")
            out[g] = P(v, f"{lbl} {_fmt(v, 'pct')}", inputs, defs)
        fr._cache[key] = out
        return out

    # ---- combinators
    def map1(self, v: Val, fn) -> Val:
        if isinstance(v, CV):
            return CV(fn(v.pt))
        return SV({g: fn(p) for g, p in v.pts.items()})

    def zip(self, vals: list[Val], fn) -> Val:
        if all(isinstance(v, CV) for v in vals):
            return CV(fn([v.pt for v in vals]))
        return SV({g: fn([v.pt if isinstance(v, CV) else v.pts[g] for v in vals]) for g in self.frame.periods})

    def binary(self, op: str, a: Val, b: Val) -> Val:
        sym = {"+": "+", "-": "−", "*": "×", "/": "÷"}[op]

        def f(ps: list[P]) -> P:
            x, y = ps
            inputs, defs = _merge(x, y)
            text = f"{x.text} {sym} {y.text}"
            if x.value is None or y.value is None:
                return P(None, text, inputs, defs, x.note or y.note)
            if op == "+":
                v = x.value + y.value
            elif op == "-":
                v = x.value - y.value
            elif op == "*":
                v = x.value * y.value
            elif y.value == 0:
                return P(None, text, inputs, defs, "division by zero")
            else:
                v = x.value / y.value
            if not math.isfinite(v):
                return P(None, text, inputs, defs, "result out of range")
            return P(v, text, inputs, defs)

        return self.zip([a, b], f)

    def _int(self, node: Node) -> int:
        assert isinstance(node, Num)
        return int(node.value)

    def _series(self, v: Val) -> SV:
        if isinstance(v, CV):
            return SV(dict.fromkeys(self.frame.periods, v.pt))
        return v

    def call(self, node: Call) -> Val:
        fn, args = node.fn, node.args
        src = to_source(args[0])
        if fn in ("sum", "avg", "min", "max"):
            vals = [self.ev(a) for a in args]
            if len(vals) == 1:
                self.unit_hint = self.unit(args[0])
                return self.reduce(fn, vals[0], src)
            return self.zip(vals, lambda ps: self.elementwise(fn, ps))
        if fn == "abs":
            return self.map1(self.ev(args[0]), lambda p: P(None if p.value is None else abs(p.value), f"|{p.text}|",
                                                           p.inputs, p.defs, p.note))
        if fn == "pct_of":
            return self.binary("/", self.ev(args[0]), self.ev(args[1]))
        unit = self.unit(args[0])
        x = self._series(self.ev(args[0]))
        if fn == "lag":
            return self.shift(x, self._int(args[1]))
        if fn == "yoy":
            k = 12 // self.frame.months
            return self.growth(x, k, f"year over year of {src}")
        if fn == "mom":
            per = {"month": "month over month", "quarter": "quarter over quarter", "year": "year over year"}[self.frame.target]
            return self.growth(x, 1, f"{per} of {src}")
        if fn == "cmgr":
            months = self._int(args[1])
            if months % self.frame.months:
                raise DSLError(f"cmgr({src}, {months}) needs a whole number of {self.frame.target}s: "
                               f"use a multiple of {self.frame.months} months")
            return self.cmgr(x, months, src)
        if fn == "rolling":
            return self.rolling(x, self._int(args[1]), src, unit)
        if fn == "cumsum":
            return self.cumsum(x, src, unit)
        raise DSLError(f"unknown function '{fn}'")

    def elementwise(self, fn: str, ps: list[P]) -> P:
        inputs, defs = _merge(*ps)
        text = f"{fn}({', '.join(p.text for p in ps)})"
        vals = [p.value for p in ps]
        if any(v is None for v in vals):
            return P(None, text, inputs, defs, next(p.note for p in ps if p.value is None))
        v = {"sum": sum(vals), "avg": sum(vals) / len(vals), "min": min(vals), "max": max(vals)}[fn]
        if not math.isfinite(v):
            return P(None, text, inputs, defs, OUT_OF_RANGE)
        return P(v, text, inputs, defs)

    def reduce(self, fn: str, v: Val, src: str) -> Val:
        if isinstance(v, CV):
            return v
        ps = [v.pts[g] for g in self.window if g in v.pts and v.pts[g].value is not None]
        if not ps:
            return CV(P(None, f"{fn}({src})", note="no values in the window"))
        vals = [p.value for p in ps]
        unit = self.unit_hint
        r = {"sum": sum(vals), "avg": sum(vals) / len(vals), "min": min(vals), "max": max(vals)}[fn]
        inputs, _ = _merge(*ps)
        if not math.isfinite(r):
            return CV(P(None, f"{fn}({src})", inputs, note=OUT_OF_RANGE))
        defs: list[str] = []
        span = f"{label_period(self.window[0])}–{label_period(self.window[-1])}"
        shown = ", ".join(_fmt(x, unit) for x in vals) if len(vals) <= 12 else f"{len(vals)} values"
        defs.append(f"{fn} of {src} over {span}: ({shown}) = {_fmt(r, unit)}")
        return CV(P(r, f"{fn}({src}) {_fmt(r, unit)}", inputs, defs, boxed=True))

    def shift(self, x: SV, k: int) -> SV:
        out: dict[str, P] = {}
        for i, g in enumerate(self.frame.periods):
            if i - k < 0:
                out[g] = P(None, "n/a", note=f"no value {k} period{'s' if k > 1 else ''} earlier")
                continue
            q = self.frame.periods[i - k]
            p = x.pts[q]
            out[g] = P(p.value, f"{p.text} ({label_period(q)})", p.inputs, p.defs, p.note, p.boxed)
        return SV(out)

    def growth(self, x: SV, k: int, what: str) -> SV:
        out: dict[str, P] = {}
        for i, g in enumerate(self.frame.periods):
            cur = x.pts[g]
            if i - k < 0:
                out[g] = P(None, f"{what} n/a", note="not enough history")
                continue
            q = self.frame.periods[i - k]
            prev = x.pts[q]
            inputs, defs = _merge(prev, cur)
            if cur.value is None or prev.value is None or prev.value == 0:
                out[g] = P(None, f"{what} n/a", inputs, defs, "missing or zero base")
                continue
            v = cur.value / prev.value - 1
            if not math.isfinite(v):
                out[g] = P(None, f"{what} n/a", inputs, defs, OUT_OF_RANGE)
                continue
            defs.append(f"{what}: {_fmt(cur.value)} ({label_period(g)}) ÷ {_fmt(prev.value)} ({label_period(q)}) − 1 = {_fmt(v, 'pct')}")
            out[g] = P(v, f"growth {_fmt(v, 'pct')}", inputs, defs, boxed=True)
        return SV(out)

    def cmgr(self, x: SV, months: int, src: str) -> SV:
        k = months // self.frame.months
        out: dict[str, P] = {}
        for i, g in enumerate(self.frame.periods):
            if i - k < 0:
                out[g] = P(None, "cmgr n/a", note="not enough history")
                continue
            q = self.frame.periods[i - k]
            start, end = x.pts[q], x.pts[g]
            inputs, defs = _merge(start, end)
            if start.value is None or end.value is None or start.value <= 0 or end.value <= 0:
                out[g] = P(None, "cmgr n/a", inputs, defs, "needs positive values at both ends")
                continue
            try:
                v = (end.value / start.value) ** (1 / months) - 1
            except OverflowError:
                v = math.inf
            if not math.isfinite(v):
                out[g] = P(None, "cmgr n/a", inputs, defs, OUT_OF_RANGE)
                continue
            defs.append(f"compound monthly growth of {src} over {months} months: ({_fmt(end.value)} ({label_period(g)}) ÷ "
                        f"{_fmt(start.value)} ({label_period(q)}))^(1/{months}) − 1 = {_fmt(v, 'pct')}")
            out[g] = P(v, f"cmgr {_fmt(v, 'pct')}", inputs, defs, boxed=True)
        return SV(out)

    def rolling(self, x: SV, n: int, src: str, unit: str | None) -> SV:
        out: dict[str, P] = {}
        for i, g in enumerate(self.frame.periods):
            if i - n + 1 < 0:
                out[g] = P(None, "rolling n/a", note="not enough history")
                continue
            span = self.frame.periods[i - n + 1:i + 1]
            ps = [x.pts[q] for q in span]
            inputs, defs = _merge(*ps)
            defs = []
            if any(p.value is None for p in ps):
                out[g] = P(None, "rolling n/a", inputs, defs, "a value in the window is missing")
                continue
            v = sum(p.value for p in ps) / n
            if not math.isfinite(v):
                out[g] = P(None, "rolling n/a", inputs, defs, OUT_OF_RANGE)
                continue
            shown = ", ".join(_fmt(p.value, unit) for p in ps)
            defs.append(f"{n}-period average of {src}, {label_period(span[0])}–{label_period(span[-1])}: ({shown}) ÷ {n} = {_fmt(v, unit)}")
            out[g] = P(v, f"rolling avg {_fmt(v, unit)}", inputs, defs, boxed=True)
        return SV(out)

    def cumsum(self, x: SV, src: str, unit: str | None) -> SV:
        out: dict[str, P] = {}
        start = self.frame.index(self.window[0]) if self.window else 0
        for i, g in enumerate(self.frame.periods):
            j = start if i >= start else 0
            span = self.frame.periods[j:i + 1]
            ps = [x.pts[q] for q in span]
            inputs, defs = _merge(*ps)
            defs = []
            if any(p.value is None for p in ps):
                out[g] = P(None, "running total n/a", inputs, defs, "a value in the range is missing")
                continue
            v = sum(p.value for p in ps)
            if not math.isfinite(v):
                out[g] = P(None, "running total n/a", inputs, defs, OUT_OF_RANGE)
                continue
            shown = " + ".join(_fmt(p.value, unit) for p in ps) if len(ps) <= 12 else f"{len(ps)} values"
            defs.append(f"running total of {src}, {label_period(span[0])}–{label_period(g)}: {shown} = {_fmt(v, unit)}")
            out[g] = P(v, f"running total {_fmt(v, unit)}", inputs, defs, boxed=True)
        return SV(out)


# ---------------------------------------------------------------- resolution and missing data

def _field_hints(ctx: TruthContext) -> dict[str, str]:
    credits = "SR&ED credits or grants" if str(ctx.profile.get("country", "")).upper() == "CA" else "tax credits or grants"
    return {
        "non_dilutive_income": f"non-dilutive income ({credits})",
        "net_income": "net income (or revenue and costs)",
        "revenue.recurring": "recurring (subscription) revenue",
        "revenue.total": "revenue",
        "cogs": "cost of revenue",
        "opex.customer_success": "a customer success or support cost line",
        "cash_balance": "a cash balance (bank statement or balance sheet)",
        "cohort_mrr": "a cohort table (signup cohort × period MRR)",
        "customers.count": "customer counts by period",
        "customers.new": "new-customer counts by period",
        "customers.churned": "churned-customer counts by period",
        "headcount.total": "headcount by period",
    }


def _missing_reason(ctx: TruthContext, label: str, needs: list[str]) -> str:
    hints = _field_hints(ctx)
    parts = [hints.get(n) or (_lower(FIELDS[n].label) if n in FIELDS else n) for n in needs]
    joined = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    return f"{label} needs {joined}. Map it in your financials or upload a file that has it."


def _slug(ref: str) -> str:
    s = "".join(c if c.isalnum() or c in "._" else "_" for c in ref.strip())[:60].strip("_")
    return s or "widget"


def _missing_for(node: Node, ctx: TruthContext, ref: str, label: str) -> MissingFigure | None:
    needs: list[str] = []
    m = ctx.model
    for n in names(node):
        if isinstance(n, Raw):
            if n.key not in m.raw:
                needs.append(f'raw column "{n.key}"')
            continue
        kind = name_kind(n.id)
        if kind == "field":
            if not m.has(n.id):
                needs.append(n.id)
        elif kind == "helper":
            needs += [f for f in HELPERS[n.id] if not m.has(f)]
        else:
            f = ctx.figures.get(n.id)
            if isinstance(f, MissingFigure):
                return f
            if f is None:
                return MissingFigure(id=n.id, label=n.id, needs=[n.id],
                                     reason=f"{n.id} isn't available for this company's data")
    needs = _dedupe(needs)
    if not needs:
        return None
    return MissingFigure(id=_slug(ref), label=label, needs=needs, reason=_missing_reason(ctx, label, needs))


def metric_series_expr(metric_id: str, ctx: TruthContext, frame_months: int) -> str | None:
    """The per-period series behind a metric id, as a DSL expression (None when it's a single figure)."""
    has_credits = ctx.model.has("non_dilutive_income")
    recent = 2 if frame_months == 1 else frame_months
    return {
        "mrr": "mrr", "arr": "arr", "revenue": "revenue",
        "burn": "burn_ex_non_dilutive" if has_credits else "burn",
        "burn_incl_credits": "burn",
        "gross_margin": "gross_margin", "gross_margin_incl_cs": "gross_margin_incl_cs",
        "cash_balance": "cash_balance",
        "cmgr_12m": "cmgr(revenue.recurring, 12)",
        "cmgr_recent": f"cmgr(revenue.recurring, {recent})",
        "revenue_growth": "mom(revenue)",
        "revenue_growth_yoy": "yoy(revenue)",
    }.get(metric_id)


def _is_metric(ref: str, ctx: TruthContext) -> bool:
    return ref in ctx.figures or ref in METRIC_IDS


def _no_running_total_of_balances(node: Node) -> None:
    """cumsum() over a period-end balance (cash, customers, headcount) adds up snapshots: refuse it."""
    if isinstance(node, Call):
        if node.fn == "cumsum":
            stocks = [n.id for n in names(node.args[0])
                      if isinstance(n, Name) and n.id in FIELDS and FIELDS[n.id].agg == "last"]
            if stocks:
                what = _lower(FIELDS[stocks[0]].label)
                raise DSLError(f"cumsum() adds values up over time, but {what} is a balance at the end of each period, "
                               f"so a running total of it has no meaning. Chart {stocks[0]} on its own instead.")
        for a in node.args:
            _no_running_total_of_balances(a)
    elif isinstance(node, Bin):
        _no_running_total_of_balances(node.left)
        _no_running_total_of_balances(node.right)
    elif isinstance(node, Neg):
        _no_running_total_of_balances(node.operand)


@dataclass
class _Resolved:
    ref: str
    label: str
    node: Node | None = None
    figure: Figure | None = None
    missing: MissingFigure | None = None


def _resolve(s: SeriesSpec, ctx: TruthContext, frame: Frame, scalar: bool, title: str) -> _Resolved:
    ref = s.ref.strip()
    if _is_metric(ref, ctx):
        f = ctx.figures.get(ref)
        label = s.label or (f.label if f is not None and f.label else ref)
        if isinstance(f, MissingFigure):
            return _Resolved(ref, label, missing=f)
        if scalar:
            if f is None:
                return _Resolved(ref, label, missing=MissingFigure(id=ref, label=label, needs=[ref],
                                                                   reason=f"{label} isn't available for this company's data"))
            return _Resolved(ref, label, figure=f)
        expr = metric_series_expr(ref, ctx, frame.months)
        if expr is None:
            raise DSLError(f"'{ref}' is a single figure, not a series; show it in a kpi or gauge_ring widget")
        if ref == "burn" and not s.label:
            label = "Burn ex-credits" if ctx.model.has("non_dilutive_income") else "Burn"
        node = parse(expr)
    else:
        node = parse(ref)
        _no_running_total_of_balances(node)
        label = s.label or (HELPER_LABELS.get(ref, "").capitalize() if ref in HELPERS else
                            FIELDS[ref].label if ref in FIELDS else ref if len(ref) <= 40 else title)
    missing = _missing_for(node, ctx, ref, label)
    return _Resolved(ref, label, node=node, missing=missing)


# ---------------------------------------------------------------- windows and provenance

def period_bounds(p: str) -> tuple[tuple[int, int], tuple[int, int]]:
    if "-Q" in p:
        y, q = p.split("-Q")
        return (int(y), int(q) * 3 - 2), (int(y), int(q) * 3)
    if "-" in p:
        y, m = p.split("-")
        return (int(y), int(m)), (int(y), int(m))
    return (int(p), 1), (int(p), 12)


def apply_window(periods: list[str], window: Window | None) -> list[str]:
    if window is None:
        return list(periods)
    out = list(periods)
    if window.from_:
        lo = period_bounds(window.from_)[0]
        out = [p for p in out if period_bounds(p)[1] >= lo]
    if window.to:
        hi = period_bounds(window.to)[1]
        out = [p for p in out if period_bounds(p)[0] <= hi]
    if window.last_n:
        out = out[-window.last_n:]
    return out


def _source(ctx: TruthContext, inputs: list[InputRef]) -> PointSource | None:
    m = ctx.model
    by_field: dict[str, list[str]] = {}
    for i in inputs:
        if i.field and i.field in FIELDS and i.period:
            by_field.setdefault(i.field, []).append(i.period)
    if by_field:
        refs, first = [], None
        for fid, ps in by_field.items():
            ds, ref, kind = m.source_ref(fid, sorted(set(ps), key=period_sort_key))
            refs.append(ref)
            first = first or (ds, kind)
        kind = first[1] if first[1] in ("csv", "xlsx") else "derived"
        return PointSource(kind=kind, ref="; ".join(_dedupe(refs))[:300], dataset_id=first[0])
    raws = [i for i in inputs if i.raw]
    if raws:
        dsi = m.datasets.get(raws[0].dataset_id or "")
        kind = dsi.upload_kind if dsi and dsi.upload_kind in ("csv", "xlsx") else "csv"
        return PointSource(kind=kind, ref="; ".join(_dedupe([i.ref or "" for i in raws])), dataset_id=raws[0].dataset_id)
    figs = [i for i in inputs if i.figure_id]
    if figs:
        f = ctx.figures.get(figs[0].figure_id or "")
        if isinstance(f, Figure):
            return _psource(f.source)
    return None


def _psource(s: Source) -> PointSource:
    return PointSource(kind=s.kind, ref=s.ref or "", dataset_id=s.dataset_id)


def _point(ctx: TruthContext, g: str, p: P, unit: str | None, leaf: bool) -> Point:
    if p.value is None:
        formula = f"{label_period(g)}: no value" + (f" ({p.note})" if p.note else "")
    else:
        main = p.text if leaf or p.boxed else f"{p.text} = {_fmt(p.value, unit)}"
        formula = " · ".join([f"{label_period(g)}: {main}", *p.defs])
    return Point(period=g, label=label_period(g), value=p.value, formula=formula, inputs=p.inputs,
                 source=_source(ctx, p.inputs))


def _public_unit(u: str | None, ctx: TruthContext) -> str | None:
    return ctx.currency if u == "money" else u


# ---------------------------------------------------------------- KPI and cohort paths

def _kpi_item(s: SeriesSpec, ctx: TruthContext, frame: Frame, ev: Evaluator, title: str) -> KpiItem:
    r = _resolve(s, ctx, frame, scalar=True, title=title)
    if r.missing:
        return KpiItem(id=r.missing.id, label=r.label, missing=r.missing)
    if r.figure and not _finite(r.figure.value):
        return KpiItem(id=r.figure.id, label=r.label, missing=MissingFigure(
            id=r.figure.id, label=r.label, needs=[], reason=f"{r.label} is out of range, so it can't be shown"))
    if r.figure:
        f = r.figure
        inputs = [InputRef(figure_id=i.figure_id, field=i.column, period=i.period, value=i.value, dataset_id=i.dataset_id)
                  for i in f.inputs]
        return KpiItem(id=f.id, label=r.label, value=f.value, unit=f.unit, display=f.display, formula=f.formula,
                       inputs=inputs, source=_psource(f.source), kind=f.kind, period=f.period)
    assert r.node is not None
    v = ev.ev(r.node)
    unit = _public_unit(ev.unit(r.node), ctx)
    if isinstance(v, CV):
        g, p = (frame.periods[-1] if frame.periods else ""), v.pt
    else:
        avail = [g for g in ev.window if v.pts[g].value is not None]
        if not avail:
            return KpiItem(id=_slug(r.ref), label=r.label, missing=MissingFigure(
                id=_slug(r.ref), label=r.label, needs=[], reason=f"{r.label} has no values in the selected window"))
        g = avail[-1]
        p = v.pts[g]
    if not _finite(p.value):
        # "sum(revenue)/0", or a window with no data, has nothing to show: missing, never "n/a" as a value
        why = f" ({p.note})" if p.note else ""
        return KpiItem(id=_slug(r.ref), label=r.label, missing=MissingFigure(
            id=_slug(r.ref), label=r.label, needs=[], reason=f"{r.label} has no value in the selected window{why}"))
    pt = _point(ctx, g, p, unit, isinstance(r.node, Name | Raw))
    if isinstance(v, CV):
        main = p.text if p.boxed or isinstance(r.node, Name | Raw) else f"{p.text} = {_fmt(p.value, unit)}"
        pt.formula = " · ".join([main, *p.defs])
    display = fmt_value(p.value, unit) if unit else _fmt(p.value)
    return KpiItem(id=_slug(r.ref), label=r.label, value=p.value, unit=unit, display=display, formula=pt.formula,
                   inputs=pt.inputs, source=pt.source, period=g if isinstance(v, SV) else None)


def _cohort_series(spec: WidgetSpec, ctx: TruthContext, ref: str, out: EvaluatedWidget) -> EvaluatedWidget:
    m = ctx.model
    if not m.cohort_mrr:
        mf = MissingFigure(id=ref, label="Revenue retention by cohort", needs=["cohort_mrr"],
                           reason=_missing_reason(ctx, "Retention by cohort", ["cohort_mrr"]), group="recurring")
        return out.model_copy(update={"status": "missing", "missing": mf})
    ds = m.table_sources.get("cohort_mrr")
    periods = sorted({p for by_p in m.cohort_mrr.values() for p in by_p}, key=period_sort_key)
    periods = apply_window(periods, spec.window)
    if spec.group_by and spec.group_by != ("quarter" if periods and "-Q" in periods[0] else "month"):
        out.notes.append("Cohort tables are shown at their own granularity.")
    retention = ref == "cohort_retention"
    series = []
    for cohort in sorted(m.cohort_mrr, key=lambda c: period_sort_key(c) if c[:4].isdigit() else (0, 0)):
        by_p = m.cohort_mrr[cohort]
        base_p = next((p for p in sorted(by_p, key=period_sort_key) if by_p[p] > 0), None)
        clabel = label_period(cohort) if cohort[:4].isdigit() else cohort
        pts = []
        for p in periods:
            v = by_p.get(p)
            src = PointSource(kind="csv", ref=f"cohort table · cohort {clabel}", dataset_id=ds)
            if v is None or (retention and base_p is None):
                pts.append(Point(period=p, label=label_period(p), value=None,
                                 formula=f"{label_period(p)}: no MRR for the {clabel} cohort", source=src))
                continue
            inputs = [InputRef(field="cohort_mrr", period=p, value=v, dataset_id=ds, ref=f"cohort {clabel}")]
            if retention:
                base = by_p[base_p]
                inputs.append(InputRef(field="cohort_mrr", period=base_p, value=base, dataset_id=ds, ref=f"cohort {clabel}"))
                value = v / base
                formula = (f"{label_period(p)}: {clabel} cohort MRR {_fmt(v)} ÷ its MRR in {label_period(base_p)} "
                           f"{_fmt(base)} = {_fmt(value, 'pct')}")
            else:
                value = v
                formula = f"{label_period(p)}: {clabel} cohort MRR {_fmt(v)}"
            pts.append(Point(period=p, label=label_period(p), value=value, formula=formula, inputs=inputs, source=src))
        series.append(EvaluatedSeries(label=clabel, ref=ref, unit="pct" if retention else ctx.currency, points=pts))
    return out.model_copy(update={"periods": periods, "period_labels": [label_period(p) for p in periods],
                                  "series": series, "granularity": "quarter" if periods and "-Q" in periods[0] else "month"})


# ---------------------------------------------------------------- waterfall

def _waterfall(base: EvaluatedSeries) -> list[EvaluatedSeries]:
    """Each step is a bar from the running total before it to the running total after it.

    The invisible base bar holds the running total before the step; the change v is split exactly into
    up = max(v, 0) and down = min(v, 0) (v = up + down), and the chart stacks base, up and down with
    `stackStrategy: "all"`, so the bars land on the running total after the step on either side of zero.
    The change keeps its sign, so the tooltip, Table view and explain card show the change itself, never
    a helper height. (Up and down are both defined for every step: ECharts stacks "all" onto the previous
    series even when it is empty, so a gap there would hide the bar.)
    """
    helper, up, down = [], [], []
    cum = 0.0
    for pt in base.points:
        v = pt.value
        after = cum + v if v is not None else None
        if v is None or not _finite(after):
            note = f" ({OUT_OF_RANGE})" if v is not None else ""
            for lst in (helper, up, down):
                lst.append(pt.model_copy(update={"value": None, "formula": pt.formula + note}))
            continue
        before, cum = cum, after
        note = f" · running total {_fmt(before)} → {_fmt(after)}"
        helper.append(pt.model_copy(update={"value": before, "inputs": [], "source": None,
                                            "formula": f"{pt.label}: running total before this step {_fmt(before)}"}))
        up.append(pt.model_copy(update={"value": max(v, 0.0), "formula": pt.formula + note if v > 0 else
                                        f"{pt.label}: no increase this step" + note}))
        down.append(pt.model_copy(update={"value": min(v, 0.0), "formula": pt.formula + note if v < 0 else
                                          f"{pt.label}: no decrease this step" + note}))
    common = {"ref": base.ref, "unit": base.unit, "axis": base.axis}
    return [
        EvaluatedSeries(label=f"{base.label} (base)", role="waterfall_base", points=helper, **common),
        EvaluatedSeries(label=f"{base.label} up", role="waterfall_up", points=up, **common),
        EvaluatedSeries(label=f"{base.label} down", role="waterfall_down", points=down, **common),
    ]


# ---------------------------------------------------------------- entry point

def evaluate_widget(spec: WidgetSpec | dict[str, Any], ctx: TruthContext) -> EvaluatedWidget:
    """Compute a widget's data, with provenance on every point. Never raises on bad specs."""
    try:
        spec = spec if isinstance(spec, WidgetSpec) else WidgetSpec.model_validate(spec)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(x) for x in first.get("loc", ()))
        return EvaluatedWidget(status="error", template=str(getattr(spec, "get", lambda *_: "")("template") or ""),
                               title="", error=f"Invalid widget spec at {where or 'root'}: {first.get('msg')}")
    base = EvaluatedWidget(status="ok", template=spec.template, title=spec.title, spec_hash=spec_hash(spec),
                           currency=ctx.currency)
    try:
        return _evaluate(spec, ctx, base)
    except DSLError as e:
        return base.model_copy(update={"status": "error", "error": e.message})
    except ArithmeticError:  # an overflow the operator guards missed: one error tile, not a failed dashboard
        return base.model_copy(update={"status": "error", "error": "A value in this widget is out of range."})


def _evaluate(spec: WidgetSpec, ctx: TruthContext, out: EvaluatedWidget) -> EvaluatedWidget:
    refs = [s.ref.strip() for s in spec.series]
    if refs[0] in COHORT_REFS:
        return _cohort_series(spec, ctx, refs[0], out)
    frame = Frame(ctx, spec.group_by)
    out.notes.extend(frame.notes)
    out.granularity = frame.target
    window = apply_window(frame.periods, spec.window)
    ev = Evaluator(ctx, frame, window)

    if spec.template in SCALAR_TEMPLATES:
        items = [_kpi_item(s, ctx, frame, ev, spec.title) for s in spec.series]
        if items[0].missing:
            return out.model_copy(update={"status": "missing", "missing": items[0].missing,
                                          "kpi": Kpi(primary=items[0], secondary=items[1:])})
        return out.model_copy(update={"kpi": Kpi(primary=items[0], secondary=items[1:]),
                                      "mark_lines": _mark_lines(spec, ctx, ev, frame)})

    if not window:
        return out.model_copy(update={"status": "error", "error": "No periods in the selected window"})

    if spec.template == "scatter" and len(spec.series) < 2:
        return out.model_copy(update={"status": "error", "error": "A scatter needs two series: x then y"})
    resolved = [_resolve(s, ctx, frame, scalar=False, title=spec.title) for s in spec.series]
    present = [(s, r) for s, r in zip(spec.series, resolved, strict=True) if not r.missing]
    missing = [r.missing for r in resolved if r.missing]
    if not present or (spec.template == "scatter" and len(present) < 2):
        return out.model_copy(update={"status": "missing", "missing": missing[0], "missing_series": missing})
    for mf in missing:
        out.notes.append(f"Left out {mf.label or mf.id}: {mf.reason}")
    out.missing_series = missing

    built: list[tuple[SeriesSpec, _Resolved, SV, str | None, Role, str]] = []
    k_compare = {"previous_period": 1, "yoy": 12 // frame.months}.get(spec.compare or "")
    for s, r in present:
        assert r.node is not None
        unit = spec.presentation.unit or _public_unit(ev.unit(r.node), ctx)
        val = ev._series(ev.ev(r.node))
        built.append((s, r, val, unit, "value", r.label))
        if k_compare:
            suffix = "previous period" if spec.compare == "previous_period" else "a year earlier"
            built.append((s, r, ev.shift(val, k_compare), unit, "compare", f"{r.label} ({suffix})"))

    # trim leading/trailing periods where no value series has data
    has = [g for g in window if any(v.pts[g].value is not None for _, _, v, _, role, _ in built if role == "value")]
    if not has:
        mf = MissingFigure(id=_slug(refs[0]), label=spec.title, needs=[],
                           reason=f"{spec.title} has no values in the selected window" +
                                  (f" ({frame.notes[-1]})" if frame.notes else ""))
        return out.model_copy(update={"status": "missing", "missing": mf})
    periods = window[window.index(has[0]):window.index(has[-1]) + 1]

    series: list[EvaluatedSeries] = []
    for s, r, val, unit, role, label in built:
        leaf = isinstance(r.node, Name | Raw) and role == "value"
        pts = [_point(ctx, g, val.pts[g], unit, leaf) for g in periods]
        series.append(EvaluatedSeries(label=label, ref=r.ref, unit=unit, axis=s.axis,
                                      style="dashed" if role == "compare" else s.style, role=role, points=pts))
    if spec.template == "waterfall":
        series = _waterfall(series[0])
    return out.model_copy(update={"periods": periods, "period_labels": [label_period(g) for g in periods],
                                  "series": series, "mark_lines": _mark_lines(spec, ctx, ev, frame)})


def _mark_lines(spec: WidgetSpec, ctx: TruthContext, ev: Evaluator, frame: Frame) -> list[MarkLineValue]:
    out = []
    for ml in spec.presentation.mark_lines:
        item = _kpi_item(SeriesSpec(ref=ml.value_ref, label=ml.label), ctx, frame, ev, spec.title)
        if item.missing or item.value is None:
            continue
        out.append(MarkLineValue(label=ml.label, value=item.value, unit=item.unit, formula=item.formula, source=item.source))
    return out
