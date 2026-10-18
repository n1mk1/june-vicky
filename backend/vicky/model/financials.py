"""Assemble confirmed datasets + mappings into one canonical, period-indexed model.

Every value keeps provenance (dataset, column(s), source row) so figures and chart points can
explain themselves. Missing totals are derived from components and marked as derived.

Money columns in another currency (the mapping's unit) are converted into the model currency at
Bank of Canada rates for their own period (`vicky.model.fx`); each cell keeps the rates it used.
A cell whose rate isn't published for its period is left out, and the gap is recorded so a metric
it would have unlocked says why it is missing.

Cost columns printed as negatives ("(3,000)", a bank ledger's "AWS -1,300") are read as positive
costs. Months rolled into quarters only count for a complete quarter; a table at a granularity the
model can't use is left out. Both are stated in the model's notes.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from vicky.model.canonical import FIELDS, OPEX_CATEGORIES
from vicky.model.currencies import CURRENCY_CODES
from vicky.model.fx import SOURCE_NAME, FxRate, Rates
from vicky.model.loader import SRC_ROWS, period_sort_key, quarter_of

# Fields that are costs: a column of them shown mostly as negatives is read as positive amounts.
COST_FIELDS = {"cogs", "depreciation", *OPEX_CATEGORIES, "opex.total"}


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
    fx_gaps: dict[str, list[tuple[str, str]]] = field(
        default_factory=dict
    )  # field or table kind → [(src, period)]
    table_fx: dict[str, str] = field(
        default_factory=dict
    )  # table kind → " · converted …" for its source refs
    # The customer and cohort tables in their source currency (one currency per table, else empty): retention
    # and concentration are ratios, so exchange-rate moves must not show up in them.
    customer_mrr_src: dict[str, dict[str, float]] = field(default_factory=dict)
    cohort_mrr_src: dict[str, dict[str, float]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)  # what the build left out or reinterpreted, in plain words
    fx: Rates | None = None

    def convert(
        self, val: float, src: str, period: str, agg: str = "sum"
    ) -> tuple[float, FxRate | None] | None:
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
        dsi = self.datasets.get(ds or "")
        cols = sorted({col for c in cells for col in c.columns})
        if any(c.derived for c in cells):
            # A derived cell carries the file provenance of its inputs (dataset, columns), so it still points at the file.
            origin = f" (from {dsi.name} · {', '.join(cols)})" if dsi and cols else ""
            return (
                ds,
                f"derived: {cells[0].derived}{origin}"
                + fx_note([r for c in cells for r in c.fx], self.currency),
                kind,
            )
        if dsi and dsi.transposed:
            ref = f"{', '.join(cols)} · {periods[0]}" + (f"–{periods[-1]}" if len(periods) > 1 else "")
        else:
            rows = sorted({r for c in cells for r in c.rows})
            ref = f"row {rows[0]}" if len(rows) == 1 else f"rows {rows[0]}–{rows[-1]}"
            ref += f" · {', '.join(cols)}"
        name = dsi.name if dsi else ""
        return ds, f"{name} {ref}".strip() + fx_note([r for c in cells for r in c.fx], self.currency), kind


def fx_note(rates: list[FxRate], currency: str) -> str:
    """ " · converted …" for a source reference, or "" when nothing was converted."""
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


def _quarter_label(q: str) -> str:
    y, n = q.split("-Q")
    return f"Q{n} {y}"


def _mostly_negative(values: list) -> bool:
    """More than half the column's non-zero amounts are negative (costs printed as "(3,000)" or "-3,000")."""
    nums = [v for v in values if isinstance(v, int | float) and not isinstance(v, bool) and v != 0]
    return bool(nums) and sum(1 for v in nums if v < 0) > len(nums) / 2


