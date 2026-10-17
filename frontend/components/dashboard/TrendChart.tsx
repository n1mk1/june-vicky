"use client";

import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Panel } from "@/components/ui/Panel";
import { FIGURES, fmtMoney, mrrSeries } from "@/lib/tidewell";
import { palette, useTheme } from "@/lib/use-theme";
import { cn } from "@/lib/utils";

const DATA = mrrSeries();

type Metric = "mrr" | "burn";

export function TrendChart() {
  const { theme } = useTheme();
  const c = palette[theme];
  const [metric, setMetric] = useState<Metric>("mrr");

  return (
    <Panel
      title={metric === "mrr" ? "Monthly recurring revenue" : "Monthly burn excl. SR&ED"}
      marks
      aside={
        <div role="tablist" aria-label="Chart metric" className="flex gap-1">
          {(["mrr", "burn"] as const).map((m) => (
            <button
              key={m}
              role="tab"
              aria-selected={metric === m}
              onClick={() => setMetric(m)}
              className={cn(
                "rounded-full border px-2.5 py-0.5 text-[11px] transition-colors",
                metric === m ? "border-invert-bg bg-invert-bg text-invert-ink" : "border-line text-ink-2 hover:text-ink",
              )}
            >
              {m === "mrr" ? "MRR" : "Burn"}
            </button>
          ))}
        </div>
      }
      bodyClassName="flex flex-col p-3 pt-4"
    >
      <div className="min-h-[180px] flex-1">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={DATA} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
            <CartesianGrid stroke={c.line} strokeDasharray="2 4" vertical={false} />
            <XAxis
              dataKey="label"
              tick={{ fill: c.dim, fontSize: 10 }}
              tickLine={false}
              axisLine={{ stroke: c.line }}
              interval={5}
            />
            <YAxis
              tick={{ fill: c.dim, fontSize: 10 }}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v: number) => fmtMoney(v).replace(".0K", "K")}
              width={52}
            />
            <Tooltip
              cursor={{ stroke: c.dim, strokeWidth: 1 }}
              contentStyle={{
                background: theme === "dark" ? "rgba(12,13,16,0.92)" : "rgba(242,242,242,0.95)",
                border: `1px solid ${c.line}`,
                borderRadius: 10,
                fontSize: 12,
                color: c.ink,
              }}
              labelStyle={{ color: c.dim }}
              formatter={(v, name) => [fmtMoney(Number(v)), name === "trend" ? "Trend" : name === "mrr" ? "MRR" : "Burn"]}
            />
            {metric === "mrr" ? (
              <>
                <Line type="monotone" dataKey="mrr" stroke={c.ink} strokeWidth={1.5} dot={false} activeDot={{ r: 3, fill: c.ember, stroke: "none" }} />
                <Line type="monotone" dataKey="trend" stroke={c.ember} strokeWidth={1.25} strokeDasharray="4 4" dot={false} />
              </>
            ) : (
              <Line type="monotone" dataKey="burn" stroke={c.ink} strokeWidth={1.5} dot={false} activeDot={{ r: 3, fill: c.ember, stroke: "none" }} />
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="px-1 pt-2 text-[11px] leading-snug text-dim">
        {metric === "mrr"
          ? `Solid: actuals from CSV 01. Dashed: the last-two-month rate (${FIGURES.growth2.display}) carried forward. Not a forecast.`
          : "Net loss with SR&ED credits removed, so the June 2025 and July 2026 credits don't hide the spend."}
      </p>
    </Panel>
  );
}
