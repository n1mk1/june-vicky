"use client";

import { BarChart, GaugeChart, HeatmapChart, LineChart, RadarChart, ScatterChart } from "echarts/charts";
import {
  AriaComponent,
  BrushComponent,
  DataZoomComponent,
  DatasetComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  RadarComponent,
  TitleComponent,
  ToolboxComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { LegacyGridContainLabel } from "echarts/features";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";
import { registerVikThemes, themeName } from "@/lib/echarts-theme";
import { useTheme } from "@/lib/use-theme";
import { cn } from "@/lib/utils";

echarts.use([
  LineChart,
  BarChart,
  HeatmapChart,
  GaugeChart,
  ScatterChart,
  RadarChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  DatasetComponent,
  MarkLineComponent,
  VisualMapComponent,
  BrushComponent,
  ToolboxComponent,
  AriaComponent,
  TitleComponent,
  RadarComponent,
  // The backend's options use grid.containLabel (ECharts 5 style).
  LegacyGridContainLabel,
  CanvasRenderer,
]);

export interface ChartClick {
  seriesIndex: number;
  dataIndex: number;
  value: unknown;
  name: string;
}

interface EChartProps {
  option: Record<string, unknown>;
  onPointClick?: (p: ChartClick) => void;
  /** The category index window `[start, end]` after the user zooms (slider, wheel or pinch). */
  onZoom?: (window: [number, number]) => void;
  className?: string;
  ariaLabel?: string;
}

/** Thin wrapper over echarts/core: themed from CSS tokens, resizes with its box, re-inits on theme change. */
export function EChart({ option, onPointClick, onZoom, className, ariaLabel }: EChartProps) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const click = useRef(onPointClick);
  const zoom = useRef(onZoom);
  const { theme } = useTheme();

  useEffect(() => {
    click.current = onPointClick;
    zoom.current = onZoom;
  }, [onPointClick, onZoom]);

  // (Re)create the instance when the theme changes; ECharts themes are fixed at init.
  useEffect(() => {
    const node = el.current;
    if (!node) return;
    registerVikThemes(echarts);
    const inst = echarts.init(node, themeName(theme), { renderer: "canvas" });
    chart.current = inst;
    let handled = false;
    inst.on("click", (p) => {
      handled = true;
      inst.dispatchAction({ type: "hideTip" });
      const e = p as unknown as { seriesIndex?: number; dataIndex?: number; value: unknown; name: string };
      click.current?.({ seriesIndex: e.seriesIndex ?? 0, dataIndex: e.dataIndex ?? 0, value: e.value, name: e.name });
    });
    // Lines draw no symbols on long series, so a click anywhere in the grid picks the nearest point:
    // the category under the pointer, then the series whose value sits closest vertically.
    inst.getZr().on("click", (e: { offsetX: number; offsetY: number }) => {
      window.setTimeout(() => {
        if (handled) {
          handled = false;
          return;
        }
        const px: [number, number] = [e.offsetX, e.offsetY];
        try {
          if (!inst.containPixel({ gridIndex: 0 }, px)) return;
          const xy = inst.convertFromPixel({ gridIndex: 0 }, px) as number[] | number;
          const xi = Math.round(Number(Array.isArray(xy) ? xy[0] : xy));
          if (!Number.isFinite(xi)) return;
          const opt = inst.getOption() as {
            dataset?: { source?: unknown[][] }[];
            series?: { encode?: { y?: string | string[] }; type?: string }[];
          };
          const source = opt.dataset?.[0]?.source;
          const row = source?.[xi + 1];
          if (!source || !row) return;
          let best = -1;
          let bestD = Number.POSITIVE_INFINITY;
          (opt.series ?? []).forEach((s, i) => {
            const enc = Array.isArray(s.encode?.y) ? s.encode?.y[0] : s.encode?.y;
            const col = enc ? source[0].indexOf(enc) : -1;
            const v = col >= 0 ? row[col] : null;
            if (typeof v !== "number") return;
            const at = inst.convertToPixel({ seriesIndex: i }, [xi, v]) as number[] | undefined;
            const d = at ? Math.abs(at[1] - e.offsetY) : Number.POSITIVE_INFINITY;
            if (d < bestD) {
              bestD = d;
              best = i;
            }
          });
          if (best >= 0) inst.dispatchAction({ type: "hideTip" });
          if (best >= 0) click.current?.({ seriesIndex: best, dataIndex: xi, value: row, name: String(row[0]) });
        } catch {
          // Non-cartesian charts (gauge, radar) have no grid to resolve against.
        }
      }, 0);
    });
    // Only user gestures emit `datazoom` (setOption doesn't), so applying a range never loops back.
    inst.on("datazoom", () => {
      const dz = (inst.getOption() as { dataZoom?: { startValue?: number; endValue?: number }[] }).dataZoom?.[0];
      if (typeof dz?.startValue === "number" && typeof dz.endValue === "number") zoom.current?.([dz.startValue, dz.endValue]);
    });
    const ro = new ResizeObserver(() => inst.resize());
    ro.observe(node);
    return () => {
      ro.disconnect();
      inst.dispose();
      chart.current = null;
    };
  }, [theme]);

  useEffect(() => {
    chart.current?.setOption(option, { notMerge: true });
  }, [option, theme]);

  return <div ref={el} role="img" aria-label={ariaLabel} className={cn("h-full min-h-[140px] w-full", className)} />;
}
