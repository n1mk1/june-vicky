"""Build the full ECharts option for an evaluated widget.

`dataset.source` is filled only from `EvaluatedWidget` values: never from the spec or any LLM
text. The spec contributes structure (template, axes, styles) and display strings (title,
series names); the evaluator contributes every number. No colours here: the frontend
registers the `vik-dark` / `vik-light` themes and reads `theme` to pick one.

Underscore keys are Vik metadata the frontend strips before `setOption`:
`_provenance` (option series index → period → point provenance, for click-to-explain),
`_meta` (periods, units, status) and `_kpi` / `_table` for the non-chart templates.
"""

from typing import Any

from vik.viz.evaluate import EvaluatedSeries, EvaluatedWidget, KpiItem, Point
from vik.viz.spec import WidgetSpec

THEMES = ("vik-dark", "vik-light")
_LINEAR = {"line", "area", "bar", "stacked_bar", "combo_bar_line", "waterfall"}


def _unit_name(unit: str | None) -> str:
    if unit is None:
        return ""
    return {"pct": "%", "count": "count", "months": "months", "x": "×", "ratio": "ratio"}.get(
        unit, unit.upper()
    )


def _prov(p: Point) -> dict[str, Any]:
    return {
        "label": p.label,
        "value": p.value,
        "formula": p.formula,
        "inputs": [i.model_dump(mode="json", exclude_none=True) for i in p.inputs],
        "source": p.source.model_dump(mode="json") if p.source else None,
    }


def _kprov(k: KpiItem) -> dict[str, Any]:
    return {
        "label": k.label,
        "value": k.value,
        "formula": k.formula,
        "period": k.period,
        "kind": k.kind,
        "inputs": [i.model_dump(mode="json", exclude_none=True) for i in k.inputs],
        "source": k.source.model_dump(mode="json") if k.source else None,
    }


def _base(spec: WidgetSpec, ev: EvaluatedWidget, theme: str) -> dict[str, Any]:
    return {
        "theme": theme,
        "title": {"text": spec.title, "show": False},
        "aria": {"enabled": True},
        "animationDuration": 400,
        "_meta": {
            "status": ev.status,
            "template": spec.template,
            "spec_hash": ev.spec_hash,
            "currency": ev.currency,
            "granularity": ev.granularity,
            "notes": list(ev.notes),
        },
    }


def _interaction(opt: dict[str, Any], brush_type: str = "lineX") -> None:
    opt["dataZoom"] = [
        {"type": "inside", "xAxisIndex": 0, "filterMode": "none"},
        {"type": "slider", "xAxisIndex": 0, "filterMode": "none", "height": 18, "bottom": 4},
    ]
    opt["axisPointer"] = {"link": [{"xAxisIndex": "all"}]}
    opt["brush"] = {
        "toolbox": [brush_type, "clear"],
        "xAxisIndex": 0,
        "brushLink": "all",
        "throttleType": "debounce",
    }
    opt["toolbox"] = {"show": True, "right": 0, "feature": {"brush": {"type": [brush_type, "clear"]}}}
    opt["grid"] = {"containLabel": True, "left": 8, "right": 8, "top": 36, "bottom": 32}


def build_option(
    spec: WidgetSpec, evaluated: EvaluatedWidget, theme_name: str = "vik-dark"
) -> dict[str, Any]:
    """The full ECharts option (plus `_provenance` / `_meta`) for one evaluated widget."""
    theme = theme_name if theme_name in THEMES else THEMES[0]
    opt = _base(spec, evaluated, theme)
    if evaluated.status != "ok":
        opt["_meta"]["missing"] = evaluated.missing.model_dump(mode="json") if evaluated.missing else None
        opt["_meta"]["error"] = evaluated.error
        return opt
    if spec.template in ("kpi", "gauge_ring"):
        return _scalar(spec, evaluated, opt)
    if spec.template == "heatmap":
        return _heatmap(evaluated, opt)
    if spec.template == "scatter":
        return _scatter(spec, evaluated, opt)
    return _linear(spec, evaluated, opt)


# ---------------------------------------------------------------- category-axis charts


