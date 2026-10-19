"""Dashboard visualisation engine: WidgetSpec → evaluated series with provenance → ECharts option."""

from vik.viz.defaults import DefaultDashboard, default_dashboard, default_layout, default_widgets
from vik.viz.dsl import DSLError, parse
from vik.viz.echarts import build_option
from vik.viz.evaluate import EvaluatedWidget, evaluate_widget
from vik.viz.spec import WidgetSpec, spec_hash

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
