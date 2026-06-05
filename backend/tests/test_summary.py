"""Tests for the AI summary endpoint logic (rule-based fallback path)."""
from __future__ import annotations

import os

import pytest

from app.models import Metrics, SummaryRequest
from app.summary import generate_summary


def _metrics(**kw) -> Metrics:
    base = dict(
        initial_capital=10000.0,
        final_equity=10500.0,
        total_return_pct=5.0,
        max_drawdown_pct=4.0,
        sharpe=1.5,
        num_trades=8,
        total_fees_usd=12.0,
        win_rate_pct=60.0,
    )
    base.update(kw)
    return Metrics(**base)


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    # Force the deterministic path regardless of the developer's environment.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def test_rule_based_summary_basic():
    req = SummaryRequest(metrics=_metrics(), start="2024-01-01", end="2024-02-01", interval="1h")
    res = generate_summary(req)
    assert res.source == "rule"
    assert "+5.00%" in res.summary
    assert len(res.recommendations) >= 1


def test_rule_based_summary_with_comparison_mentions_trend():
    req = SummaryRequest(
        metrics=_metrics(total_return_pct=5.0),
        comparison_metrics=_metrics(total_return_pct=8.0),
        comparison_label="previous period",
        start="2024-02-01",
        end="2024-03-01",
        interval="1h",
    )
    res = generate_summary(req)
    assert res.source == "rule"
    # Return fell from 8% to 5% -> should be described as decreased.
    assert "decreased" in res.summary
    assert "previous period" in res.summary


def test_rule_based_flags_high_drawdown():
    req = SummaryRequest(
        metrics=_metrics(max_drawdown_pct=35.0, sharpe=0.4),
        start="2024-01-01",
        end="2024-02-01",
        interval="1h",
    )
    res = generate_summary(req)
    joined = " ".join(res.recommendations).lower()
    assert "drawdown" in joined
