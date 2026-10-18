"use client";

import { GraphChart } from "echarts/charts";
import { TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";
import type { KbGraph as Graph, KbGraphNode } from "@/lib/types";
import { useTheme } from "@/lib/use-theme";
import { cn } from "@/lib/utils";

echarts.use([GraphChart, TooltipComponent, CanvasRenderer]);

interface KbGraphProps {
  graph: Graph;
  selected: string | null;
  /** Nodes whose title or path contains this light up; the rest fade. */
  query: string;
  onOpen: (id: string) => void;
  onCreate: (title: string) => void;
  className?: string;
}

interface Tokens {
  ink: string;
  ink2: string;
  dim: string;
  line: string;
  lineStrong: string;
  ember: string;
  surface: string;
  mono: string;
}

function readTokens(): Tokens {
  const cs = getComputedStyle(document.documentElement);
  const v = (n: string, d: string) => cs.getPropertyValue(n).trim() || d;
  return {
    ink: v("--ink", "#e2e2e2"),
    ink2: v("--ink-2", "#a8a8aa"),
    dim: v("--dim", "rgba(216,216,216,0.48)"),
    line: v("--line", "rgba(255,255,255,0.11)"),
    lineStrong: v("--line-strong", "rgba(255,255,255,0.3)"),
    ember: v("--ember", "#e0502f"),
    surface: v("--surface-solid", "#0c0d10"),
    mono: `${v("--font-martian", "monospace")}, monospace`,
  };
}

const KIND_LABEL: Record<KbGraphNode["kind"], string> = {
  hub: "Hub",
  document: "Document",
  table: "Table",
  note: "Note",
  missing: "Not written yet",
};

function nodeStyle(n: KbGraphNode, t: Tokens) {
  const base = Math.min(26, 6 + Math.sqrt(n.degree) * 3.2);
  switch (n.kind) {
    case "hub":
      return { symbol: "circle", symbolSize: Math.min(30, 12 + Math.sqrt(n.degree) * 2.6), itemStyle: { color: t.ember } };
    case "table":
      return { symbol: "roundRect", symbolSize: base, itemStyle: { color: t.ink2 } };
    case "note":
      return { symbol: "diamond", symbolSize: base + 2, itemStyle: { color: t.ink } };
    case "missing":
      return {
        symbol: "circle",
        symbolSize: 7,
        itemStyle: { color: "transparent", borderColor: t.dim, borderWidth: 1, borderType: "dashed" as const },
      };
    default:
      return { symbol: "circle", symbolSize: base, itemStyle: { color: t.ink } };
  }
}

type Positions = Map<string, [number, number]>;

/** Where every node sits now, so a refresh (after an edit) continues from the current layout. */
function positions(chart: echarts.ECharts | null, ids: string[]): Positions {
  const out: Positions = new Map();
  try {
    const model = (chart as unknown as { getModel(): { getSeriesByIndex(i: number): { getData(): { getItemLayout(i: number): number[] | undefined } } | undefined } })
      ?.getModel()
      ?.getSeriesByIndex(0);
    const data = model?.getData();
    ids.forEach((id, i) => {
      const p = data?.getItemLayout(i);
      if (p && Number.isFinite(p[0]) && Number.isFinite(p[1])) out.set(id, [p[0], p[1]]);
    });
  } catch {
    // No layout yet.
  }
  return out;
}

function buildOption(graph: Graph, t: Tokens, prev: Positions, width: number) {
  const n = graph.nodes.length;
  const small = n <= 40;
  // A narrow panel (a note open beside it) zooms out so the spread-out layout still fits.
  const zoom = Math.min(1, Math.max(0.75, width / 640));
  return {
    animationDurationUpdate: 300,
    tooltip: {
      confine: true,
      backgroundColor: t.surface,
      borderColor: t.line,
      textStyle: { color: t.ink, fontSize: 12 },
      formatter: (p: { dataType: string; data: { name: string; path: string | null; kind: KbGraphNode["kind"] } }) =>
        p.dataType === "node"
          ? `<b>${escapeHtml(p.data.name)}</b><br/><span style="opacity:.6">${KIND_LABEL[p.data.kind]}${
              p.data.path ? ` · ${escapeHtml(p.data.path)}` : ""
            }</span>`
          : "",
    },
    series: [
      {
        type: "graph",
        layout: "force",
        roam: true,
        zoom,
        draggable: true,
        scaleLimit: { min: 0.25, max: 5 },
        selectedMode: "single",
        force: {
          repulsion: n > 200 ? 55 : n > 80 ? 90 : small ? 320 : 150,
          gravity: n > 200 ? 0.12 : small ? 0.05 : 0.07,
          edgeLength: small ? [70, 160] : [28, 90],
          friction: 0.18,
          layoutAnimation: true,
        },
        labelLayout: { hideOverlap: true },
        label: { position: "right", color: t.ink2, fontSize: 10.5, distance: 4 },
        lineStyle: { color: t.lineStrong, width: 0.8, opacity: 0.8, curveness: 0 },
        emphasis: {
          focus: "adjacency",
          label: { show: true, color: t.ink },
          lineStyle: { width: 1.4, color: t.ember, opacity: 1 },
        },
        blur: { itemStyle: { opacity: 0.12 }, lineStyle: { opacity: 0.05 }, label: { opacity: 0.15 } },
        select: { itemStyle: { borderColor: t.ember, borderWidth: 2.5 }, label: { show: true, color: t.ink, fontWeight: "bold" } },
        data: graph.nodes.map((node) => {
          const at = prev.get(node.id);
          return {
            id: node.id,
            name: node.title,
            path: node.path,
            kind: node.kind,
            ...(at ? { x: at[0], y: at[1] } : {}),
            ...nodeStyle(node, t),
            label: { show: small || node.kind === "hub" || node.degree >= 4 },
          };
        }),
        links: graph.links.map((l) => ({
          source: l.source,
          target: l.target,
          lineStyle: l.type === "related" ? { type: "dashed" as const, opacity: 0.55 } : undefined,
        })),
      },
    ],
  };
}

function escapeHtml(s: string) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string);
}

