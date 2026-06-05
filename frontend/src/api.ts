import type { BacktestResult, ExampleGraph, Metrics, SummaryResponse } from "./types";

const BASE = "/api";

export interface BacktestParams {
  graph: unknown;
  start: string;
  end: string;
  interval: string;
  initial_capital: number;
}

export async function runBacktest(params: BacktestParams): Promise<BacktestResult> {
  const resp = await fetch(`${BASE}/backtest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!resp.ok) {
    let detail = `Request failed (${resp.status})`;
    try {
      const body = await resp.json();
      if (body.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return resp.json();
}

export async function fetchExamples(): Promise<ExampleGraph[]> {
  const resp = await fetch(`${BASE}/examples`);
  if (!resp.ok) return [];
  return resp.json();
}

export interface SummaryParams {
  metrics: Metrics;
  start: string;
  end: string;
  interval: string;
  strategy?: string;
  comparison_metrics?: Metrics | null;
  comparison_label?: string | null;
  comparison_start?: string | null;
  comparison_end?: string | null;
}

export async function fetchSummary(params: SummaryParams): Promise<SummaryResponse> {
  const resp = await fetch(`${BASE}/summary`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!resp.ok) {
    let detail = `Summary request failed (${resp.status})`;
    try {
      const body = await resp.json();
      if (body.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return resp.json();
}
