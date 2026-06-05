"""Tests for US equity data providers and graph wiring."""
from __future__ import annotations

import json
import os
from unittest.mock import patch

import pandas as pd
import pytest

from app.data.equity_providers import fetch_yahoo, fetch_equity_raw
from app.engine.graph import build_runtime
from app.models import Graph

EXAMPLES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "examples")


YAHOO_FIXTURE = {
    "chart": {
        "result": [
            {
                "timestamp": [1704067200, 1704070800],
                "indicators": {
                    "quote": [
                        {
                            "open": [185.0, 186.0],
                            "high": [187.0, 188.0],
                            "low": [184.0, 185.5],
                            "close": [186.5, 187.2],
                            "volume": [1000, 1100],
                        }
                    ]
                },
            }
        ]
    }
}


@patch("app.data.equity_providers.requests.get")
def test_fetch_yahoo_parses_ohlcv(mock_get):
    mock_resp = mock_get.return_value
    mock_resp.raise_for_status = lambda: None
    mock_resp.json.return_value = YAHOO_FIXTURE

    start = 1704067200000
    end = 1704153600000
    df = fetch_yahoo("AAPL", "1h", start, end)

    assert len(df) == 2
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df["close"].iloc[0] == pytest.approx(186.5)


@patch("app.data.equity_providers.fetch_yahoo")
def test_fetch_equity_raw_uses_yahoo_first(mock_yahoo):
    mock_yahoo.return_value = pd.DataFrame(
        {"open": [1], "high": [1], "low": [1], "close": [100], "volume": [1]},
        index=pd.DatetimeIndex(["2024-01-01"], tz="UTC"),
    )
    df = fetch_equity_raw("SPY", "1d", 0, 9999999999999)
    assert not df.empty
    mock_yahoo.assert_called_once()


def test_equity_swap_data_requirements():
    g = Graph.model_validate(
        {
            "nodes": [
                {
                    "id": "buy-aapl",
                    "kind": "action",
                    "subtype": "swap",
                    "config": {"from_asset": "USDC", "to_asset": "AAPL", "amount": "1000", "chain": "equity"},
                    "enabled": True,
                }
            ],
            "edges": [],
        }
    )
    rt = build_runtime(g)
    prices, funding = rt.data_requirements()
    assert ("AAPL", "equity") in prices
    assert funding == []


def test_equity_signal_market_config():
    g = Graph.model_validate(
        {
            "nodes": [
                {
                    "id": "sig",
                    "kind": "signal",
                    "subtype": "price_threshold",
                    "config": {"symbol": "SPY", "operator": "<", "threshold": 500, "market": "equity"},
                    "enabled": True,
                },
                {
                    "id": "buy",
                    "kind": "action",
                    "subtype": "swap",
                    "config": {"from_asset": "USDC", "to_asset": "SPY", "amount": "500", "chain": "equity"},
                    "enabled": True,
                },
            ],
            "edges": [{"from": "sig", "to": "buy"}],
        }
    )
    rt = build_runtime(g)
    prices, _ = rt.data_requirements()
    assert ("SPY", "equity") in prices


def test_graph_16_example_parses():
    with open(os.path.join(EXAMPLES_DIR, "graph_16.json")) as f:
        data = json.load(f)
    build_runtime(Graph.model_validate(data["graph"]))