/** Obsidian-style graph of the vault: drag nodes, scroll to zoom, hover for neighbours, click to open. */
export function KbGraph({ graph, selected, query, onOpen, onCreate, className }: KbGraphProps) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const ids = useRef<string[]>([]);
  const handlers = useRef({ onOpen, onCreate });
  const current = useRef({ graph, selected });
  const { theme } = useTheme();

  useEffect(() => {
    handlers.current = { onOpen, onCreate };
    current.current = { graph, selected };
  }, [onOpen, onCreate, graph, selected]);

  /** Draw the graph; `keep` continues from where the nodes are, otherwise the layout starts fresh. */
  const draw = useRef((inst: echarts.ECharts, keep: boolean) => {
    const { graph: g, selected: sel } = current.current;
    const prev = keep ? positions(inst, ids.current) : new Map();
    ids.current = g.nodes.map((n) => n.id);
    inst.setOption(buildOption(g, readTokens(), prev, inst.getWidth()), { notMerge: true });
    const i = g.nodes.findIndex((n) => n.id === sel);
    if (i >= 0) inst.dispatchAction({ type: "select", seriesIndex: 0, dataIndex: i });
  });

  useEffect(() => {
    const node = el.current;
    if (!node) return;
    const inst = echarts.init(node, undefined, { renderer: "canvas" });
    chart.current = inst;
    inst.on("click", (p) => {
      const e = p as unknown as { dataType?: string; data?: { id: string; name: string; kind: string } };
      if (e.dataType !== "node" || !e.data) return;
      if (e.data.kind === "missing") handlers.current.onCreate(e.data.name);
      else handlers.current.onOpen(e.data.id);
    });
    // Opening or closing a note resizes the panel: the old layout would sit off-centre (and a hover
    // state could stick with no mouse-out), so a real size change lays the graph out afresh.
    let size = { w: node.clientWidth, h: node.clientHeight };
    let timer = 0;
    const ro = new ResizeObserver(() => {
      inst.resize();
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        const w = node.clientWidth;
        const h = node.clientHeight;
        if (Math.abs(w - size.w) > 40 || Math.abs(h - size.h) > 40) {
          size = { w, h };
          if (ids.current.length) draw.current(inst, false);
        }
      }, 200);
    });
    ro.observe(node);
    return () => {
      window.clearTimeout(timer);
      ro.disconnect();
      inst.dispose();
      chart.current = null;
    };
  }, []);

  // Data or theme changed: rebuild, keeping each node where it was.
  useEffect(() => {
    const inst = chart.current;
    if (inst) draw.current(inst, true);
  }, [graph, theme]);

  // Selection and search are actions on the existing chart, so the layout doesn't restart.
  useEffect(() => {
    const inst = chart.current;
    if (!inst) return;
    const index = graph.nodes.findIndex((n) => n.id === selected);
    inst.dispatchAction({ type: "unselect", seriesIndex: 0, dataIndex: graph.nodes.map((_, i) => i) });
    if (index >= 0) inst.dispatchAction({ type: "select", seriesIndex: 0, dataIndex: index });
  }, [graph, selected, theme]);

  useEffect(() => {
    const inst = chart.current;
    if (!inst) return;
    const q = query.trim().toLowerCase();
    inst.dispatchAction({ type: "downplay", seriesIndex: 0 });
    if (!q) return;
    const hits = graph.nodes
      .map((n, i) => ((n.title + " " + (n.path ?? "")).toLowerCase().includes(q) ? i : -1))
      .filter((i) => i >= 0);
    if (hits.length) inst.dispatchAction({ type: "highlight", seriesIndex: 0, dataIndex: hits });
  }, [graph, query, theme]);

  return <div ref={el} role="img" aria-label="Graph of the knowledge base notes and their links" className={cn("h-full w-full", className)} />;
}

/** The key under the graph. */
export function GraphLegend({ className }: { className?: string }) {
  const item = "flex items-center gap-1.5";
  return (
    <div className={cn("flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink-2", className)}>
      <span className={item}>
        <span className="size-2.5 rounded-full bg-ember" /> Hub
      </span>
      <span className={item}>
        <span className="size-2 rounded-full bg-ink" /> Document
      </span>
      <span className={item}>
        <span className="size-2 rounded-[2px] bg-ink-2" /> Table
      </span>
      <span className={item}>
        <span className="size-2 rotate-45 bg-ink" /> Your note
      </span>
      <span className={item}>
        <span className="size-2 rounded-full border border-dashed border-dim" /> Linked, not written
      </span>
      <span className={item}>
        <span className="h-px w-4 border-t border-dashed border-line-strong" /> Related
      </span>
    </div>
  );
}
