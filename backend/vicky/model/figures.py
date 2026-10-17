"""Figures: the atomic, sourced numbers every agent and chart draws on."""

from typing import Any, Literal

from pydantic import BaseModel, Field

Unit = Literal["cad", "usd", "gbp", "eur", "aud", "pct", "months", "count", "ratio", "x"]
FigureKind = Literal["historical", "forecast", "founder_claim", "benchmark"]
SourceKind = Literal["csv", "xlsx", "pdf", "docx", "md", "pack_summary", "founder_stated", "benchmark", "derived"]

CURRENCY_UNITS = {"cad", "usd", "gbp", "eur", "aud"}


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
    return {"gbp": "£", "eur": "€"}.get(unit, "$")


def fmt_money(value: float, unit: str = "usd") -> str:
    sym = currency_symbol(unit)
    sign = "-" if value < 0 else ""
    v = abs(value)
    if v >= 1_000_000:
        return f"{sign}{sym}{v / 1_000_000:.2f}M"
    if v >= 10_000:
        return f"{sign}{sym}{v / 1_000:.1f}K"
    if v >= 1_000:
        return f"{sign}{sym}{v:,.0f}"
    return f"{sign}{sym}{v:.0f}"


def fmt_value(value: float, unit: str) -> str:
    if unit in CURRENCY_UNITS:
        return fmt_money(value, unit)
    if unit == "pct":
        digits = 1 if abs(value) < 0.1 else 0
        return f"{value * 100:.{digits}f}%"
    if unit == "months":
        return f"{value:.1f} mo"
    if unit == "x":
        return f"{value:.2f}x"
    if unit == "ratio":
        return f"{value:.2f}"
    if unit == "count":
        return f"{value:,.0f}"
    return f"{value:g}"


def figure_dict(f: Figure | MissingFigure) -> dict:
    return f.model_dump(mode="json")


def parse_figure(d: dict) -> Figure | MissingFigure:
    if d.get("missing"):
        return MissingFigure.model_validate(d)
    return Figure.model_validate(d)
