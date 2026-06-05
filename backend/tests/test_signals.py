"""Signal evaluation robustness: malformed signals degrade, not crash."""
from __future__ import annotations

import pytest

from app.engine.signals import SignalState
from app.engine.simulator import run_backtest
from app.models import BacktestRequest, Node
from tests.synthetic import make_market_data


@pytest.fixture(scope="module")
def market_data():
    return make_market_data()


def _graph_with_signal(signal_config: dict) -> dict:
    return {
        "nodes": [
            {
                "id": "sig",
                "kind": "signal",
                "subtype": "price_threshold",
                "config": signal_config,
                "enabled": True,
            },
            {
                "id": "buy",
                "kind": "action",
                "subtype": "swap",
                "config": {"from_asset": "USDC", "to_asset": "ETH", "amount": 100, "chain": "base"},
                "enabled": True,
            },
        ],
        "edges": [{"from": "sig", "to": "buy"}],
    }


def _run(graph: dict, market_data):
    req = BacktestRequest(graph=graph, start="2024-01-01", end="2024-01-20",
                          interval="1h", initial_capital=10_000)
    return run_backtest(req, market_data=market_data)


def test_bad_operator_does_not_crash_and_warns_once(market_data):
    graph = _graph_with_signal({"symbol": "ETH", "operator": "bogus", "threshold": 2000})
    result = _run(graph, market_data)

    # The whole backtest still completes over every tick.
    assert len(result.equity_curve) == len(market_data.timeline)
    warns = [e for e in result.events if e.node_id == "sig" and "disabled" in e.message]
    assert len(warns) == 1  # warned once, then skipped — not once per tick
    assert warns[0].level == "warning"
    # The signal never fired, so no swap happened.
    assert result.metrics.num_trades == 0


def test_missing_threshold_does_not_crash(market_data):
    graph = _graph_with_signal({"symbol": "ETH", "operator": "<"})  # no threshold
    result = _run(graph, market_data)
    assert len(result.equity_curve) == len(market_data.timeline)
    assert any(e.node_id == "sig" and "disabled" in e.message for e in result.events)


def test_non_numeric_threshold_does_not_crash(market_data):
    graph = _graph_with_signal({"symbol": "ETH", "operator": "<", "threshold": "cheap"})
    result = _run(graph, market_data)
    assert len(result.equity_curve) == len(market_data.timeline)
    assert any(e.node_id == "sig" and "disabled" in e.message for e in result.events)


def test_valid_signal_still_fires(market_data):
    # ETH sweeps below 2000 in the synthetic path, so a "< 2000" signal fires
    # and triggers the buy at least once.
    graph = _graph_with_signal({"symbol": "ETH", "operator": "<", "threshold": 2000})
    result = _run(graph, market_data)
    assert result.metrics.num_trades >= 1
    assert not any("disabled" in e.message for e in result.events)


def test_signalstate_evaluate_operators():
    def node(op):
        return Node(id="s", kind="signal", subtype="price_threshold",
                    config={"operator": op, "threshold": 100})

    assert SignalState.evaluate(node("<"), 90) is True
    assert SignalState.evaluate(node("below"), 110) is False
    assert SignalState.evaluate(node(">="), 100) is True
    with pytest.raises(ValueError):
        SignalState.evaluate(node("nope"), 100)