def _rows(ev: EvaluatedWidget, series: list[EvaluatedSeries], sort: str | None) -> list[int]:
    order = list(range(len(ev.periods)))
    if sort and series:
        key = series[0].points
        present = [i for i in order if key[i].value is not None]
        absent = [i for i in order if key[i].value is None]
        present.sort(key=lambda i: key[i].value, reverse=sort == "desc")
        order = present + absent
    return order


def _linear(spec: WidgetSpec, ev: EvaluatedWidget, opt: dict[str, Any]) -> dict[str, Any]:
    pres = spec.presentation
    t = spec.template
    sortable = t in ("bar", "stacked_bar", "table")
    order = _rows(ev, ev.series, pres.sort if sortable else None)
    dims = ["period"] + [f"s{i}" for i in range(len(ev.series))]
    source: list[list[Any]] = [dims]
    for i in order:
        source.append([ev.period_labels[i]] + [s.points[i].value for s in ev.series])
    opt["dataset"] = {"source": source}
    opt["_meta"]["periods"] = [ev.periods[i] for i in order]
    opt["_meta"]["period_labels"] = [ev.period_labels[i] for i in order]
    opt["_meta"]["units"] = {str(i): s.unit for i, s in enumerate(ev.series)}

    if t == "table":
        opt["_table"] = {
            "columns": [{"key": "period", "label": "Period", "unit": None}]
            + [{"key": f"s{i}", "label": s.label, "unit": s.unit} for i, s in enumerate(ev.series)]
        }
        opt["series"] = []
        opt["_provenance"] = {
            str(i): {ev.periods[j]: _prov(s.points[j]) for j in order} for i, s in enumerate(ev.series)
        }
        return opt

    # axis assignment
    values = [s for s in ev.series if s.role in ("value", "compare")]
    explicit_right = any(s.axis == "right" for s in values)
    first_unit = values[0].unit if values else None

    # combo_bar_line without explicit axes: the first series (and its comparison) are bars on the left,
    # everything after is a line on the right
    lead = {0} | ({1} if len(ev.series) > 1 and ev.series[1].role == "compare" else set())

    def on_right(i: int, s: EvaluatedSeries) -> bool:
        if t == "waterfall":
            return False
        if explicit_right:
            return s.axis == "right"
        if t == "combo_bar_line":
            return i not in lead
        if pres.dual_axis:
            return s.unit != first_unit
        return False

    right_flags = [on_right(i, s) for i, s in enumerate(ev.series)]
    left_units = [s.unit for s, r in zip(ev.series, right_flags, strict=True) if not r]
    right_units = [s.unit for s, r in zip(ev.series, right_flags, strict=True) if r]
    y_axes = [
        {
            "type": "value",
            "position": "left",
            "name": _unit_name(left_units[0] if left_units else None),
            "scale": t in ("line", "area") and not pres.stack,
        }
    ]
    if any(right_flags):
        y_axes.append(
            {
                "type": "value",
                "position": "right",
                "name": _unit_name(right_units[0]),
                "splitLine": {"show": False},
                "scale": True,
            }
        )
    opt["yAxis"] = y_axes
    opt["xAxis"] = {"type": "category", "boundaryGap": t not in ("line", "area")}
    opt["_meta"]["y_units"] = [left_units[0] if left_units else None] + (
        [right_units[0]] if right_units else []
    )

    out_series = []
    for i, s in enumerate(ev.series):
        right = right_flags[i]
        if t == "waterfall":
            kind = "bar"
        elif t == "combo_bar_line":
            kind = "line" if right or s.role == "compare" else "bar"
        elif t in ("bar", "stacked_bar"):
            kind = "line" if s.role == "compare" else "bar"
        else:
            kind = "line"
        item: dict[str, Any] = {
            "type": kind,
            "name": s.label,
            "datasetIndex": 0,
            "encode": {"x": "period", "y": f"s{i}"},
            "yAxisIndex": 1 if right else 0,
        }
        if kind == "line":
            item["smooth"] = pres.smooth
            item["showSymbol"] = len(ev.periods) <= 12
            item["connectNulls"] = False
            if s.style == "dashed":
                item["lineStyle"] = {"type": "dashed"}
            if t == "area" and s.role == "value":
                item["areaStyle"] = {}
        stacked = t == "stacked_bar" or (pres.stack and t in ("bar", "area", "line"))
        if stacked and s.role == "value":
            item["stack"] = "total"
        if t == "waterfall":
            # base (running total before) + signed change = running total after, on either side of zero;
            # ECharts' default "samesign" would stack a change on the wrong bar once the total crosses zero
            item["stack"] = "waterfall"
            item["stackStrategy"] = "all"
            if s.role == "waterfall_base":
                item["itemStyle"] = {"color": "transparent", "borderColor": "transparent"}
                item["emphasis"] = {"disabled": True}
                item["silent"] = True
                item["tooltip"] = {"show": False}
        if pres.labels and s.role != "waterfall_base":
            item["label"] = {"show": True, "position": "top" if kind == "bar" and not stacked else "inside"}
        out_series.append(item)

    first_value = next((i for i, s in enumerate(ev.series) if s.role in ("value", "waterfall_up")), 0)
    if ev.mark_lines and out_series:
        out_series[first_value]["markLine"] = {
            "symbol": "none",
            "label": {"formatter": "{b}"},
            "data": [{"name": m.label, "yAxis": m.value} for m in ev.mark_lines],
        }
    opt["series"] = out_series
    opt["legend"] = {
        "show": True,
        "type": "scroll",
        "top": 0,
        "data": [s.label for s in ev.series if s.role != "waterfall_base"],
    }
    opt["tooltip"] = {
        "trigger": "axis",
        "axisPointer": {"type": "shadow" if t in ("bar", "stacked_bar", "waterfall") else "line"},
    }
    _interaction(opt)
    opt["_provenance"] = {
        str(i): {ev.periods[j]: _prov(s.points[j]) for j in order}
        for i, s in enumerate(ev.series)
        if s.role != "waterfall_base"
    }
    opt["_meta"]["mark_lines"] = [m.model_dump(mode="json") for m in ev.mark_lines]
    return opt


