export interface EquityPoint {
  t: string;
  equity: number;
  price: number | null;
}

export interface Trade {
  t: string;
  node_id: string;
  kind: string;
  chain: string;
  symbol: string;
  side: string;
  qty: number;
  price: number;
  usd_value: number;
  fee_usd: number;
  realized_pnl: number;
  note: string;
}

export interface BacktestEvent {
  t: string;
  level: string;
  node_id: string | null;
  message: string;
}

export interface Metrics {
  initial_capital: number;
  final_equity: number;
  total_return_pct: number;
  max_drawdown_pct: number;
  sharpe: number;
  num_trades: number;
  total_fees_usd: number;
  win_rate_pct: number | null;
}

export interface BacktestResult {
  metrics: Metrics;
  equity_curve: EquityPoint[];
  trades: Trade[];
  events: BacktestEvent[];
  interval: string;
  start: string;
  end: string;
}

export interface ExampleGraph {
  name: string;
  title: string;
  graph: unknown;
}

export interface SummaryResponse {
  summary: string;
  recommendations: string[];
  source: string; // "llm" | "rule"
}
