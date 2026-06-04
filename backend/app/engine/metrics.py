"""Performance metrics computed from the equity curve and trade log."""
from __future__ import annotations

import math
from typing import List, Optional

from ..models import EquityPoint, Metrics, Trade

INTERVAL_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


def _max_drawdown_pct(equities: List[float]) -> float:
    peak = -math.inf
    max_dd = 0.0
    for v in equities:
        peak = max(peak, v)
        if peak > 0:
            dd = (peak - v) / peak
            max_dd = max(max_dd, dd)
    return max_dd * 100.0


def _sharpe(equities: List[float], interval: str) -> float:
    if len(equities) < 3:
        return 0.0
    returns = []
    for prev, cur in zip(equities[:-1], equities[1:]):
        if prev > 0:
            returns.append(cur / prev - 1.0)
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(var)
    if std == 0:
        return 0.0
    secs = INTERVAL_SECONDS.get(interval, 3600)
    periods_per_year = (365 * 24 * 3600) / secs
    sharpe = (mean / std) * math.sqrt(periods_per_year)
    # Near-deterministic equity (e.g. yield-only) produces a vanishing stdev and
    # an absurd ratio; clamp to a sane, interpretable range.
    return max(-100.0, min(100.0, sharpe))


def _win_rate_pct(trades: List[Trade]) -> Optional[float]:
    closing = [t for t in trades if abs(t.realized_pnl) > 1e-9]
    if not closing:
        return None
    wins = sum(1 for t in closing if t.realized_pnl > 0)
    return 100.0 * wins / len(closing)


def compute_metrics(
    equity_curve: List[EquityPoint],
    trades: List[Trade],
    initial_capital: float,
    interval: str,
) -> Metrics:
    equities = [p.equity for p in equity_curve]
    final_equity = equities[-1] if equities else initial_capital
    total_return_pct = (final_equity / initial_capital - 1.0) * 100.0 if initial_capital else 0.0
    return Metrics(
        initial_capital=initial_capital,
        final_equity=final_equity,
        total_return_pct=total_return_pct,
        max_drawdown_pct=_max_drawdown_pct(equities),
        sharpe=_sharpe(equities, interval),
        num_trades=len(trades),
        total_fees_usd=sum(t.fee_usd for t in trades),
        win_rate_pct=_win_rate_pct(trades),
    )
