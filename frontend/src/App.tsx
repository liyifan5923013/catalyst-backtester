import { useEffect, useMemo, useState } from "react";
import { fetchExamples, runBacktest } from "./api";
import type { BacktestResult, ExampleGraph } from "./types";
import { BacktestForm } from "./components/BacktestForm";
import { GraphInput } from "./components/GraphInput";
import { ResultsDashboard } from "./components/ResultsDashboard";

export interface Config {
  start: string;
  end: string;
  interval: string;
  initial_capital: number;
}

const DEFAULT_GRAPH = JSON.stringify(
  {
    nodes: [
      {
        id: "buy-eth-on-base",
        kind: "action",
        subtype: "swap",
        config: { from_asset: "USDC", to_asset: "ETH", amount: "100", chain: "base" },
        enabled: true,
      },
    ],
    edges: [],
  },
  null,
  2
);

export default function App() {
  const [graphText, setGraphText] = useState(DEFAULT_GRAPH);
  const [examples, setExamples] = useState<ExampleGraph[]>([]);
  const [config, setConfig] = useState<Config>(() => {
    const iso = (d: Date) => d.toISOString().slice(0, 10);
    const end = new Date();
    const start = new Date(end.getTime() - 120 * 24 * 3600 * 1000);
    return { start: iso(start), end: iso(end), interval: "1h", initial_capital: 10000 };
  });
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchExamples().then(setExamples).catch(() => setExamples([]));
  }, []);

  const parsedGraph = useMemo(() => {
    try {
      return { value: JSON.parse(graphText), error: null as string | null };
    } catch (e) {
      return { value: null, error: (e as Error).message };
    }
  }, [graphText]);

  async function handleRun() {
    if (parsedGraph.error || !parsedGraph.value) {
      setError(`Invalid graph JSON: ${parsedGraph.error}`);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await runBacktest({ graph: parsedGraph.value, ...config });
      setResult(res);
    } catch (e) {
      setError((e as Error).message);
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  function handleSelectExample(name: string) {
    const ex = examples.find((e) => e.name === name);
    if (ex) setGraphText(JSON.stringify(ex.graph, null, 2));
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>Catalyst Backtester</h1>
        <p>Replay a Catalyst strategy graph against historical market data.</p>
      </header>

      <div className="layout">
        <aside className="panel sidebar">
          <BacktestForm
            config={config}
            onChange={setConfig}
            examples={examples}
            onSelectExample={handleSelectExample}
            onRun={handleRun}
            loading={loading}
            canRun={!parsedGraph.error}
          />
          <GraphInput value={graphText} onChange={setGraphText} jsonError={parsedGraph.error} />
        </aside>

        <main className="panel results">
          {error && <div className="alert error">{error}</div>}
          {loading && <div className="alert info">Running backtest. Fetching market data may take a few seconds…</div>}
          {!loading && !result && !error && (
            <div className="empty-state">
              <h2>No results yet</h2>
              <p>Pick an example or paste a graph, choose a date range, and run a backtest.</p>
            </div>
          )}
          {result && <ResultsDashboard result={result} />}
        </main>
      </div>
    </div>
  );
}
