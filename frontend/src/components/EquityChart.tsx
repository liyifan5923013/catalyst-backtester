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

export function EquityChart({ data, comparison, comparisonLabel }: Props) {
  const comparing = !!comparison && comparison.length > 0;

  const chartData = data.map((p, i) => ({
    t: p.t.slice(0, 16).replace("T", " "),
    equity: Number(p.equity.toFixed(2)),
    price: p.price != null ? Number(p.price.toFixed(2)) : null,
    // Align the comparison series by elapsed candle index so the two periods overlay.
    compare: comparing && comparison![i] ? Number(comparison![i].equity.toFixed(2)) : null,
    compareT: comparing && comparison![i] ? comparison![i].t.slice(0, 16).replace("T", " ") : null,
  }));

  const step = Math.max(1, Math.floor(chartData.length / 8));
  const cmpName = `Equity · ${comparisonLabel ?? "comparison"}`;

  return (
    <div className="chart-card">
      <div className="chart-head">
        <h3>Portfolio equity</h3>
        <span className="chart-sub">
          {comparing
            ? "Two periods overlaid by elapsed time (aligned at start). Times in UTC."
            : "Mark-to-market account value over time. Times in UTC."}
        </span>
      </div>
      <ResponsiveContainer width="100%" height={340}>
        <LineChart data={chartData} margin={{ top: 10, right: 56, left: 16, bottom: 28 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#2a2f3a" />
          <XAxis
            dataKey="t"
            tick={{ fontSize: 11, fill: axisColor }}
            interval={step}
            angle={-15}
            height={50}
            textAnchor="end"
            label={{
              value: comparing ? "Elapsed time — current period (UTC)" : "Time (UTC)",
              position: "insideBottom",
              offset: -16,
              fill: axisColor,
              fontSize: 11,
            }}
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
          <Legend wrapperStyle={{ fontSize: 11 }} />
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
  );
}
