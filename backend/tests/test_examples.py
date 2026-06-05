"""Run all example graphs against deterministic synthetic data (offline)."""
import json
import os

import pytest

from app.models import BacktestRequest
from app.engine.simulator import run_backtest
from tests.synthetic import make_market_data

EXAMPLES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "examples")
EXAMPLE_FILES = sorted(f for f in os.listdir(EXAMPLES_DIR) if f.endswith(".json"))


@pytest.fixture(scope="module")
def market_data():
    return make_market_data()


@pytest.mark.parametrize("name", EXAMPLE_FILES)
def test_example_runs(name, market_data):
    with open(os.path.join(EXAMPLES_DIR, name)) as f:
        graph = json.load(f)["graph"]
    req = BacktestRequest(graph=graph, start="2024-01-01", end="2024-01-20",
                          interval="1h", initial_capital=10_000)
    result = run_backtest(req, market_data=market_data)

    # The equity curve covers every tick.
    assert len(result.equity_curve) == len(market_data.timeline)
    # Equity stays finite and non-negative.
    for pt in result.equity_curve:
        assert pt.equity == pt.equity  # not NaN
        assert pt.equity >= 0
    # Metrics are internally consistent.
    assert result.metrics.initial_capital == 10_000
    assert result.metrics.final_equity == pytest.approx(result.equity_curve[-1].equity)
    assert result.metrics.num_trades == len(result.trades)


def test_signal_ladder_executes_multiple_trades(market_data):
    """Graph 4 is a repeating ladder: signals should fire repeatedly."""
    with open(os.path.join(EXAMPLES_DIR, "graph_04.json")) as f:
        graph = json.load(f)["graph"]
    req = BacktestRequest(graph=graph, start="2024-01-01", end="2024-01-20",
                          interval="1h", initial_capital=10_000)
    result = run_backtest(req, market_data=market_data)
    # initial inventory + multiple signal-driven buys/sells
    assert result.metrics.num_trades >= 5
