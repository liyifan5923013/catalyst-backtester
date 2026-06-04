"""Portfolio state: spot balances, perp positions, and yield positions.

All valuation is in USD. Stablecoins (USDC/USDT/DAI/USD) are pegged to $1.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict

STABLES = {"USDC", "USDT", "DAI", "USD"}
SECONDS_PER_YEAR = 365 * 24 * 3600

PriceFn = Callable[[str], float]  # symbol -> USD price


@dataclass
class PerpPosition:
    symbol: str
    size_tokens: float  # signed: + long, - short
    entry_price: float
    margin: float  # USD collateral allocated to this position
    leverage: float

    def notional(self, price: float) -> float:
        return abs(self.size_tokens) * price

    def unrealized_pnl(self, price: float) -> float:
        return self.size_tokens * (price - self.entry_price)

    def equity(self, price: float) -> float:
        return self.margin + self.unrealized_pnl(price)


@dataclass
class YieldPosition:
    key: str
    asset: str
    principal: float  # USD (includes accrued interest)
    apy: float


@dataclass
class Portfolio:
    cash_asset: str = "USDC"
    balances: Dict[str, float] = field(default_factory=dict)
    perps: Dict[str, PerpPosition] = field(default_factory=dict)
    yields: Dict[str, YieldPosition] = field(default_factory=dict)

    # -- spot balances --------------------------------------------------
    def get(self, asset: str) -> float:
        return self.balances.get(asset.upper(), 0.0)

    def add(self, asset: str, qty: float) -> None:
        a = asset.upper()
        self.balances[a] = self.balances.get(a, 0.0) + qty

    def sub(self, asset: str, qty: float) -> None:
        self.add(asset, -qty)

    # -- valuation ------------------------------------------------------
    @staticmethod
    def asset_price(asset: str, price_of: PriceFn) -> float:
        a = asset.upper()
        if a in STABLES:
            return 1.0
        return price_of(a)

    def spot_value(self, price_of: PriceFn) -> float:
        total = 0.0
        for asset, qty in self.balances.items():
            total += qty * self.asset_price(asset, price_of)
        return total

    def perp_value(self, price_of: PriceFn) -> float:
        total = 0.0
        for pos in self.perps.values():
            total += pos.equity(price_of(pos.symbol))
        return total

    def yield_value(self) -> float:
        return sum(p.principal for p in self.yields.values())

    def total_equity(self, price_of: PriceFn) -> float:
        return self.spot_value(price_of) + self.perp_value(price_of) + self.yield_value()

    # -- yield accrual --------------------------------------------------
    def accrue_yield(self, dt_seconds: float) -> None:
        if dt_seconds <= 0:
            return
        for pos in self.yields.values():
            growth = pos.apy * dt_seconds / SECONDS_PER_YEAR
            pos.principal *= (1.0 + growth)
