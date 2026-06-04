import {
  CartesianGrid,
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
}

export function EquityChart({ data }: Props) {
  const chartData = data.map((p) => ({
    t: p.t.slice(0, 16).replace("T", " "),
    equity: Number(p.equity.toFixed(2)),
    price: p.price != null ? Number(p.price.toFixed(2)) : null,
  }));

  // Keep the x-axis readable: show ~8 ticks.
  const step = Math.max(1, Math.floor(chartData.length / 8));

  return (
    <div className="chart-card">
      <h3>Portfolio equity</h3>
      <ResponsiveContainer width="100%" height={320}>
        <LineChart data={chartData} margin={{ top: 10, right: 50, left: 10, bottom: 10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#2a2f3a" />
          <XAxis
            dataKey="t"
            tick={{ fontSize: 11, fill: "#8b93a7" }}
            interval={step}
            angle={-15}
            height={50}
            textAnchor="end"
          />
          <YAxis
            yAxisId="equity"
            tick={{ fontSize: 11, fill: "#8b93a7" }}
            domain={["auto", "auto"]}
            tickFormatter={(v) => `$${(v / 1000).toFixed(1)}k`}
          />
          <YAxis
            yAxisId="price"
            orientation="right"
            tick={{ fontSize: 11, fill: "#6b7280" }}
            domain={["auto", "auto"]}
            tickFormatter={(v) => `$${v}`}
          />
          <Tooltip
            contentStyle={{ background: "#161a22", border: "1px solid #2a2f3a", borderRadius: 8 }}
            labelStyle={{ color: "#cbd2e0" }}
          />
          <Line
            yAxisId="equity"
            type="monotone"
            dataKey="equity"
            stroke="#4ade80"
            strokeWidth={2}
            dot={false}
            name="Equity"
          />
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
