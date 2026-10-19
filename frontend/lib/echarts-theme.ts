/**
 * Registers the `vik-dark` and `vik-light` ECharts themes from the CSS tokens in
 * app/globals.css. The backend's options carry no colours (viz/echarts.py); the theme does.
 *
 * Tokens are read by mounting a hidden probe with `data-theme="dark|light"` (the selectors in
 * globals.css apply to any element), so the charts always match the stylesheet.
 */

import type { Theme } from "./use-theme";
import { palette } from "./use-theme";

export const themeName = (t: Theme) => (t === "light" ? "vik-light" : "vik-dark");

interface Tokens {
  ink: string;
  ink2: string;
  dim: string;
  line: string;
  lineStrong: string;
  ember: string;
  surfaceSolid: string;
  font: string;
  mono: string;
}

function readTokens(theme: Theme): Tokens {
  const fallback = palette[theme];
  const base: Tokens = {
    ink: fallback.ink,
    ink2: theme === "dark" ? "#a8a8aa" : "#434343",
    dim: fallback.dim,
    line: fallback.line,
    lineStrong: theme === "dark" ? "rgba(255,255,255,0.3)" : "rgba(17,18,20,0.34)",
    ember: fallback.ember,
    surfaceSolid: theme === "dark" ? "#0c0d10" : "#f2f2f2",
    font: "Inter Tight, system-ui, sans-serif",
    mono: "monospace",
  };
  if (typeof document === "undefined") return base;
  const probe = document.createElement("div");
  probe.dataset.theme = theme;
  probe.style.display = "none";
  document.body.appendChild(probe);
  const cs = getComputedStyle(probe);
  const v = (name: string, d: string) => cs.getPropertyValue(name).trim() || d;
  const out: Tokens = {
    ink: v("--ink", base.ink),
    ink2: v("--ink-2", base.ink2),
    dim: v("--dim", base.dim),
    line: v("--line", base.line),
    lineStrong: v("--line-strong", base.lineStrong),
    ember: v("--ember", base.ember),
    surfaceSolid: v("--surface-solid", base.surfaceSolid),
    font: `${v("--font-inter-tight", "Inter Tight")}, system-ui, sans-serif`,
    mono: `${v("--font-martian", "monospace")}, monospace`,
  };
  probe.remove();
  return out;
}

/**
 * Black and white: series are told apart by lightness alone. The first is full ink, the second a
 * clearly lighter grey (carry-forwards, risk, the second ring), then alternating mid and far greys.
 */
function seriesColors(t: Tokens, theme: Theme): string[] {
  return theme === "dark"
    ? [t.ink, "#8c8c8c", "#cfcfcf", "#5a5a5a", "#ababab", "#3c3c3c", "#e6e6e6", "#717171"]
    : [t.ink, "#7a7a7a", "#3a3a3a", "#b0b0b0", "#5c5c5c", "#cfcfcf", "#1f1f1f", "#939393"];
}

function build(theme: Theme): Record<string, unknown> {
  const t = readTokens(theme);
  const axis = {
    axisLine: { show: true, lineStyle: { color: t.line } },
    axisTick: { show: false },
    axisLabel: { color: t.dim, fontSize: 10, fontFamily: t.font },
    splitLine: { show: true, lineStyle: { color: t.line, type: [2, 4] } },
    splitArea: { show: false },
    nameTextStyle: { color: t.dim, fontSize: 10, fontFamily: t.mono },
  };
  return {
    color: seriesColors(t, theme),
    backgroundColor: "transparent",
    textStyle: { fontFamily: t.font, color: t.ink2 },
    title: { textStyle: { color: t.ink }, subtextStyle: { color: t.dim } },
    line: { symbol: "circle", symbolSize: 4, lineStyle: { width: 1.5 }, emphasis: { lineStyle: { width: 1.5 } } },
    bar: { itemStyle: { borderRadius: [3, 3, 0, 0] }, barMaxWidth: 28 },
    categoryAxis: { ...axis, splitLine: { show: false } },
    valueAxis: { ...axis, axisLine: { show: false } },
    logAxis: axis,
    timeAxis: axis,
    legend: {
      textStyle: { color: t.ink2, fontSize: 11 },
      icon: "roundRect",
      itemWidth: 10,
      itemHeight: 3,
      pageIconColor: t.ink2,
      pageIconInactiveColor: t.line,
      pageTextStyle: { color: t.dim },
    },
    tooltip: {
      backgroundColor: theme === "dark" ? "rgba(12,13,16,0.94)" : "rgba(242,242,242,0.96)",
      borderColor: t.line,
      borderWidth: 1,
      padding: [8, 10],
      textStyle: { color: t.ink, fontSize: 12, fontFamily: t.font },
      extraCssText: "border-radius:10px;box-shadow:none;backdrop-filter:blur(12px);",
      axisPointer: {
        lineStyle: { color: t.dim, width: 1 },
        crossStyle: { color: t.dim },
        shadowStyle: { color: theme === "dark" ? "rgba(255,255,255,0.04)" : "rgba(17,18,20,0.05)" },
      },
    },
    axisPointer: { lineStyle: { color: t.dim }, label: { backgroundColor: t.ink, color: t.surfaceSolid } },
    dataZoom: {
      backgroundColor: "transparent",
      borderColor: t.line,
      fillerColor: theme === "dark" ? "rgba(255,255,255,0.06)" : "rgba(17,18,20,0.06)",
      handleStyle: { color: t.surfaceSolid, borderColor: t.lineStrong },
      moveHandleStyle: { color: t.lineStrong },
      dataBackground: { lineStyle: { color: t.lineStrong }, areaStyle: { color: t.line } },
      selectedDataBackground: { lineStyle: { color: t.ink2 }, areaStyle: { color: t.line } },
      textStyle: { color: t.dim, fontSize: 9 },
      brushStyle: { color: t.line },
      emphasis: { handleStyle: { borderColor: t.ink } },
    },
    toolbox: { iconStyle: { borderColor: t.dim }, emphasis: { iconStyle: { borderColor: t.ink } } },
    brush: { brushStyle: { color: t.line, borderColor: t.lineStrong } },
    markLine: { lineStyle: { color: t.ember, type: "dashed" }, label: { color: t.ember } },
    visualMap: {
      inRange: { color: theme === "dark" ? ["#16171c", "#5b5c62", t.ink] : ["#e4e4e4", "#8d8e93", t.ink] },
      textStyle: { color: t.dim, fontSize: 10 },
      itemHeight: 120,
      itemWidth: 10,
    },
    gauge: {
      axisLine: { lineStyle: { color: [[1, t.line]] } },
      detail: { color: t.ink, fontFamily: t.font, fontWeight: 400 },
      title: { color: t.ink2 },
    },
    radar: {
      axisName: { color: t.ink2, fontSize: 11 },
      axisLine: { lineStyle: { color: t.line } },
      splitLine: { lineStyle: { color: t.line } },
      splitArea: { show: false },
    },
    heatmap: { itemStyle: { borderColor: theme === "dark" ? "#040508" : "#f2f2f2", borderWidth: 1 } },
  };
}

let registered = false;

/** Register both themes once per page (re-reading tokens is cheap but not needed per chart). */
export function registerVikThemes(echarts: { registerTheme: (name: string, theme: object) => void }) {
  if (registered || typeof document === "undefined") return;
  echarts.registerTheme("vik-dark", build("dark"));
  echarts.registerTheme("vik-light", build("light"));
  registered = true;
}