def build_model(
    datasets: list[DatasetInput],
    currency: str,
    target_granularity: str | None = None,
    fx: Rates | None = None,
) -> CanonicalModel:
    series_ds = [d for d in datasets if d.table_kind == "series"]
    grans = {d.granularity for d in series_ds if d.granularity in ("month", "quarter", "year")}
    if target_granularity not in grans:
        target_granularity = (
            "month"
            if "month" in grans
            else "quarter"
            if "quarter" in grans
            else (next(iter(grans)) if grans else "month")
        )
    model = CanonicalModel(currency=currency.lower(), granularity=target_granularity, fx=fx)
    convert = model.convert

    def skipped(key: str, src: str, period: str) -> None:
        model.fx_gaps.setdefault(key, []).append((src, period))

    table_currencies: dict[str, set[str]] = defaultdict(set)
    for d in datasets:
        model.datasets[d.id] = d
        m_by_col = {m["source_column"]: m.get("canonical_field") for m in d.mapping}
        cur_by_col = {m["source_column"]: column_currency(m, model.currency) for m in d.mapping}
        foreign = {
            c for c, u in cur_by_col.items() if u != model.currency
        }  # raw columns in a currency convert too
        if d.table_kind == "series":
            if d.rows and all(
                _to_target(row["period"], d.granularity, target_granularity) is None for row in d.rows
            ):
                model.notes.append(
                    f"{d.name} is {d.granularity}ly and the model is {target_granularity}ly: "
                    f"its {d.granularity}s can't be split into {target_granularity}s, so it is left out"
                )
                continue
            # Months rolled into quarters: a quarter with fewer than 3 months would understate every flow in it.
            partial: dict[str, int] = {}
            if d.granularity == "month" and target_granularity == "quarter":
                months_in: dict[str, set[str]] = defaultdict(set)
                for row in d.rows:
                    months_in[quarter_of(row["period"])].add(row["period"])
                partial = {q: len(ms) for q, ms in months_in.items() if len(ms) < 3}
                for q in sorted(partial, key=period_sort_key):
                    model.notes.append(
                        f"{_quarter_label(q)} has {partial[q]} of 3 months in {d.name}: its amounts are "
                        f"left out rather than summed short (balances still count)"
                    )
            flip = {
                col
                for col, t in m_by_col.items()
                if t in COST_FIELDS and _mostly_negative([r.get(col) for r in d.rows])
            }
            if flip:
                model.notes.append(
                    f"Costs shown as negatives were read as positive ({d.name}: {', '.join(sorted(flip))})"
                )
            accum: dict[str, dict[str, Cell]] = defaultdict(dict)
            for i, row in enumerate(d.rows):
                p = _to_target(row["period"], d.granularity, target_granularity)
                if p is None:
                    continue
                src_rows = row.get(SRC_ROWS) or [i + 2]
                for col, val in row.items():
                    if col == "period" or not isinstance(val, int | float) or isinstance(val, bool):
                        continue
                    target = m_by_col.get(col)
                    if p in partial and not (target in FIELDS and FIELDS[target].agg == "last"):
                        continue
                    if col in flip:
                        val = -val
                    rate = None
                    if (target in FIELDS and FIELDS[target].kind == "money") or col in foreign:
                        agg_ = FIELDS[target].agg if target in FIELDS else "sum"
                        src = cur_by_col.get(col, model.currency)
                        conv = convert(float(val), src, row["period"], agg_)
                        if conv is None:
                            # No published rate for this period: left out rather than shown in the wrong currency.
                            model.fx_skipped.append(f"{d.name}:{col} {row['period']}")
                            skipped(target if target in FIELDS else f"{d.name}:{col}", src, row["period"])
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
                        accum[target][p] = Cell(
                            float(val), d.id, [col], list(src_rows), d.upload_kind, fx=[rate] if rate else []
                        )
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
                        cell.rows.extend(src_rows)
            for fid, by_p in accum.items():
                model.cells.setdefault(fid, {}).update(by_p)
        elif d.table_kind in ("customer_mrr", "cohort_mrr"):
            dim_col = next((c for c, t in m_by_col.items() if t in ("dim.customer", "dim.cohort")), None)
            val_col = next((c for c, t in m_by_col.items() if t == "value.mrr"), None)
            customers = d.table_kind == "customer_mrr"
            target_table = model.customer_mrr if customers else model.cohort_mrr
            native = model.customer_mrr_src if customers else model.cohort_mrr_src
            model.table_sources[d.table_kind] = d.id
            src_cur = cur_by_col.get(val_col, model.currency) if val_col else model.currency
            table_currencies[d.table_kind].add(src_cur)
            for row in d.rows:
                v = row.get(val_col) if val_col else None
                if v is None:
                    v = next(
                        (
                            x
                            for k, x in row.items()
                            if k not in ("period", "dim") and isinstance(x, int | float)
                        ),
                        None,
                    )
                if v is None:
                    continue
                dim = str(row.get("dim") if dim_col else row.get("dim"))
                # Several rows for one customer (or cohort) in a period (one per product or invoice) add up.
                key, sub = (row["period"], dim) if customers else (dim, row["period"])
                by = native.setdefault(key, {})
                by[sub] = by.get(sub, 0.0) + float(v)
                conv = convert(float(v), src_cur, row["period"], "sum")
                if conv is None:
                    model.fx_skipped.append(f"{d.name}:{val_col} {row['period']}")
                    skipped(d.table_kind, src_cur, row["period"])
                    continue
                if conv[1]:
                    model.table_fx[d.table_kind] = fx_note([conv[1], conv[1]], model.currency)
                by = target_table.setdefault(key, {})
                by[sub] = by.get(sub, 0.0) + float(conv[0])
    for kind, curs in table_currencies.items():
        if len(curs) > 1:  # tables in several currencies only compare once converted
            (model.customer_mrr_src if kind == "customer_mrr" else model.cohort_mrr_src).clear()

    periods = set()
    for by_p in model.cells.values():
        periods.update(by_p)
    for by_p in model.raw.values():
        periods.update(by_p)
    model.periods = sorted(periods, key=period_sort_key)
    _derive(model)
    return model