# ---------------------------------------------------------------- other templates


def _scatter(spec: WidgetSpec, ev: EvaluatedWidget, opt: dict[str, Any]) -> dict[str, Any]:
    values = [s for s in ev.series if s.role == "value"]  # a comparison series is never an axis
    if len(values) < 2:
        opt["_meta"]["status"] = "error"
        opt["_meta"]["error"] = "A scatter needs two series: x then y"
        return opt
    x, y = values[0], values[1]
    source: list[list[Any]] = [["period", "x", "y"]]
    keep = [
        i for i in range(len(ev.periods)) if x.points[i].value is not None and y.points[i].value is not None
    ]
    for i in keep:
        source.append([ev.period_labels[i], x.points[i].value, y.points[i].value])
    opt["dataset"] = {"source": source}
    opt["xAxis"] = {
        "type": "value",
        "name": f"{x.label} ({_unit_name(x.unit)})" if x.unit else x.label,
        "scale": True,
    }
    opt["yAxis"] = {
        "type": "value",
        "name": f"{y.label} ({_unit_name(y.unit)})" if y.unit else y.label,
        "scale": True,
    }
    opt["series"] = [
        {
            "type": "scatter",
            "name": spec.title,
            "datasetIndex": 0,
            "encode": {"x": "x", "y": "y", "tooltip": ["period", "x", "y"], "itemName": "period"},
        }
    ]
    opt["tooltip"] = {"trigger": "item"}
    opt["legend"] = {"show": False}
    _interaction(opt, "rect")
    opt["_meta"]["periods"] = [ev.periods[i] for i in keep]
    opt["_meta"]["units"] = {"x": x.unit, "y": y.unit}
    opt["_meta"]["labels"] = {"x": x.label, "y": y.label}
    opt["_provenance"] = {
        "0": {ev.periods[i]: {"x": _prov(x.points[i]), "y": _prov(y.points[i])} for i in keep}
    }
    return opt


