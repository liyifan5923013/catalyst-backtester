"""Property-based fuzz test: hundreds of generated graphs must never crash.

For each seed we generate a randomized-but-valid Catalyst graph and run it
through the real engine against deterministic synthetic data, asserting the
invariants that must hold for *any* strategy:

- the engine does not raise,
- the equity curve covers every tick,
- equity stays finite and non-negative,
- the reported metrics reconcile with the equity curve and trade log.

Seeds make each failing case reproducible: run the generator with the same
``--seed`` to inspect the offending graph.
"""
from __future__ import annotations

import math
import random

import pytest

import pandas as pd

from app.data.providers import MarketData
from app.engine.simulator import run_backtest
from app.models import BacktestRequest, CostModel
from tests.graph_gen import generate_graph
from tests.synthetic import make_market_data

N_CASES = 250


@pytest.fixture(scope="module")
def market_data():
    return make_market_data()


@pytest.fixture(scope="module")
def flat_market():
    """A frictionless market: constant prices, no funding events.

    Used as an accuracy oracle -- in this world value is conserved, so equity
    must stay exactly at initial capital regardless of what actions fire.
    """
    idx = pd.date_range("2024-01-01", periods=200, freq="h", tz="UTC")
    frame = pd.DataFrame(index=idx)
    frame["ETH@evm"] = 2000.0
    frame["ETH@hyperliquid"] = 2000.0
    frame["AAPL@equity"] = 180.0
    frame["SPY@equity"] = 450.0
    return MarketData(timeline=idx, interval="1h", _price_frame=frame, funding_events=[])


ZERO_COST = CostModel(
    evm_gas_usd=0.0,
    evm_swap_fee_bps=0.0,
    evm_slippage_bps=0.0,
    hl_taker_fee_bps=0.0,
    hl_slippage_bps=0.0,
    yield_apy=0.0,
    equity_commission_bps=0.0,
    equity_slippage_bps=0.0,
)


@pytest.mark.parametrize("seed", range(N_CASES))
def test_generated_graph_runs_without_crashing(seed, market_data):
    graph = generate_graph(random.Random(seed))
    req = BacktestRequest(
        graph=graph,
        start="2024-01-01",
        end="2024-01-20",
        interval="1h",
        initial_capital=10_000,
    )

    result = run_backtest(req, market_data=market_data)

    assert len(result.equity_curve) == len(market_data.timeline)
    for pt in result.equity_curve:
        assert math.isfinite(pt.equity), f"non-finite equity (seed={seed})"
        assert pt.equity >= 0, f"negative equity (seed={seed})"

    m = result.metrics
    assert m.initial_capital == 10_000
    assert m.num_trades == len(result.trades)
    assert m.final_equity == pytest.approx(result.equity_curve[-1].equity)
    assert math.isfinite(m.total_return_pct)
    assert math.isfinite(m.sharpe)
    # Drawdown is a percentage in [0, 100].
    assert 0 <= m.max_drawdown_pct <= 100 + 1e-9


@pytest.mark.parametrize("seed", range(N_CASES))
def test_value_conserved_in_frictionless_market(seed, flat_market):
    """Accuracy oracle: with zero costs, no funding, and constant prices, equity
    must stay exactly at initial capital for *any* generated graph. Any
    accounting bug (mismatched cost basis, dropped margin, double-counted
    principal) would break conservation here."""
    graph = generate_graph(random.Random(seed))
    req = BacktestRequest(
        graph=graph, start="2024-01-01", end="2024-01-20",
        interval="1h", initial_capital=10_000, costs=ZERO_COST,
    )
    result = run_backtest(req, market_data=flat_market)
    for pt in result.equity_curve:
        assert pt.equity == pytest.approx(10_000, rel=1e-9, abs=1e-4), (
            f"value not conserved (seed={seed}): equity={pt.equity}"
        )
    assert result.metrics.total_return_pct == pytest.approx(0.0, abs=1e-6)
    assert result.metrics.max_drawdown_pct == pytest.approx(0.0, abs=1e-6)


def test_generator_exercises_all_action_types():
    """Across many seeds the generator should cover every subtype + signals."""
    subtypes = set()
    has_signal = False
    has_edges = False
    for seed in range(N_CASES):
        g = generate_graph(random.Random(seed))
        for node in g["nodes"]:
            subtypes.add(node["subtype"])
            if node["kind"] == "signal":
                has_signal = True
        if g["edges"]:
            has_edges = True
    assert {"swap", "perp_order", "yield_deposit", "yield_withdraw"} <= subtypes
    assert "price_threshold" in subtypes
    assert has_signal and has_edges


def test_generated_graphs_produce_some_trades(market_data):
    """Sanity: the fuzz corpus is active, not a pile of no-op graphs."""
    total_trades = 0
    for seed in range(N_CASES):
        graph = generate_graph(random.Random(seed))
        req = BacktestRequest(
            graph=graph, start="2024-01-01", end="2024-01-20",
            interval="1h", initial_capital=10_000,
        )
        total_trades += len(run_backtest(req, market_data=market_data).trades)
    assert total_trades > 0
