import type { BacktestResult } from "../types";
import { EquityChart } from "./EquityChart";
import { TradeLog } from "./TradeLog";

interface Props {
  result: BacktestResult;
}

const money = (n: number) =>
  n.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 2 });

export function ResultsDashboard({ result }: Props) {
  const m = result.metrics;
  const ret = m.total_return_pct;
  return (
    <div className="dashboard">
      <div className="metrics-grid">
        <Metric label="Final equity" value={money(m.final_equity)} />
        <Metric
          label="Total return"
          value={`${ret >= 0 ? "+" : ""}${ret.toFixed(2)}%`}
          tone={ret > 0 ? "pos" : ret < 0 ? "neg" : "neutral"}
        />
        <Metric label="Max drawdown" value={`${m.max_drawdown_pct.toFixed(2)}%`} tone="neg" />
        <Metric label="Sharpe" value={m.sharpe.toFixed(2)} />
        <Metric label="Trades" value={String(m.num_trades)} />
        <Metric label="Total fees" value={money(m.total_fees_usd)} />
        {m.win_rate_pct != null && <Metric label="Win rate" value={`${m.win_rate_pct.toFixed(0)}%`} />}
        <Metric label="Initial capital" value={money(m.initial_capital)} />
      </div>

      <EquityChart data={result.equity_curve} />

      {result.events.length > 0 && (
        <div className="events-card">
          <h3>Events ({result.events.length})</h3>
          <ul>
            {result.events.slice(0, 50).map((e, i) => (
              <li key={i} className={`event ${e.level}`}>
                <span className="mono">{e.t.slice(0, 16).replace("T", " ")}</span>
                <span className={`level ${e.level}`}>{e.level}</span>
                <span>{e.message}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <TradeLog trades={result.trades} />
    </div>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="metric">
      <span className="metric-label">{label}</span>
      <span className={`metric-value ${tone ?? ""}`}>{value}</span>
    </div>
  );
}
