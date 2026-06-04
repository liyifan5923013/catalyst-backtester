"""Pydantic models for the Catalyst backtesting API.

These mirror the Catalyst graph definition format and the request/response
shape of the ``POST /backtest`` endpoint.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Graph definition (input)
# ---------------------------------------------------------------------------
class Node(BaseModel):
    id: str
    kind: str  # "action" | "signal"
    subtype: str  # swap | perp_order | yield_deposit | yield_withdraw | price_threshold
    config: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class Edge(BaseModel):
    from_: str = Field(alias="from")
    to: str

    model_config = {"populate_by_name": True}


class Graph(BaseModel):
    schema_version: Optional[str] = None
    variables: Dict[str, Any] = Field(default_factory=dict)
    settings: Dict[str, Any] = Field(default_factory=dict)
    nodes: List[Node] = Field(default_factory=list)
    edges: List[Edge] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Cost / execution assumptions (configurable, with sensible MVP defaults)
# ---------------------------------------------------------------------------
class CostModel(BaseModel):
    evm_gas_usd: float = 0.5  # flat gas per EVM transaction (Base is cheap)
    evm_swap_fee_bps: float = 5.0  # DEX fee, e.g. 0.05%
    evm_slippage_bps: float = 10.0  # assumed slippage on EVM swaps
    hl_taker_fee_bps: float = 3.5  # Hyperliquid taker fee ~0.035%
    hl_slippage_bps: float = 5.0
    perp_maintenance_margin_frac: float = 0.02  # 2% maintenance margin
    yield_apy: float = 0.05  # flat 5% APY for yield positions (MVP)


# ---------------------------------------------------------------------------
# Backtest request
# ---------------------------------------------------------------------------
class BacktestRequest(BaseModel):
    graph: Graph
    start: str  # ISO date/datetime, e.g. "2024-01-01"
    end: str
    interval: str = "1h"  # 15m | 1h | 4h | 1d
    initial_capital: float = 10_000.0
    costs: CostModel = Field(default_factory=CostModel)


# ---------------------------------------------------------------------------
# Backtest response
# ---------------------------------------------------------------------------
class EquityPoint(BaseModel):
    t: str  # ISO timestamp
    equity: float
    price: Optional[float] = None  # reference price (ETH) for context


class Trade(BaseModel):
    t: str
    node_id: str
    kind: str  # swap | perp_open | perp_close | yield_deposit | yield_withdraw
    chain: str
    symbol: str
    side: str  # buy | sell | long | short | deposit | withdraw
    qty: float  # token quantity (or USD for yield)
    price: float
    usd_value: float
    fee_usd: float
    realized_pnl: float = 0.0
    note: str = ""


class Event(BaseModel):
    t: str
    level: str  # info | warning | error
    node_id: Optional[str] = None
    message: str


class Metrics(BaseModel):
    initial_capital: float
    final_equity: float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe: float
    num_trades: int
    total_fees_usd: float
    win_rate_pct: Optional[float] = None


class BacktestResult(BaseModel):
    metrics: Metrics
    equity_curve: List[EquityPoint]
    trades: List[Trade]
    events: List[Event]
    interval: str
    start: str
    end: str
