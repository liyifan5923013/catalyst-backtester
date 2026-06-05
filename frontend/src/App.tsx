import { useEffect, useMemo, useState } from "react";
import { fetchExamples, fetchSummary, runBacktest } from "./api";
import type { BacktestResult, ExampleGraph, SummaryResponse } from "./types";
import { BacktestForm } from "./components/BacktestForm";
import { GraphInput } from "./components/GraphInput";
import { ResultsDashboard } from "./components/ResultsDashboard";
import { useIsMobile } from "./hooks/useIsMobile";
import {
  COMPARE_LABELS,
  describeGraph,
  effectiveCompareRange,
  type CompareState,
} from "./utils";

export interface Config {
  start: string;
  end: string;
  interval: string;
  initial_capital: number;
}

type MobileTab = "setup" | "results";

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
  const isMobile = useIsMobile();
  const [graphText, setGraphText] = useState(DEFAULT_GRAPH);
  const [examples, setExamples] = useState<ExampleGraph[]>([]);
  const [config, setConfig] = useState<Config>(() => {
    const iso = (d: Date) => d.toISOString().slice(0, 10);
    const end = new Date();
    const start = new Date(end.getTime() - 120 * 24 * 3600 * 1000);
    return { start: iso(start), end: iso(end), interval: "1h", initial_capital: 10000 };
  });
  const [compare, setCompare] = useState<CompareState>(() => ({
    enabled: false,
    mode: "previous",
    start: "",
    end: "",
  }));
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [compareResult, setCompareResult] = useState<BacktestResult | null>(null);
  const [compareLabel, setCompareLabel] = useState<string | null>(null);
  const [compareWarning, setCompareWarning] = useState<string | null>(null);
  const [summary, setSummary] = useState<SummaryResponse | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const [mobileTab, setMobileTab] = useState<MobileTab>("setup");

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
      if (isMobile) setMobileTab("setup");
      return;
    }
    setLoading(true);
    setError(null);
    setSummary(null);
    setCompareWarning(null);
    try {
      const graph = parsedGraph.value;
      const primary = await runBacktest({ graph, ...config });

      let cmp: BacktestResult | null = null;
      let cmpLabel: string | null = null;
      let cmpWarn: string | null = null;
      if (compare.enabled) {
        const range = effectiveCompareRange(config, compare);
        cmpLabel = COMPARE_LABELS[compare.mode];
        if (!range.start || !range.end) {
          cmpWarn = "Pick a comparison start and end date to enable the comparison.";
        } else {
          try {
            cmp = await runBacktest({
              graph,
              start: range.start,
              end: range.end,
              interval: config.interval,
              initial_capital: config.initial_capital,
            });
          } catch (e) {
            cmp = null;
            cmpWarn = `Comparison (${cmpLabel}, ${range.start} → ${range.end}) couldn't be run: ${(e as Error).message}`;
          }
        }
      }

      setResult(primary);
      setCompareResult(cmp);
      setCompareLabel(cmp ? cmpLabel : null);
      setCompareWarning(cmpWarn);
      if (isMobile) setMobileTab("results");

      void loadSummary(primary, cmp, cmp ? cmpLabel : null, graph);
    } catch (e) {
      setError((e as Error).message);
      setResult(null);
      setCompareResult(null);
      setCompareWarning(null);
      if (isMobile) setMobileTab("results");
    } finally {
      setLoading(false);
    }
  }

  async function loadSummary(
    primary: BacktestResult,
    cmp: BacktestResult | null,
    cmpLabel: string | null,
    graph: unknown
  ) {
    setSummaryLoading(true);
    try {
      const range = compare.enabled ? effectiveCompareRange(config, compare) : null;
      const res = await fetchSummary({
        metrics: primary.metrics,
        start: primary.start,
        end: primary.end,
        interval: primary.interval,
        strategy: describeGraph(graph),
        comparison_metrics: cmp ? cmp.metrics : null,
        comparison_label: cmpLabel,
        comparison_start: range?.start ?? null,
        comparison_end: range?.end ?? null,
      });
      setSummary(res);
    } catch {
      setSummary(null);
    } finally {
      setSummaryLoading(false);
    }
  }

  function handleSelectExample(name: string) {
    const ex = examples.find((e) => e.name === name);
    if (ex) setGraphText(JSON.stringify(ex.graph, null, 2));
  }

  const formProps = {
    config,
    onChange: setConfig,
    examples,
    onSelectExample: handleSelectExample,
    onRun: handleRun,
    loading,
    canRun: !parsedGraph.error,
    compare,
    onCompareChange: setCompare,
  };

  const resultsPanel = (
    <>
      {error && <div className="alert error">{error}</div>}
      {loading && <div className="alert info">Running backtest. Fetching market data may take a few seconds…</div>}
      {!loading && compareWarning && <div className="alert warn">{compareWarning}</div>}
      {!loading && !result && !error && (
        <div className="empty-state">
          <h2>No results yet</h2>
          <p>Pick an example or paste a graph, choose a date range, and run a backtest.</p>
        </div>
      )}
      {result && (
        <ResultsDashboard
          result={result}
          comparison={compareResult}
          comparisonLabel={compareLabel}
          summary={summary}
          summaryLoading={summaryLoading}
        />
      )}
    </>
  );

  if (isMobile) {
    return (
      <div className={`app mobile-app ${mobileTab === "setup" ? "mobile-tab-setup-active" : ""}`}>
        <header className="app-header mobile-header">
          <div>
            <h1>Catalyst Backtester</h1>
            <p>Strategy backtests · UTC</p>
          </div>
          <div className="header-links">
            <a className="header-link" href="/help.html">
              Help
            </a>
            <a className="header-link" href="/overview.html">
              About
            </a>
          </div>
        </header>

        <div className="mobile-body">
          {mobileTab === "setup" && (
            <section className="panel mobile-panel">
              <BacktestForm {...formProps} hideRunButton />
              <GraphInput
                value={graphText}
                onChange={setGraphText}
                jsonError={parsedGraph.error}
                compact
                collapsible
              />
            </section>
          )}

          {mobileTab === "results" && <section className="panel mobile-panel results">{resultsPanel}</section>}
        </div>

        {mobileTab === "setup" && (
          <div className="mobile-run-bar">
            <button className="run-btn run-btn-mobile" onClick={handleRun} disabled={loading || !!parsedGraph.error}>
              {loading ? "Running…" : compare.enabled ? "Run & compare" : "Run backtest"}
            </button>
          </div>
        )}

        <nav className="mobile-nav" aria-label="Main">
          <button
            type="button"
            className={`mobile-nav-btn ${mobileTab === "setup" ? "active" : ""}`}
            onClick={() => setMobileTab("setup")}
          >
            <span className="mobile-nav-icon">⚙</span>
            Setup
          </button>
          <button
            type="button"
            className={`mobile-nav-btn ${mobileTab === "results" ? "active" : ""}`}
            onClick={() => setMobileTab("results")}
          >
            <span className="mobile-nav-icon">📊</span>
            Results
            {result && <span className="mobile-nav-dot" />}
          </button>
        </nav>
      </div>
    );
  }

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-header-main">
          <div>
            <h1>Catalyst Backtester</h1>
            <p>Replay a Catalyst strategy graph against historical market data. All times in UTC.</p>
          </div>
          <div className="header-links">
            <a className="header-link" href="/help.html">
              Help
            </a>
            <a className="header-link" href="/overview.html">
              About
            </a>
          </div>
        </div>
      </header>

      <div className={`layout ${collapsed ? "collapsed" : ""}`}>
        {!collapsed && (
          <aside className="panel sidebar">
            <button
              type="button"
              className="collapse-btn"
              title="Hide the inputs panel to focus on results"
              onClick={() => setCollapsed(true)}
            >
              ‹ Hide
            </button>
            <BacktestForm {...formProps} />
            <GraphInput value={graphText} onChange={setGraphText} jsonError={parsedGraph.error} />
          </aside>
        )}

        <main className="panel results">
          {collapsed && (
            <button type="button" className="show-btn" onClick={() => setCollapsed(false)}>
              ☰ Show inputs
            </button>
          )}
          {resultsPanel}
        </main>
      </div>
    </div>
  );
}
