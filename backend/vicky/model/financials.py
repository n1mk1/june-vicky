"""Assemble confirmed datasets + mappings into one canonical, period-indexed model.

Every value keeps provenance (dataset, column(s), source row) so figures and chart points can
explain themselves. Missing totals are derived from components and marked as derived.

Money columns in another currency (the mapping's unit) are converted into the model currency at
Bank of Canada rates for their own period (`vicky.model.fx`); each cell keeps the rates it used.
A column whose rate isn't published for a period stays a raw column for that period.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from vicky.model.canonical import FIELDS, OPEX_CATEGORIES
from vicky.model.currencies import CURRENCY_CODES
from vicky.model.fx import SOURCE_NAME, FxRate, Rates
from vicky.model.loader import period_sort_key, quarter_of


@dataclass
class Cell:
    value: float
    dataset_id: str | None
    columns: list[str]
    rows: list[int]
    upload_kind: str = "csv"
    derived: str | None = None
    fx: list[FxRate] = field(default_factory=list)


@dataclass
class DatasetInput:
    id: str
    name: str
    table_kind: str
    granularity: str
    transposed: bool
    rows: list[dict]
    mapping: list[dict]
    upload_kind: str = "csv"


@dataclass
class CanonicalModel:
    currency: str
    granularity: str
    periods: list[str] = field(default_factory=list)
    cells: dict[str, dict[str, Cell]] = field(default_factory=dict)
    raw: dict[str, dict[str, float]] = field(default_factory=dict)
    raw_source: dict[str, tuple[str, str]] = field(default_factory=dict)
    customer_mrr: dict[str, dict[str, float]] = field(default_factory=dict)
    cohort_mrr: dict[str, dict[str, float]] = field(default_factory=dict)
    table_sources: dict[str, str] = field(default_factory=dict)
    datasets: dict[str, DatasetInput] = field(default_factory=dict)
    fx_skipped: list[str] = field(default_factory=list)  # "<dataset>:<column> <period>" left unconverted
    table_fx: dict[str, str] = field(default_factory=dict)  # table kind → " · converted …" for its source refs
    fx: Rates | None = None

    def convert(self, val: float, src: str, period: str, agg: str = "sum") -> tuple[float, FxRate | None] | None:
        """A `src` amount for a period in the model currency (with the rate used), or None without a rate."""
        if src == self.currency or src not in CURRENCY_CODES:
            return val, None
        r = self.fx.rate(src, self.currency, period, "end" if agg == "last" else "avg") if self.fx else None
        return (val * r.value, r) if r else None

    @property
    def months_per_period(self) -> int:
        return 3 if self.granularity == "quarter" else 12 if self.granularity == "year" else 1

    def has(self, fid: str) -> bool:
        return any(c is not None for c in self.cells.get(fid, {}).values())

    def series(self, fid: str) -> dict[str, float]:
        return {p: c.value for p, c in self.cells.get(fid, {}).items()}

    def value(self, fid: str, period: str) -> float | None:
        c = self.cells.get(fid, {}).get(period)
        return c.value if c else None

    def periods_with(self, fid: str) -> list[str]:
        return [p for p in self.periods if p in self.cells.get(fid, {})]

    def latest(self, fid: str) -> str | None:
        ps = self.periods_with(fid)
        return ps[-1] if ps else None

    def cell(self, fid: str, period: str) -> Cell | None:
        return self.cells.get(fid, {}).get(period)

    def source_ref(self, fid: str, periods: list[str]) -> tuple[str | None, str, str]:
        """(dataset_id, human ref, upload kind) for a field over some periods."""
        cells = [self.cell(fid, p) for p in periods]
        cells = [c for c in cells if c]
        if not cells:
            return None, "", "derived"
        ds = cells[0].dataset_id
        kind = cells[0].upload_kind
        if any(c.derived for c in cells):
            return ds, f"derived: {cells[0].derived}", kind
        dsi = self.datasets.get(ds or "")
        cols = sorted({col for c in cells for col in c.columns})
        if dsi and dsi.transposed:
            ref = f"{', '.join(cols)} · {periods[0]}" + (f"–{periods[-1]}" if len(periods) > 1 else "")
        else:
            rows = sorted({r for c in cells for r in c.rows})
            ref = f"row {rows[0]}" if len(rows) == 1 else f"rows {rows[0]}–{rows[-1]}"
            ref += f" · {', '.join(cols)}"
        name = dsi.name if dsi else ""
        return ds, f"{name} {ref}".strip() + fx_note([r for c in cells for r in c.fx], self.currency), kind


def fx_note(rates: list[FxRate], currency: str) -> str:
    """" · converted …" for a source reference, or "" when nothing was converted."""
    if not rates:
        return ""
    if len(rates) == 1:
        return f" · converted {rates[0].note()}"
    srcs = "/".join(sorted({r.src.upper() for r in rates}))
    return f" · converted {srcs}→{currency.upper()} at {SOURCE_NAME} rates for each period"


def _to_target(period: str, granularity: str, target: str) -> str | None:
    if granularity == target:
        return period
    if granularity == "month" and target == "quarter":
        return quarter_of(period)
    return None


def column_currency(mapping: dict, default: str) -> str:
    """The currency a mapped money column is in: its mapping unit when that is a currency."""
    u = str(mapping.get("unit") or "").lower()
    return u if u in CURRENCY_CODES else default


def build_model(datasets: list[DatasetInput], currency: str, target_granularity: str | None = None,
                fx: Rates | None = None) -> CanonicalModel:
    series_ds = [d for d in datasets if d.table_kind == "series"]
    grans = {d.granularity for d in series_ds if d.granularity in ("month", "quarter", "year")}
    if target_granularity not in grans:
        target_granularity = "month" if "month" in grans else "quarter" if "quarter" in grans else (next(iter(grans)) if grans else "month")
    model = CanonicalModel(currency=currency.lower(), granularity=target_granularity, fx=fx)
    convert = model.convert

    for d in datasets:
        model.datasets[d.id] = d
        m_by_col = {m["source_column"]: m.get("canonical_field") for m in d.mapping}
        cur_by_col = {m["source_column"]: column_currency(m, model.currency) for m in d.mapping}
        foreign = {c for c, u in cur_by_col.items() if u != model.currency}  # raw columns in a currency convert too
        if d.table_kind == "series":
            accum: dict[str, dict[str, Cell]] = defaultdict(dict)
            for i, row in enumerate(d.rows):
                p = _to_target(row["period"], d.granularity, target_granularity)
                if p is None:
                    continue
                src_row = i + 2
                for col, val in row.items():
                    if col == "period" or not isinstance(val, int | float):
                        continue
                    target = m_by_col.get(col)
                    rate = None
                    if (target in FIELDS and FIELDS[target].kind == "money") or col in foreign:
                        agg_ = FIELDS[target].agg if target in FIELDS else "sum"
                        conv = convert(float(val), cur_by_col.get(col, model.currency), row["period"], agg_)
                        if conv is None:
                            # No published rate for this period: left out rather than shown in the wrong currency.
                            model.fx_skipped.append(f"{d.name}:{col} {row['period']}")
                            continue
                        val, rate = conv
                    if target in (None, "period") or target not in FIELDS:
                        key = f"{d.name}:{col}"
                        model.raw.setdefault(key, {})
                        model.raw[key][p] = model.raw[key].get(p, 0.0) + float(val)
                        model.raw_source[key] = (d.id, col)
                        continue
                    agg = FIELDS[target].agg
                    cell = accum[target].get(p)
                    if cell is None:
                        accum[target][p] = Cell(float(val), d.id, [col], [src_row], d.upload_kind, fx=[rate] if rate else [])
                    else:
                        if agg == "sum" and (col not in cell.columns or d.granularity != target_granularity):
                            cell.value += float(val)
                        elif agg == "last":
                            cell.value = float(val)
                            cell.fx = []
                        if rate:
                            cell.fx.append(rate)
                        if col not in cell.columns:
                            cell.columns.append(col)
                        cell.rows.append(src_row)
            for fid, by_p in accum.items():
                model.cells.setdefault(fid, {}).update(by_p)
        elif d.table_kind in ("customer_mrr", "cohort_mrr"):
            dim_col = next((c for c, t in m_by_col.items() if t in ("dim.customer", "dim.cohort")), None)
            val_col = next((c for c, t in m_by_col.items() if t == "value.mrr"), None)
            target_table = model.customer_mrr if d.table_kind == "customer_mrr" else model.cohort_mrr
            model.table_sources[d.table_kind] = d.id
            src_cur = cur_by_col.get(val_col, model.currency) if val_col else model.currency
            for row in d.rows:
                v = row.get(val_col) if val_col else None
                if v is None:
                    v = next((x for k, x in row.items() if k not in ("period", "dim") and isinstance(x, int | float)), None)
                if v is None:
                    continue
                conv = convert(float(v), src_cur, row["period"], "sum")
                if conv is None:
                    model.fx_skipped.append(f"{d.name}:{val_col} {row['period']}")
                    continue
                v = conv[0]
                if conv[1]:
                    model.table_fx[d.table_kind] = fx_note([conv[1], conv[1]], model.currency)
                dim = str(row.get("dim") if dim_col else row.get("dim"))
                if d.table_kind == "customer_mrr":
                    target_table.setdefault(row["period"], {})[dim] = float(v)
                else:
                    target_table.setdefault(dim, {})[row["period"]] = float(v)

    periods = set()
    for by_p in model.cells.values():
        periods.update(by_p)
    for by_p in model.raw.values():
        periods.update(by_p)
    model.periods = sorted(periods, key=period_sort_key)
    _derive(model)
    return model


def _derive(model: CanonicalModel) -> None:
    def put(fid: str, p: str, value: float, formula: str) -> None:
        model.cells.setdefault(fid, {})[p] = Cell(value, None, [], [], "derived", formula)

    for p in model.periods:
        rec, one = model.value("revenue.recurring", p), model.value("revenue.one_time", p)
        if model.value("revenue.total", p) is None and (rec is not None or one is not None):
            put("revenue.total", p, (rec or 0) + (one or 0), "recurring + one-time revenue")
        rev, cogs = model.value("revenue.total", p), model.value("cogs", p)
        if model.value("gross_profit", p) is None and rev is not None and cogs is not None:
            put("gross_profit", p, rev - cogs, "revenue − cost of revenue")
        cats = [model.value(c, p) for c in OPEX_CATEGORIES]
        if model.value("opex.total", p) is None and any(v is not None for v in cats):
            dep = model.value("depreciation", p) or 0
            put("opex.total", p, sum(v or 0 for v in cats) + dep, "sum of opex categories")
        gp, opex = model.value("gross_profit", p), model.value("opex.total", p)
        if model.value("operating_income", p) is None and gp is not None and opex is not None:
            put("operating_income", p, gp - opex, "gross profit − opex")
        oi = model.value("operating_income", p)
        if model.value("net_income", p) is None and oi is not None:
            nd = model.value("non_dilutive_income", p) or 0
            put("net_income", p, oi + nd, "operating income + non-dilutive income")


def model_summary(model: CanonicalModel) -> dict[str, Any]:
    return {
        "granularity": model.granularity,
        "periods": model.periods,
        "fields": {fid: len(by_p) for fid, by_p in model.cells.items()},
        "raw_columns": sorted(model.raw),
        "has_customer_mrr": bool(model.customer_mrr),
        "has_cohort_mrr": bool(model.cohort_mrr),
    }