def _derive(model: CanonicalModel) -> None:
    def put(fid: str, p: str, value: float, formula: str, inputs: list[str]) -> None:
        # The derived cell keeps where its inputs came from (dataset, columns, rows, rates), so its
        # figure still cites the file rather than "derived" alone.
        cells = [c for f in inputs if (c := model.cell(f, p)) is not None]
        ds = next((c.dataset_id for c in cells if c.dataset_id), None)
        cols = list(dict.fromkeys(col for c in cells for col in c.columns))
        rows = sorted({r for c in cells for r in c.rows})
        rates = [r for c in cells for r in c.fx]
        model.cells.setdefault(fid, {})[p] = Cell(value, ds, cols, rows, "derived", formula, rates)

    for p in model.periods:
        rec, one = model.value("revenue.recurring", p), model.value("revenue.one_time", p)
        if model.value("revenue.total", p) is None and (rec is not None or one is not None):
            put(
                "revenue.total",
                p,
                (rec or 0) + (one or 0),
                "recurring + one-time revenue",
                ["revenue.recurring", "revenue.one_time"],
            )
        rev, cogs = model.value("revenue.total", p), model.value("cogs", p)
        if model.value("gross_profit", p) is None and rev is not None and cogs is not None:
            put("gross_profit", p, rev - cogs, "revenue − cost of revenue", ["revenue.total", "cogs"])
        cats = [model.value(c, p) for c in OPEX_CATEGORIES]
        if model.value("opex.total", p) is None and any(v is not None for v in cats):
            dep = model.value("depreciation", p) or 0
            put(
                "opex.total",
                p,
                sum(v or 0 for v in cats) + dep,
                "sum of opex categories",
                [*OPEX_CATEGORIES, "depreciation"],
            )
        gp, opex = model.value("gross_profit", p), model.value("opex.total", p)
        if model.value("operating_income", p) is None and gp is not None and opex is not None:
            put("operating_income", p, gp - opex, "gross profit − opex", ["gross_profit", "opex.total"])
        oi = model.value("operating_income", p)
        if model.value("net_income", p) is None and oi is not None:
            nd = model.value("non_dilutive_income", p) or 0
            put(
                "net_income",
                p,
                oi + nd,
                "operating income + non-dilutive income",
                ["operating_income", "non_dilutive_income"],
            )


FX_PERIODS_SHOWN = 4


def model_notes(model: CanonicalModel) -> list[str]:
    """What the build left out or reinterpreted, in plain words for the founder: the build's own notes, then
    one line per currency that had no published rate for some periods."""
    out = list(dict.fromkeys(model.notes))
    gaps: dict[str, set[str]] = defaultdict(set)
    for pairs in model.fx_gaps.values():
        for src, period in pairs:
            gaps[src].add(period)
    for src in sorted(gaps):
        periods = sorted(gaps[src], key=period_sort_key)
        shown = ", ".join(periods[:FX_PERIODS_SHOWN])
        more = len(periods) - FX_PERIODS_SHOWN
        when = f"{shown} and {more} more" if more > 0 else shown
        out.append(
            f"No {src.upper()}→{model.currency.upper()} rate for {when} ({SOURCE_NAME}): amounts in "
            f"{src.upper()} for {'that period' if len(periods) == 1 else 'those periods'} are left out rather "
            f"than shown in the wrong currency"
        )
    return out


def model_summary(model: CanonicalModel) -> dict[str, Any]:
    return {
        "granularity": model.granularity,
        "periods": model.periods,
        "fields": {fid: len(by_p) for fid, by_p in model.cells.items()},
        "raw_columns": sorted(model.raw),
        "has_customer_mrr": bool(model.customer_mrr),
        "has_cohort_mrr": bool(model.cohort_mrr),
        "notes": list(model.notes),
        "fx_skipped": list(model.fx_skipped),
        "messages": model_notes(model),
    }
