"""Accuracy tests: hand-computed expected values for the financial math.

Unlike the fuzz suite (robustness + conservation), these pin exact numbers for
fees, slippage, gas, cost basis, realized PnL, funding, liquidation, and yield
accrual, so a change to any formula is caught.
"""
from __future__ import annotations

import pytest

from app.engine.execution import (
    ExecContext,
    apply_funding,
    check_liquidations,
    execute_perp,
    execute_swap,
    execute_yield,
)
from app.engine.portfolio import SECONDS_PER_YEAR, PerpPosition, Portfolio
from app.models import CostModel, Node


def ctx(price: float = 2000.0) -> ExecContext:
    return ExecContext(ts_iso="2024-01-01T00:00:00+00:00", price=lambda sym, chain: price)


def swap(**cfg) -> Node:
    return Node(id="n", kind="action", subtype="swap", config=cfg, enabled=True)


def perp(**cfg) -> Node:
    return Node(id="p", kind="action", subtype="perp_order", config=cfg, enabled=True)


def yld(subtype, **cfg) -> Node:
    return Node(id="y", kind="action", subtype=subtype, config=cfg, enabled=True)


# -- swap fees by venue ------------------------------------------------------
def test_equity_swap_uses_equity_costs():
    """Equity buy: 0 commission + 5 bps slippage, no gas (default CostModel)."""
    pf = Portfolio()
    pf.add("USDC", 10_000)
    execute_swap(swap(from_asset="USDC", to_asset="AAPL", amount="1000", chain="equity"),
                 pf, CostModel(), ctx(180.0))
    # slip = 1000 * 5/1e4 = 0.5; tokens = (1000 - 0 - 0.5)/180
    assert pf.get("AAPL") == pytest.approx(999.5 / 180.0, rel=1e-12)
    assert pf.get("USDC") == pytest.approx(9000.0, rel=1e-12)  # no gas on equity


def test_hyperliquid_spot_swap_uses_hl_costs():
    """HL spot buy: 3.5 bps taker + 5 bps slippage, no gas."""
    pf = Portfolio()
    pf.add("USDC", 10_000)
    execute_swap(swap(from_asset="USDC", to_asset="ETH", amount="1000", chain="hyperliquid"),
                 pf, CostModel(), ctx(2000.0))
    # fee = 0.35, slip = 0.5; tokens = (1000 - 0.35 - 0.5)/2000
    assert pf.get("ETH") == pytest.approx(999.15 / 2000.0, rel=1e-12)
    assert pf.get("USDC") == pytest.approx(9000.0, rel=1e-12)


def test_evm_swap_gas_and_fees():
    """EVM buy: 5 bps fee + 10 bps slippage + $0.5 flat gas."""
    pf = Portfolio()
    pf.add("USDC", 10_000)
    execute_swap(swap(from_asset="USDC", to_asset="ETH", amount="1000", chain="base"),
                 pf, CostModel(), ctx(2000.0))
    # fee = 0.5, slip = 1.0; tokens = (1000 - 0.5 - 1.0)/2000
    assert pf.get("ETH") == pytest.approx(998.5 / 2000.0, rel=1e-12)
    assert pf.get("USDC") == pytest.approx(10_000 - 1000 - 0.5, rel=1e-12)


# -- cost basis + realized PnL on partial sell ------------------------------
def test_partial_sell_realized_pnl_and_cost_basis():
    pf = Portfolio()
    pf.add("USDC", 10_000)
    # Buy: tokens = 998.5/2000 = 0.49925, cost basis = 1000 + 0.5 gas = 1000.5
    execute_swap(swap(from_asset="USDC", to_asset="ETH", amount="1000", chain="base"),
                 pf, CostModel(), ctx(2000.0))
    held = pf.get("ETH")
    assert held == pytest.approx(0.49925, rel=1e-12)
    assert pf.cost_basis["ETH"] == pytest.approx(1000.5, rel=1e-12)

    # Sell exactly half at 2200.
    res = execute_swap(swap(from_asset="ETH", to_asset="USDC", amount=str(held / 2), chain="base"),
                       pf, CostModel(), ctx(2200.0))
    # gross = 0.249625 * 2200 = 549.175
    # fees = 5bps + 10bps + 0.5 gas = 0.2745875 + 0.549175 + 0.5
    # usd_out = 549.175 - 1.3237625 = 547.8512375
    # cost_removed = 1000.5 * 0.5 = 500.25 ; realized = 547.8512375 - 500.25
    assert res.trade.realized_pnl == pytest.approx(47.6012375, rel=1e-9)
    assert pf.cost_basis["ETH"] == pytest.approx(500.25, rel=1e-12)