def _heatmap(ev: EvaluatedWidget, opt: dict[str, Any]) -> dict[str, Any]:
    source: list[list[Any]] = [["period", "row", "value"]]
    values = []
    for s in ev.series:
        for p in s.points:
            if p.value is not None:
                source.append([p.label, s.label, p.value])
                values.append(p.value)
    opt["dataset"] = {"source": source}
    opt["xAxis"] = {"type": "category", "data": list(ev.period_labels), "splitArea": {"show": True}}
    opt["yAxis"] = {"type": "category", "data": [s.label for s in ev.series], "splitArea": {"show": True}}
    opt["visualMap"] = {
        "min": min(values) if values else 0,
        "max": max(values) if values else 1,
        "calculable": True,
        "orient": "horizontal",
        "left": "center",
        "bottom": 0,
        "dimension": 2,
    }
    opt["series"] = [
        {
            "type": "heatmap",
            "datasetIndex": 0,
            "encode": {"x": "period", "y": "row", "value": "value"},
            "label": {"show": False},
            "emphasis": {"itemStyle": {"borderWidth": 1}},
        }
    ]
    opt["tooltip"] = {"trigger": "item"}
    opt["dataZoom"] = [
        {"type": "inside", "xAxisIndex": 0},
        {"type": "slider", "xAxisIndex": 0, "height": 18, "bottom": 36},
    ]
    opt["grid"] = {"containLabel": True, "left": 8, "right": 8, "top": 8, "bottom": 72}
    opt["_meta"]["periods"] = list(ev.periods)
    opt["_meta"]["rows"] = [s.label for s in ev.series]
    opt["_meta"]["units"] = {"value": ev.series[0].unit if ev.series else None}
    # heatmap cells are addressed by row (series) then period
    opt["_provenance"] = {
        str(r): {p.period: _prov(p) for p in s.points if p.value is not None} for r, s in enumerate(ev.series)
    }
    return opt


def _scalar(spec: WidgetSpec, ev: EvaluatedWidget, opt: dict[str, Any]) -> dict[str, Any]:
    assert ev.kpi is not None
    items = [ev.kpi.primary, *ev.kpi.secondary]
    source: list[list[Any]] = [["key", "value"]]
    for i, k in enumerate(items):
        source.append([f"k{i}", k.value])
    opt["dataset"] = {"source": source}
    opt["_kpi"] = [
        {
            "key": f"k{i}",
            "id": k.id,
            "label": k.label,
            "unit": k.unit,
            "display": k.display,
            "kind": k.kind,
            "period": k.period,
            "missing": k.missing.model_dump(mode="json") if k.missing else None,
        }
        for i, k in enumerate(items)
    ]
    opt["_provenance"] = {str(i): {"value": _kprov(k)} for i, k in enumerate(items) if k.value is not None}
    if spec.template == "kpi":
        opt["series"] = []
        return opt
    rings = [(i, k) for i, k in enumerate(items) if k.value is not None]
    series = []
    for n, (_, k) in enumerate(rings):
        outer = 92 - n * 16
        ring: dict[str, Any] = {
            "type": "gauge",
            "name": k.label,
            "startAngle": 90,
            "endAngle": -270,
            "radius": f"{outer}%",
            "pointer": {"show": False},
            "progress": {"show": True, "overlap": False, "roundCap": True, "width": 10, "clip": False},
            "axisLine": {"lineStyle": {"width": 10}},
            "splitLine": {"show": False},
            "axisTick": {"show": False},
            "axisLabel": {"show": False},
            "title": {"show": False},
            "detail": {"show": n == 0, "valueAnimation": True, "offsetCenter": [0, 0]},
            "data": [{"value": k.value, "name": k.label}],
        }
        if k.unit == "pct":
            ring["min"], ring["max"] = 0, 1
        series.append(ring)
    opt["series"] = series
    opt["tooltip"] = {"trigger": "item"}
    opt["legend"] = {"show": True, "bottom": 0, "data": [k.label for _, k in rings]}
    opt["_meta"]["rings"] = [f"k{i}" for i, _ in rings]
    return opt
