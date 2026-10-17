"""WidgetSpec: the declarative description of one dashboard widget.

A spec says *what* to show (metric ids or DSL expressions, window, grouping, presentation).
It never carries a number: values come from `evaluate.evaluate_widget` on the TruthContext.
"""

import hashlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Template = Literal["line", "area", "bar", "stacked_bar", "combo_bar_line", "waterfall", "kpi", "gauge_ring",
                   "heatmap", "scatter", "table"]
GroupBy = Literal["month", "quarter", "year"]
Compare = Literal["previous_period", "yoy"]

TEMPLATES: tuple[str, ...] = Template.__args__  # type: ignore[attr-defined]
SCALAR_TEMPLATES = {"kpi", "gauge_ring"}

_PERIOD_RE = re.compile(r"^\d{4}(-(0[1-9]|1[0-2]|Q[1-4]))?$")
MAX_SERIES = 8


class SeriesSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref: str = Field(min_length=1, max_length=500, description="Metric id or DSL expression")
    label: str | None = Field(default=None, max_length=80)
    axis: Literal["left", "right"] = "left"
    style: Literal["solid", "dashed"] = "solid"


class Window(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    from_: str | None = Field(default=None, alias="from")
    to: str | None = None
    last_n: int | None = Field(default=None, ge=1, le=240)

    @field_validator("from_", "to")
    @classmethod
    def _period(cls, v: str | None) -> str | None:
        if v is not None and not _PERIOD_RE.match(v):
            raise ValueError("period must look like 2026-09, 2026-Q3 or 2026")
        return v


class MarkLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(max_length=80)
    value_ref: str = Field(min_length=1, max_length=500, description="Metric id or DSL expression giving one number")


class Presentation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stack: bool = False
    smooth: bool = False
    dual_axis: bool = False
    labels: bool = False
    mark_lines: list[MarkLine] = Field(default_factory=list, max_length=4)
    sort: Literal["asc", "desc"] | None = None
    unit: str | None = Field(default=None, max_length=12)


class WidgetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", serialize_by_alias=True)

    template: Template
    title: str = Field(min_length=1, max_length=120)
    series: list[SeriesSpec] = Field(min_length=1, max_length=MAX_SERIES)
    window: Window | None = None
    group_by: GroupBy | None = None
    compare: Compare | None = None
    presentation: Presentation = Field(default_factory=Presentation)


def spec_json(spec: WidgetSpec | dict[str, Any]) -> dict[str, Any]:
    """The canonical JSON form (validated, defaults filled, aliases used)."""
    s = spec if isinstance(spec, WidgetSpec) else WidgetSpec.model_validate(spec)
    return s.model_dump(mode="json", by_alias=True)


def spec_hash(spec: WidgetSpec | dict[str, Any]) -> str:
    """Stable sha256 of the canonical JSON: insensitive to key order and to omitted defaults."""
    body = json.dumps(spec_json(spec), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
