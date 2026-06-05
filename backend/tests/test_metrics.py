"""Accuracy tests for performance-metric computation (hand-computed values)."""
from __future__ import annotations

import pytest

from app.engine.metrics import compute_metrics
from app.models import EquityPoint, Trade


def eq(values):
    return [EquityPoint(t=f"2024-01-01T{i:02d}:00:00+00:00", equity=v) for i, v in enumerate(values)]


def trade(realized=0.0, fee=0.0):
    return Trade(t="t", node_id="n", kind="swap", chain="base", symbol="ETH",
                 side="sell", qty=1.0, price=1.0, usd_value=1.0, fee_usd=fee, realized_pnl=realized)


def test_total_return_pct():
    m = compute_metrics(eq([10_000, 10_250, 10_500]), [], 10_000, "1h")
    assert m.final_equity == pytest.approx(10_500)
    assert m.total_return_pct == pytest.approx(5.0)


def test_negative_return():
    m = compute_metrics(eq([10_000, 9_500]), [], 10_000, "1h")
    assert m.total_return_pct == pytest.approx(-5.0)


def test_max_drawdown_pct():
    # peak 120, trough 90 -> (120-90)/120 = 25%.
    m = compute_metrics(eq([100, 120, 90, 110]), [], 100, "1h")
    assert m.max_drawdown_pct == pytest.approx(25.0)


def test_no_drawdown_when_monotonic_up():
    m = compute_metrics(eq([100, 110, 130]), [], 100, "1h")
    assert m.max_drawdown_pct == pytest.approx(0.0)


def test_win_rate_counts_only_closing_trades():
    trades = [trade(realized=5.0), trade(realized=-3.0), trade(realized=2.0), trade(realized=0.0)]
    m = compute_metrics(eq([100, 100]), trades, 100, "1h")
    # closing = 3 (the zero-pnl trade is excluded); wins = 2 -> 66.67%.
    assert m.win_rate_pct == pytest.approx(200.0 / 3.0)


def test_win_rate_none_without_closing_trades():
    m = compute_metrics(eq([100, 100]), [trade(realized=0.0)], 100, "1h")
    assert m.win_rate_pct is None


def test_total_fees_sums_trade_fees():
    m = compute_metrics(eq([100, 100]), [trade(fee=1.25), trade(fee=0.75)], 100, "1h")
    assert m.total_fees_usd == pytest.approx(2.0)
    assert m.num_trades == 2


def test_sharpe_zero_for_flat_equity():
    # No variance -> undefined ratio -> clamped to 0.
    m = compute_metrics(eq([100, 100, 100, 100]), [], 100, "1h")
    assert m.sharpe == pytest.approx(0.0)


def test_sharpe_positive_for_uptrend_negative_for_downtrend():
    up = compute_metrics(eq([100, 102, 101, 104, 103, 106]), [], 100, "1h")
    down = compute_metrics(eq([100, 98, 99, 96, 97, 94]), [], 100, "1h")
    assert up.sharpe > 0
    assert down.sharpe < 0
    # Clamp keeps it interpretable.
    assert -100.0 <= up.sharpe <= 100.0
    assert -100.0 <= down.sharpe <= 100.0


def test_sharpe_matches_hand_computation():
    # equities [100,110,105]: returns r1=0.1, r2=-5/110=-0.0454545...
    # mean=0.0272727..., sample std (n-1=1): |r-mean| each = 0.0727272...,
    # var = 2*0.0727272^2 / 1, std = sqrt(var); annualized by sqrt(8760).
    import math
    r1 = 0.1
    r2 = -5.0 / 110.0
    mean = (r1 + r2) / 2.0
    var = ((r1 - mean) ** 2 + (r2 - mean) ** 2) / 1.0
    std = math.sqrt(var)
    expected = (mean / std) * math.sqrt(365 * 24 * 3600 / 3600)
    m = compute_metrics(eq([100, 110, 105]), [], 100, "1h")
    assert m.sharpe == pytest.approx(expected, rel=1e-9)
