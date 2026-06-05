import { useEffect, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { EquityPoint } from "../types";

interface Props {
  data: EquityPoint[];
  comparison?: EquityPoint[] | null;
  comparisonLabel?: string | null;
}

const axisColor = "#8b93a7";

/** Compact UTC label for the x-axis (full timestamp stays in the tooltip). */
function formatAxisTick(label: string): string {
  const d = new Date(label.replace(" ", "T") + "Z");
  if (Number.isNaN(d.getTime())) return label;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

export function EquityChart({ data, comparison, comparisonLabel }: Props) {
  const comparing = !!comparison && comparison.length > 0;
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (!expanded) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setExpanded(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [expanded]);

  const chartData = data.map((p, i) => ({
    t: p.t.slice(0, 16).replace("T", " "),
    equity: Number(p.equity.toFixed(2)),
    price: p.price != null ? Number(p.price.toFixed(2)) : null,
    compare: comparing && comparison![i] ? Number(comparison![i].equity.toFixed(2)) : null,
    compareT: comparing && comparison![i] ? comparison![i].t.slice(0, 16).replace("T", " ") : null,
  }));

  const cmpName = `Equity · ${comparisonLabel ?? "comparison"}`;

  return (
    <>
      {expanded && <div className="chart-overlay" onClick={() => setExpanded(false)} />}
      <div className={`chart-card ${expanded ? "chart-fullscreen" : ""}`}>
        <div className="chart-head">
          <div className="chart-head-text">
            <h3>Portfolio equity</h3>
            <span className="chart-sub">
              {comparing
                ? "Two periods overlaid by elapsed time (aligned at start). X-axis: current period dates (UTC)."
                : "Mark-to-market account value over time. X-axis: time (UTC)."}
            </span>
          </div>
          <button
            type="button"
            className="chart-expand"
            onClick={() => setExpanded((v) => !v)}
            title={expanded ? "Exit fullscreen (Esc)" : "View fullscreen"}
          >
            {expanded ? "✕ Close" : "⤢ Fullscreen"}
          </button>
        </div>
        <div className="chart-body">
          <ResponsiveContainer width="100%" height={expanded ? "100%" : 360}>
            <LineChart data={chartData} margin={{ top: 8, right: 56, left: 16, bottom: 12 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2a2f3a" />
              <XAxis
                dataKey="t"
                tick={{ fontSize: 11, fill: axisColor }}
                tickFormatter={formatAxisTick}
                minTickGap={expanded ? 40 : 56}
                interval="preserveStartEnd"
                height={36}
              />
              <YAxis
                yAxisId="equity"
                tick={{ fontSize: 11, fill: axisColor }}
                domain={["auto", "auto"]}
                tickFormatter={(v) => `$${(v / 1000).toFixed(1)}k`}
                label={{
                  value: "Equity (USD)",
                  angle: -90,
                  position: "insideLeft",
                  fill: axisColor,
                  fontSize: 11,
                  style: { textAnchor: "middle" },
                }}
              />
              <YAxis
                yAxisId="price"
                orientation="right"
                tick={{ fontSize: 11, fill: "#6b7280" }}
                domain={["auto", "auto"]}
                tickFormatter={(v) => `$${v}`}
                label={{
                  value: "ETH price (USD)",
                  angle: 90,
                  position: "insideRight",
                  fill: "#6b7280",
                  fontSize: 11,
                  style: { textAnchor: "middle" },
                }}
              />
              <Tooltip
                contentStyle={{ background: "#161a22", border: "1px solid #2a2f3a", borderRadius: 8 }}
                labelStyle={{ color: "#cbd2e0" }}
                formatter={(value: number | string, name: string) => [value, name]}
              />
              <Legend
                verticalAlign="top"
                align="right"
                wrapperStyle={{ fontSize: 11, paddingBottom: 4, top: -4 }}
              />
              <Line
                yAxisId="equity"
                type="monotone"
                dataKey="equity"
                stroke="#4ade80"
                strokeWidth={2}
                dot={false}
                name="Equity · current"
              />
              {comparing && (
                <Line
                  yAxisId="equity"
                  type="monotone"
                  dataKey="compare"
                  stroke="#fbbf24"
                  strokeWidth={2}
                  dot={false}
                  name={cmpName}
                  strokeDasharray="5 4"
                  connectNulls
                />
              )}
              <Line
                yAxisId="price"
                type="monotone"
                dataKey="price"
                stroke="#60a5fa"
                strokeWidth={1}
                dot={false}
                name="ETH price"
                strokeDasharray="4 3"
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </>
  );
}
