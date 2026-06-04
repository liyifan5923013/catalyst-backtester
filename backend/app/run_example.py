"""Command-line runner for a single graph file.

Usage:
    python -m app.run_example examples/graph_12.json --start 2024-01-01 --end 2024-06-01 --interval 1h
"""
from __future__ import annotations

import argparse
import json
import sys

from .models import BacktestRequest
from .engine.simulator import run_backtest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run a Catalyst graph backtest.")
    parser.add_argument("graph", help="Path to a graph JSON file (raw graph or {title, graph}).")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--initial", type=float, default=10_000.0)
    args = parser.parse_args(argv)

    with open(args.graph, "r") as f:
        data = json.load(f)
    graph = data.get("graph", data)

    req = BacktestRequest(
        graph=graph, start=args.start, end=args.end,
        interval=args.interval, initial_capital=args.initial,
    )
    result = run_backtest(req)

    m = result.metrics
    print(f"\n=== Backtest: {args.graph} ({args.start} -> {args.end}, {args.interval}) ===")
    print(f"Initial capital : ${m.initial_capital:,.2f}")
    print(f"Final equity    : ${m.final_equity:,.2f}")
    print(f"Total return    : {m.total_return_pct:+.2f}%")
    print(f"Max drawdown    : {m.max_drawdown_pct:.2f}%")
    print(f"Sharpe          : {m.sharpe:.2f}")
    print(f"Trades          : {m.num_trades}")
    print(f"Total fees      : ${m.total_fees_usd:,.2f}")
    if m.win_rate_pct is not None:
        print(f"Win rate        : {m.win_rate_pct:.1f}%")
    if result.events:
        print(f"\nEvents ({len(result.events)}):")
        for e in result.events[:20]:
            print(f"  [{e.level}] {e.t} {e.message}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
