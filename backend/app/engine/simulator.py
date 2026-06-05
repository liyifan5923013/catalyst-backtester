"""The tick-loop simulator: replays a Catalyst graph over historical data.

Per tick (one candle):
  1. accrue yield for the elapsed time,
  2. apply any perp funding payments due,
  3. check for liquidations,
  4. at t0 only, run the root actions (and their action chains),
  5. evaluate signals and fire actions on rising edges,
  6. record portfolio equity.
"""
from __future__ import annotations

from typing import List

import pandas as pd

from ..models import BacktestRequest, BacktestResult, EquityPoint, Event, Trade
from .execution import (
    ExecContext,
    apply_funding,
    check_liquidations,
    execute_perp,
    execute_swap,
    execute_yield,
)
from .graph import build_runtime
from .metrics import compute_metrics
from .portfolio import Portfolio
from .signals import SignalState

EXECUTORS = {
    "swap": execute_swap,
    "perp_order": execute_perp,
    "yield_deposit": execute_yield,
    "yield_withdraw": execute_yield,
}


def run_backtest(req: BacktestRequest, market_data=None) -> BacktestResult:
    """Run a backtest. ``market_data`` may be injected for tests/offline runs."""
    from .. data.providers import MarketData  # local import to keep tests light

    runtime = build_runtime(req.graph)
    price_reqs, funding_symbols = runtime.data_requirements()

    md = market_data or MarketData.build(
        price_reqs, funding_symbols, req.interval, req.start, req.end
    )
    timeline = md.timeline
    if len(timeline) == 0:
        raise RuntimeError("No ticks in the requested range.")

    pf = Portfolio()
    pf.add("USDC", req.initial_capital)

    signal_state = SignalState(runtime.signal_ids)
    trades: List[Trade] = []
    events: List[Event] = []
    equity_curve: List[EquityPoint] = []

    state = {"ts": timeline[0]}

    def price_of(symbol: str) -> float:
        return md.price_for_balance(symbol, state["ts"])

    def exec_price(symbol: str, chain: str) -> float:
        return md.price(symbol, chain, state["ts"])

    ctx = ExecContext(ts_iso="", price=exec_price)

    def fire_action(action_id: str, ts_iso: str, visited: set) -> None:
        if action_id in visited:
            return
        visited.add(action_id)
        node = runtime.node(action_id)
        if not node.enabled:
            return
        executor = EXECUTORS.get(node.subtype)
        if executor is None:
            events.append(Event(t=ts_iso, level="error", node_id=action_id,
                                message=f"No executor for subtype '{node.subtype}'."))
            return
        try:
            result = executor(node, pf, req.costs, ctx)
        except Exception as exc:  # noqa: BLE001 - contain per-action failures
            events.append(Event(t=ts_iso, level="error", node_id=action_id,
                                message=f"Action '{action_id}' failed: {exc}"))
            return
        if result.trade is not None:
            trades.append(result.trade)
        events.extend(result.events)
        for child in runtime.action_children.get(action_id, []):
            fire_action(child, ts_iso, visited)

    funding_ptr = 0
    n_funding = len(md.funding_events)
    prev_ts = None

    for i, ts in enumerate(timeline):
        state["ts"] = ts
        ts_iso = pd.Timestamp(ts).isoformat()
        ctx.ts_iso = ts_iso

        # 1. yield accrual
        if prev_ts is not None:
            dt = (ts - prev_ts).total_seconds()
            pf.accrue_yield(dt)

        # 2. funding payments due at/through this tick
        while funding_ptr < n_funding and md.funding_events[funding_ptr][0] <= ts:
            _fts, fsym, frate = md.funding_events[funding_ptr]
            try:
                fprice = exec_price(fsym, "hyperliquid")
                apply_funding(pf, fsym, frate, fprice, ts_iso)
            except KeyError:
                pass
            funding_ptr += 1

        # 3. liquidations
        liq_events, liq_trades = check_liquidations(
            pf, price_of, req.costs.perp_maintenance_margin_frac, ts_iso
        )
        events.extend(liq_events)
        trades.extend(liq_trades)

        # 4. root actions at t0
        if i == 0:
            for aid in runtime.root_action_ids:
                fire_action(aid, ts_iso, set())

        # 5. signals (rising edge)
        for sid in runtime.signal_ids:
            node = runtime.node(sid)
            symbol = str(node.config.get("symbol", ""))
            market = str(node.config.get("market", "crypto")).lower()
            venue = "equity" if market in ("equity", "stock") else None
            try:
                price = md.signal_price(symbol, ts, venue=venue)
            except KeyError:
                continue
            current = SignalState.evaluate(node, price)
            if signal_state.rising_edge(sid, current):
                for child in runtime.signal_children.get(sid, []):
                    fire_action(child, ts_iso, set())

        # 6. record equity
        equity = pf.total_equity(price_of)
        equity_curve.append(EquityPoint(t=ts_iso, equity=equity, price=md.reference_price(ts)))
        prev_ts = ts

    metrics = compute_metrics(equity_curve, trades, req.initial_capital, req.interval)
    return BacktestResult(
        metrics=metrics,
        equity_curve=equity_curve,
        trades=trades,
        events=events,
        interval=req.interval,
        start=req.start,
        end=req.end,
    )
