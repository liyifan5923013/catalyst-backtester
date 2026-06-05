"""Regression tests for the audit fixes (crash safety + modeling)."""
import pytest

from app.models import BacktestRequest, CostModel, Node
from app.engine.execution import execute_perp, execute_swap, check_liquidations, ExecContext
from app.engine.portfolio import PerpPosition, Portfolio
from app.engine.simulator import run_backtest
from tests.synthetic import make_market_data


def ctx(p=2000.0):
    return ExecContext(ts_iso="t", price=lambda s, c: p)


def perp(**cfg):
    return Node(id="p", kind="action", subtype="perp_order", config=cfg, enabled=True)


def swap(**cfg):
    return Node(id="s", kind="action", subtype="swap", config=cfg, enabled=True)


# --- crash safety ---------------------------------------------------------
def test_zero_leverage_warns_not_crashes():
    pf = Portfolio(); pf.add("USDC", 10000)
    res = execute_perp(perp(symbol="ETH", side="long", size_usd="500", leverage="0",
                            chain="hyperliquid", reduce_only=False), pf, CostModel(), ctx())
    assert res.trade is None
    assert res.events and res.events[0].level == "warning"
    assert "ETH" not in pf.perps


def test_invalid_leverage_warns():
    pf = Portfolio(); pf.add("USDC", 10000)
    res = execute_perp(perp(symbol="ETH", side="long", size_usd="500", leverage="abc",
                            chain="hyperliquid", reduce_only=False), pf, CostModel(), ctx())
    assert res.trade is None and res.events[0].level == "warning"


def test_bad_amount_does_not_abort_run():
    """A malformed amount should produce an error event, not kill the backtest."""
    graph = {
        "nodes": [swap(from_asset="USDC", to_asset="ETH", amount="abc", chain="base").model_dump(by_alias=True)],
        "edges": [],
    }
    md = make_market_data()
    req = BacktestRequest(graph=graph, start="2024-01-01", end="2024-01-20",
                          interval="1h", initial_capital=10_000)
    result = run_backtest(req, market_data=md)
    assert len(result.equity_curve) == len(md.timeline)  # run completed
    assert any(e.level == "error" for e in result.events)


# --- spot cost basis / realized PnL --------------------------------------
def test_spot_sell_reports_realized_pnl():
    pf = Portfolio(); pf.add("USDC", 1000)
    execute_swap(swap(from_asset="USDC", to_asset="ETH", amount="100", chain="base"),
                 pf, CostModel(), ctx(2000))
    res = execute_swap(swap(from_asset="ETH", to_asset="USDC", amount="all", chain="base"),
                       pf, CostModel(), ctx(2500))
    assert res.trade is not None
    assert res.trade.realized_pnl > 0  # bought at 2000, sold at 2500
    assert pf.cost_basis.get("ETH", 0.0) == pytest.approx(0.0, abs=1e-9)


def test_spot_loss_is_negative():
    pf = Portfolio(); pf.add("USDC", 1000)
    execute_swap(swap(from_asset="USDC", to_asset="ETH", amount="100", chain="base"),
                 pf, CostModel(), ctx(2000))
    res = execute_swap(swap(from_asset="ETH", to_asset="USDC", amount="all", chain="base"),
                       pf, CostModel(), ctx(1800))
    assert res.trade.realized_pnl < 0


# --- reduce_only full close ----------------------------------------------
def test_reduce_only_all_fully_closes():
    pf = Portfolio(); pf.add("USDC", 10000)
    execute_perp(perp(symbol="ETH", side="long", size_usd="500", leverage="5",
                      chain="hyperliquid", reduce_only=False), pf, CostModel(), ctx(2000))
    res = execute_perp(perp(symbol="ETH", side="short", size_usd="all",
                            chain="hyperliquid", reduce_only=True), pf, CostModel(), ctx(2200))
    assert "ETH" not in pf.perps  # fully closed, no dust
    assert res.trade.realized_pnl == pytest.approx(0.25 * (2200 - 2000), rel=1e-6)


def test_reduce_only_dust_snap():
    """Closing slightly less than the full notional still snaps to a full close."""
    pf = Portfolio(); pf.add("USDC", 10000)
    execute_perp(perp(symbol="ETH", side="long", size_usd="500", leverage="5",
                      chain="hyperliquid", reduce_only=False), pf, CostModel(), ctx(2000))
    # position is 0.25 ETH; at 2000 that's $500 notional. Close $499.50 -> within $1 dust.
    execute_perp(perp(symbol="ETH", side="short", size_usd="499.5",
                      chain="hyperliquid", reduce_only=True), pf, CostModel(), ctx(2000))
    assert "ETH" not in pf.perps


# --- liquidation as a trade ----------------------------------------------
def test_liquidation_emits_trade():
    pf = Portfolio()
    # A long that is deep underwater: entry 2000, mark 1000.
    pf.perps["ETH"] = PerpPosition(symbol="ETH", size_tokens=0.5, entry_price=2000.0,
                                   margin=200.0, leverage=5.0)
    events, trades = check_liquidations(pf, lambda s: 1000.0, 0.02, "t")
    assert "ETH" not in pf.perps
    assert len(events) == 1 and len(trades) == 1
    assert trades[0].kind == "perp_close"
    assert trades[0].realized_pnl < 0
