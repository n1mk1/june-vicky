"""Figures: the atomic, sourced numbers every agent and chart draws on."""

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

from vicky.model.currencies import CURRENCY_CODES, DEFAULT_CURRENCY, symbol

Unit = Literal["cad", "usd", "eur", "gbp", "aud", "nzd", "jpy", "cny", "hkd", "sgd", "twd", "krw", "inr", "idr", "myr",
               "thb", "chf", "nok", "sek", "pln", "try", "zar", "mxn", "brl", "pen",
               "pct", "months", "count", "ratio", "x"]
FigureKind = Literal["historical", "forecast", "founder_claim", "benchmark"]
SourceKind = Literal["csv", "xlsx", "pdf", "docx", "md", "pack_summary", "founder_stated", "benchmark", "derived"]

CURRENCY_UNITS = set(CURRENCY_CODES)
UNITS = CURRENCY_UNITS | {"pct", "months", "count", "ratio", "x"}


class Source(BaseModel):
    kind: SourceKind
    ref: str = ""
    dataset_id: str | None = None
    page: int | None = None
    cited_text: str | None = None
    verified: bool | None = None
    url: str | None = None
    source_id: str | None = None


class FigureRef(BaseModel):
    figure_id: str | None = None
    dataset_id: str | None = None
    column: str | None = None
    period: str | None = None
    value: float | None = None


class Figure(BaseModel):
    id: str
    label: str
    value: float
    unit: Unit
    formula: str
    inputs: list[FigureRef] = Field(default_factory=list)
    source: Source
    kind: FigureKind = "historical"
    period: str | None = None
    group: str = "generic"
    display: str = ""

    def model_post_init(self, __context: Any) -> None:
        if not self.display:
            self.display = fmt_value(self.value, self.unit)


class MissingFigure(BaseModel):
    id: str
    label: str = ""
    needs: list[str]
    reason: str
    group: str = "generic"
    missing: Literal[True] = True


class Fact(BaseModel):
    id: str
    name: str
    label: str = ""
    value: float
    unit: str
    period: str | None = None
    kind: FigureKind = "historical"
    source: Source
    status: Literal["pending", "confirmed", "removed"] = "pending"
    target_metric: bool = False
    note: str | None = None


def currency_symbol(unit: str) -> str:
    return symbol(unit) if unit in CURRENCY_UNITS else "$"


def _half_up(v: float, digits: int) -> Decimal:
    """`v` rounded half away from zero at `digits` decimals, on its exact binary value: the same digits the
    frontend's `toFixed` shows, so a figure reads the same in a KPI card and in a chart tooltip."""
    return Decimal(v).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)


def _signed(value: float, shown: Decimal, text: str) -> str:
    """A minus sign only when the rounded number isn't zero ("-$0" and "-0.0%" read as noise)."""
    return f"-{text}" if value < 0 and shown != 0 else text


def fmt_money(value: float, unit: str = DEFAULT_CURRENCY) -> str:
    if not math.isfinite(value):
        return "n/a"
    sym = currency_symbol(unit)
    v = abs(value)
    # Round first, then pick the tier, so 999.6 reads "$1,000" and 999,999.9 reads "$1.00M".
    whole = _half_up(v, 0)
    if whole < 1_000:
        return _signed(value, whole, f"{sym}{whole}")
    if whole < 10_000:
        return _signed(value, whole, f"{sym}{whole:,}")
    k = _half_up(v / 1_000, 1)
    if k < 1_000:
        return _signed(value, k, f"{sym}{k}K")
    m = _half_up(v / 1_000_000, 2)
    return _signed(value, m, f"{sym}{m}M")


def fmt_value(value: float, unit: str) -> str:
    if not math.isfinite(value):
        return "n/a"
    if unit in CURRENCY_UNITS:
        return fmt_money(value, unit)
    if unit == "pct":
        tenth = _half_up(abs(value) * 100, 1)
        shown = tenth if tenth < 10 else _half_up(abs(value) * 100, 0)
        return _signed(value, shown, f"{shown}%")
    if unit in ("months", "x", "ratio", "count"):
        digits = {"months": 1, "x": 2, "ratio": 2, "count": 0}[unit]
        shown = _half_up(abs(value), digits)
        text = f"{shown:,}" if unit == "count" else f"{shown}"
        return _signed(value, shown, text + {"months": " mo", "x": "x"}.get(unit, ""))
    return f"{value:g}"


def figure_dict(f: Figure | MissingFigure) -> dict:
    return f.model_dump(mode="json")


def parse_figure(d: dict) -> Figure | MissingFigure:
    if d.get("missing"):
        return MissingFigure.model_validate(d)
    return Figure.model_validate(d)
