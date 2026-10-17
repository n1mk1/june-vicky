import type { ComponentType } from "react";
import type { TimeRange, Widget } from "@/lib/types";
import { ChartWidget } from "./ChartWidget";
import { GaugeRingWidget } from "./GaugeRingWidget";
import { KpiWidget } from "./KpiWidget";
import { MissingTile } from "./MissingTile";

/** Everything a widget renderer may use. Values always come from the widget's evaluated data. */
export interface WidgetProps {
  widget: Widget;
  engagementId?: string;
  currency?: string;
  timeRange?: TimeRange | null;
  onRangeChange?: (range: { from: string; to: string } | null) => void;
}

export interface WidgetKind {
  /** Renders the widget. */
  component: ComponentType<WidgetProps>;
  /** Scalar widgets show one figure (and its secondaries); the rest plot series over periods. */
  scalar: boolean;
  /** Default size on the 12-column grid when a widget of this kind is added. */
  size: { w: number; h: number };
}

const chart: WidgetKind = {
  component: ({ widget, timeRange, onRangeChange }) => <ChartWidget widget={widget} timeRange={timeRange} onRangeChange={onRangeChange} />,
  scalar: false,
  size: { w: 6, h: 5 },
};

/**
 * The widget registry: one entry per WidgetSpec template. To add a widget type, add its renderer
 * here (and the template to the backend's WidgetSpec); the grid, the dashboard and the chat pick
 * it up without further changes.
 */
export const WIDGETS: Record<string, WidgetKind> = {
  kpi: { component: ({ widget, currency }) => <KpiWidget widget={widget} currency={currency} />, scalar: true, size: { w: 3, h: 4 } },
  gauge_ring: { component: ({ widget, currency }) => <GaugeRingWidget widget={widget} currency={currency} />, scalar: true, size: { w: 3, h: 4 } },
  line: chart,
  area: chart,
  bar: chart,
  stacked_bar: chart,
  combo_bar_line: chart,
  waterfall: chart,
  heatmap: chart,
  scatter: chart,
  table: chart,
};

/** Widgets whose data is missing or failed render as a tile that says why, whatever their template. */
export const MISSING: WidgetKind = {
  component: ({ widget, engagementId }) => <MissingTile widget={widget} engagementId={engagementId} />,
  scalar: true,
  size: { w: 3, h: 3 },
};

export function kindOf(widget: Widget): WidgetKind {
  if (widget.status !== "ok") return MISSING;
  return WIDGETS[widget.spec.template] ?? chart;
}
