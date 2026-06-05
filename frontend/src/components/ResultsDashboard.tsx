import type { BacktestResult, Metrics, SummaryResponse } from "../types";
import { EquityChart } from "./EquityChart";
import { TradeLog } from "./TradeLog";
import { fmtMoney } from "../utils";

interface Props {
  result: BacktestResult;
  comparison?: BacktestResult | null;
  comparisonLabel?: string | null;
  summary: SummaryResponse | null;
  summaryLoading: boolean;
}

type Kind = "money" | "pct" | "ratio" | "num";

interface Spec {
  key: keyof Metrics;
  label: string;
  kind: Kind;
  help: string;
  higherBetter?: boolean; // undefined = neutral (no green/red on delta)
  valueTone?: (v: number) => string;
}

const SPECS: Spec[] = [
  {
    key: "final_equity",
    label: "Final equity",
    kind: "money",
    help: "Mark-to-market account value at the end of the period (cash + positions).",
    higherBetter: true,
  },
  {
    key: "total_return_pct",
    label: "Total return",
    kind: "pct",
    help: "(Final equity − initial capital) ÷ initial capital, over the whole period.",
    higherBetter: true,
    valueTone: (v) => (v > 0 ? "pos" : v < 0 ? "neg" : ""),
  },
  {
    key: "max_drawdown_pct",
    label: "Max drawdown",
    kind: "pct",
    help: "Largest peak-to-trough drop in equity during the period. Lower is better.",
    higherBetter: false,
    valueTone: () => "neg",
  },
  {
    key: "sharpe",
    label: "Sharpe ratio",
    kind: "ratio",
    help: "Annualized risk-adjusted return: mean ÷ std-dev of per-candle returns. Higher is better.",
    higherBetter: true,
  },
  {
    key: "num_trades",
    label: "Trades",
    kind: "num",
    help: "Number of executed trades, including any forced liquidations.",
  },
  {
    key: "total_fees_usd",
    label: "Total fees",
    kind: "money",
    help: "Sum of modeled trading fees, slippage and gas across all trades. Lower is better.",
    higherBetter: false,
  },
  {
    key: "win_rate_pct",
    label: "Win rate",
    kind: "pct",
    help: "Share of closing trades that realized a positive PnL.",
    higherBetter: true,
  },
  {
    key: "initial_capital",
    label: "Initial capital",
    kind: "money",
    help: "Starting cash provided to the strategy.",
  },
];

function fmtValue(v: number, kind: Kind, signed = false): string {
  switch (kind) {
    case "money":
      return `${signed && v >= 0 ? "+" : v < 0 ? "-" : ""}${fmtMoney(Math.abs(v))}`;
    case "pct":
      return `${signed && v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
    case "ratio":
      return `${signed && v >= 0 ? "+" : ""}${v.toFixed(2)}`;
    case "num":
      return `${signed && v >= 0 ? "+" : ""}${v}`;
  }
}

export function ResultsDashboard({ result, comparison, comparisonLabel, summary, summaryLoading }: Props) {
  const m = result.metrics;
  const cmp = comparison?.metrics ?? null;
  const label = comparisonLabel ?? "comparison";

  return (
    <div className="dashboard">
      {(summary || summaryLoading) && (
        <SummaryCard summary={summary} loading={summaryLoading} />
      )}

      <div className="metrics-grid">
        {SPECS.map((s) => {
          const raw = m[s.key];
          if (raw == null) return null;
          const value = Number(raw);
          const prevRaw = cmp ? cmp[s.key] : null;
          const prev = prevRaw == null ? null : Number(prevRaw);
          return (
            <MetricCard
              key={s.key}
              spec={s}
              value={value}
              prev={prev}
              label={label}
            />
          );
        })}
      </div>

      <EquityChart
        data={result.equity_curve}
        comparison={comparison?.equity_curve ?? null}
        comparisonLabel={comparisonLabel}
      />

      {result.events.length > 0 && (
        <div className="events-card">
          <h3>Events ({result.events.length})</h3>
          <ul>
            {result.events.slice(0, 50).map((e, i) => (
              <li key={i} className={`event ${e.level}`}>
                <span className="mono">{e.t.slice(0, 16).replace("T", " ")} UTC</span>
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

function MetricCard({
  spec,
  value,
  prev,
  label,
}: {
  spec: Spec;
  value: number;
  prev: number | null;
  label: string;
}) {
  const tone = spec.valueTone ? spec.valueTone(value) : "";
  let deltaEl = null;
  if (prev != null) {
    const d = value - prev;
    const eps = spec.kind === "num" ? 0 : 1e-9;
    let deltaTone = "dim";
    let arrow = "→";
    if (d > eps) {
      arrow = "▲";
      deltaTone = spec.higherBetter == null ? "dim" : spec.higherBetter ? "pos" : "neg";
    } else if (d < -eps) {
      arrow = "▼";
      deltaTone = spec.higherBetter == null ? "dim" : spec.higherBetter ? "neg" : "pos";
    }
    const unit = spec.kind === "pct" || spec.kind === "ratio" ? " pts" : "";
    deltaEl = (
      <span className={`metric-delta ${deltaTone}`} title={`vs ${label}: ${fmtValue(prev, spec.kind)}`}>
        {arrow} {fmtValue(d, spec.kind, true)}
        {unit} <span className="metric-delta-label">vs {label}</span>
      </span>
    );
  }

  return (
    <div className="metric">
      <span className="metric-label" title={spec.help}>
        {spec.label}
        <span className="info-dot" title={spec.help}>
          i
        </span>
      </span>
      <span className={`metric-value ${tone}`}>{fmtValue(value, spec.kind)}</span>
      {deltaEl}
    </div>
  );
}

function SummaryCard({ summary, loading }: { summary: SummaryResponse | null; loading: boolean }) {
  return (
    <div className="summary-card">
      <div className="summary-head">
        <h3>Summary &amp; recommendations</h3>
        {summary && (
          <span className={`summary-badge ${summary.source}`}>
            {summary.source === "llm" ? "AI generated" : "Auto (heuristic)"}
          </span>
        )}
      </div>
      {loading && !summary ? (
        <p className="summary-loading">Generating summary…</p>
      ) : summary ? (
        <>
          <p className="summary-text">{summary.summary}</p>
          {summary.recommendations.length > 0 && (
            <ul className="summary-recs">
              {summary.recommendations.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          )}
        </>
      ) : null}
    </div>
  );
}
