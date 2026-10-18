"""Dashboard visualisation engine: WidgetSpec → evaluated series with provenance → ECharts option."""

from vicky.viz.defaults import DefaultDashboard, default_dashboard, default_layout, default_widgets
from vicky.viz.dsl import DSLError, parse
from vicky.viz.echarts import build_option
from vicky.viz.evaluate import EvaluatedWidget, evaluate_widget
from vicky.viz.spec import WidgetSpec, spec_hash

__all__ = [
    "DSLError",
    "DefaultDashboard",
    "EvaluatedWidget",
    "WidgetSpec",
    "build_option",
    "default_dashboard",
    "default_layout",
    "default_widgets",
    "evaluate_widget",
    "parse",
    "spec_hash",
]
