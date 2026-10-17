"use client";

import type { Widget } from "@/lib/types";
import { ChartWidget } from "./ChartWidget";
import { GaugeRingWidget } from "./GaugeRingWidget";
import { KpiWidget } from "./KpiWidget";
import { MissingTile } from "./MissingTile";

/** Renders one dashboard widget by status and template. */
export function WidgetView({ widget, engagementId, currency }: { widget: Widget; engagementId?: string; currency?: string }) {
  if (widget.status !== "ok") return <MissingTile widget={widget} engagementId={engagementId} />;
  switch (widget.spec.template) {
    case "gauge_ring":
      return <GaugeRingWidget widget={widget} currency={currency} />;
    case "kpi":
      return <KpiWidget widget={widget} currency={currency} />;
    default:
      return <ChartWidget widget={widget} />;
  }
}
