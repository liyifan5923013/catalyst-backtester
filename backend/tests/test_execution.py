import pytest

from app.models import CostModel, Node
from app.engine.execution import execute_perp, execute_swap, execute_yield, ExecContext
from app.engine.portfolio import Portfolio


def ctx(price_eth: float = 2000.0) -> ExecContext:
    return ExecContext(ts_iso="2024-01-01T00:00:00+00:00", price=lambda sym, chain: price_eth)


def swap_node(**cfg) -> Node:
    return Node(id="n", kind="action", subtype="swap", config=cfg, enabled=True)


def test_swap_buy_eth():
    pf = Portfolio()
    pf.add("USDC", 1000)
    res = execute_swap(swap_node(from_asset="USDC", to_asset="ETH", amount="100", chain="base"),
                       pf, CostModel(), ctx(2000))
    assert res.trade is not None
    # 100 USD in, 0.05% fee + 0.10% slippage, then /2000
    assert pf.get("ETH") == pytest.approx((100 - 0.05 - 0.10) / 2000, rel=1e-6)
    assert pf.get("USDC") == pytest.approx(1000 - 100 - 0.5, rel=1e-9)  # incl gas


def test_swap_sell_all():
    pf = Portfolio()
    pf.add("ETH", 0.5)
    res = execute_swap(swap_node(from_asset="ETH", to_asset="USDC", amount="all", chain="base"),
                       pf, CostModel(), ctx(2000))
    assert res.trade is not None
    assert pf.get("ETH") == pytest.approx(0.0, abs=1e-12)
    assert pf.get("USDC") > 900  # ~1000 minus fees/gas


def test_swap_insufficient_balance_warns():
    pf = Portfolio()
    pf.add("USDC", 50)
    res = execute_swap(swap_node(from_asset="USDC", to_asset="ETH", amount="100", chain="base"),
                       pf, CostModel(), ctx(2000))
    assert res.trade is None
    assert res.events and res.events[0].level == "warning"


def perp_node(**cfg) -> Node:
    return Node(id="p", kind="action", subtype="perp_order", config=cfg, enabled=True)


def test_perp_open_and_close_profit():
    pf = Portfolio()
    pf.add("USDC", 10000)
    execute_perp(perp_node(symbol="ETH", side="long", size_usd="500", leverage="5",
                           chain="hyperliquid", reduce_only=False), pf, CostModel(), ctx(2000))
    assert "ETH" in pf.perps
    pos = pf.perps["ETH"]
    assert pos.size_tokens == pytest.approx(0.25)
    assert pos.margin == pytest.approx(100.0)

    # price rises to 2200; close enough notional to fully exit (0.25*2200=550)
    execute_perp(perp_node(symbol="ETH", side="short", size_usd="600",
                           chain="hyperliquid", reduce_only=True), pf, CostModel(), ctx(2200))
    assert "ETH" not in pf.perps  # fully closed
    # realized pnl = 0.25 * (2200-2000) = 50; equity recovered + profit
    assert pf.get("USDC") > 10000


def test_perp_reduce_only_without_position_warns():
    pf = Portfolio()
    pf.add("USDC", 10000)
    res = execute_perp(perp_node(symbol="ETH", side="short", size_usd="500",
                                 chain="hyperliquid", reduce_only=True), pf, CostModel(), ctx(2000))
    assert res.trade is None
    assert res.events[0].level == "warning"


def yield_node(subtype, **cfg) -> Node:
    return Node(id="y", kind="action", subtype=subtype, config=cfg, enabled=True)


def test_yield_deposit_then_withdraw_all():
    pf = Portfolio()
    pf.add("USDC", 1000)
    execute_yield(yield_node("yield_deposit", chain="base", protocol="aave", pool="usdc",
                             asset="USDC", amount="250"), pf, CostModel(), ctx())
    assert pf.yield_value() == pytest.approx(250.0)
    assert pf.get("USDC") == pytest.approx(1000 - 250 - 0.5)

    execute_yield(yield_node("yield_withdraw", chain="base", protocol="aave", pool="usdc",
                             asset="USDC", amount="all"), pf, CostModel(), ctx())
    assert pf.yield_value() == pytest.approx(0.0)
    # back to ~999 (two gas charges)
    assert pf.get("USDC") == pytest.approx(999.0)