# -- perp PnL ----------------------------------------------------------------
def test_perp_short_profit_on_price_drop():
    pf = Portfolio()
    pf.add("USDC", 10_000)
    costs = CostModel(hl_taker_fee_bps=0.0)
    # Short $500 at 5x, price 2000: margin 100, size -0.25.
    execute_perp(perp(symbol="ETH", side="short", size_usd="500", leverage="5",
                      chain="hyperliquid", reduce_only=False), pf, costs, ctx(2000))
    assert pf.perps["ETH"].size_tokens == pytest.approx(-0.25)
    assert pf.get("USDC") == pytest.approx(9900.0)

    # Price falls to 1800: close all. realized = -1 * 0.25 * (1800-2000) = +50.
    execute_perp(perp(symbol="ETH", side="short", size_usd="all",
                      chain="hyperliquid", reduce_only=True), pf, costs, ctx(1800))
    assert "ETH" not in pf.perps
    # cash = 9900 + released margin 100 + realized 50 = 10050.
    assert pf.get("USDC") == pytest.approx(10050.0)


def test_perp_add_same_direction_weighted_entry():
    pf = Portfolio()
    pf.add("USDC", 10_000)
    costs = CostModel(hl_taker_fee_bps=0.0)
    execute_perp(perp(symbol="ETH", side="long", size_usd="500", leverage="5",
                      chain="hyperliquid"), pf, costs, ctx(2000))
    execute_perp(perp(symbol="ETH", side="long", size_usd="500", leverage="5",
                      chain="hyperliquid"), pf, costs, ctx(2200))
    pos = pf.perps["ETH"]
    # sizes: 0.25 @2000 + (500/2200) @2200; notional2 = 500.
    # entry = (0.25*2000 + 500) / (0.25 + 500/2200) = 1000 / 0.47727... = 2095.238
    assert pos.size_tokens == pytest.approx(0.25 + 500 / 2200, rel=1e-12)
    assert pos.entry_price == pytest.approx(1000.0 / (0.25 + 500 / 2200), rel=1e-9)
    assert pos.margin == pytest.approx(200.0)


# -- funding -----------------------------------------------------------------
def test_funding_charges_long_when_rate_positive():
    pf = Portfolio()
    pf.perps["ETH"] = PerpPosition(symbol="ETH", size_tokens=0.25, entry_price=2000.0,
                                   margin=100.0, leverage=5.0)
    # payment = sign(+1) * rate * notional = 0.0001 * (0.25*2000=500) = 0.05
    apply_funding(pf, "ETH", rate=0.0001, price=2000.0, ts_iso="t")
    assert pf.perps["ETH"].margin == pytest.approx(100.0 - 0.05, rel=1e-12)


def test_funding_pays_short_when_rate_positive():
    pf = Portfolio()
    pf.perps["ETH"] = PerpPosition(symbol="ETH", size_tokens=-0.25, entry_price=2000.0,
                                   margin=100.0, leverage=5.0)
    # short: sign(-1) * 0.0001 * 500 = -0.05 -> margin increases.
    apply_funding(pf, "ETH", rate=0.0001, price=2000.0, ts_iso="t")
    assert pf.perps["ETH"].margin == pytest.approx(100.0 + 0.05, rel=1e-12)


# -- liquidation threshold ---------------------------------------------------
def test_liquidation_triggers_below_maintenance():
    # Long 0.5 @2000, margin 50. equity(p)=50+0.5(p-2000); maintenance=0.02*0.5*p.
    # Liquidate when 50+0.5p-1000 <= 0.01p  ->  p <= 950/0.49 = 1938.78.
    pf = Portfolio()
    pf.perps["ETH"] = PerpPosition(symbol="ETH", size_tokens=0.5, entry_price=2000.0,
                                   margin=50.0, leverage=20.0)
    events, trades = check_liquidations(pf, lambda s: 1900.0, 0.02, "t")
    assert "ETH" not in pf.perps
    assert len(trades) == 1
    # realized = unrealized at 1900 = 0.5*(1900-2000) = -50.
    assert trades[0].realized_pnl == pytest.approx(-50.0)
    assert any(e.level == "warning" for e in events)


def test_no_liquidation_above_maintenance():
    pf = Portfolio()
    pf.perps["ETH"] = PerpPosition(symbol="ETH", size_tokens=0.5, entry_price=2000.0,
                                   margin=50.0, leverage=20.0)
    events, trades = check_liquidations(pf, lambda s: 1950.0, 0.02, "t")
    # equity=25, maintenance=0.02*0.5*1950=19.5 -> survives.
    assert "ETH" in pf.perps
    assert trades == []


# -- yield accrual -----------------------------------------------------------
def test_yield_accrual_full_year():
    pf = Portfolio()
    pf.add("USDC", 10_000)
    execute_yield(yld("yield_deposit", chain="base", protocol="aave", pool="p",
                      asset="USDC", amount="1000"), pf, CostModel(), ctx())
    # 5% APY for exactly one year -> 1000 * 1.05.
    pf.accrue_yield(SECONDS_PER_YEAR)
    assert pf.yield_value() == pytest.approx(1050.0, rel=1e-12)


def test_yield_accrual_half_year():
    pf = Portfolio()
    pf.yields.clear()
    pf.add("USDC", 10_000)
    execute_yield(yld("yield_deposit", chain="base", protocol="aave", pool="p",
                      asset="USDC", amount="1000"), pf, CostModel(), ctx())
    pf.accrue_yield(SECONDS_PER_YEAR / 2)
    assert pf.yield_value() == pytest.approx(1000.0 * (1.0 + 0.05 / 2), rel=1e-12)
