"""Tests for the scheduled pre-warm watchlist + run loop (offline)."""
from __future__ import annotations

import pandas as pd

from app.data import prewarm


def test_default_watchlist_used_when_env_unset(monkeypatch):
    monkeypatch.delenv("PREWARM_WATCHLIST", raising=False)
    assert prewarm.load_watchlist() == prewarm.DEFAULT_WATCHLIST


def test_load_watchlist_parses_env(monkeypatch):
    monkeypatch.setenv(
        "PREWARM_WATCHLIST",
        '[{"source":"binance","symbol":"SOL","interval":"4h"},'
        ' {"source":"hyperliquid","symbol":"BTC","funding":true}]',
    )
    entries = prewarm.load_watchlist()
    assert entries == [
        prewarm.WatchEntry(source="binance", symbol="SOL", interval="4h"),
        prewarm.WatchEntry(source="hyperliquid", symbol="BTC", funding=True),
    ]


def test_load_watchlist_falls_back_on_bad_json(monkeypatch):
    monkeypatch.setenv("PREWARM_WATCHLIST", "{not json")
    assert prewarm.load_watchlist() == prewarm.DEFAULT_WATCHLIST


def test_load_watchlist_skips_malformed_entries(monkeypatch):
    monkeypatch.setenv(
        "PREWARM_WATCHLIST",
        '[{"symbol":"NOSRC"}, {"source":"binance","symbol":"ETH"}]',
    )
    entries = prewarm.load_watchlist()
    assert entries == [prewarm.WatchEntry(source="binance", symbol="ETH")]


def test_run_prewarm_noop_without_database(monkeypatch):
    monkeypatch.setattr(prewarm.db, "is_enabled", lambda: False)
    assert prewarm.run_prewarm() == 0


def test_run_prewarm_invokes_fetcher_per_entry(monkeypatch):
    monkeypatch.setattr(prewarm.db, "is_enabled", lambda: True)
    monkeypatch.setenv(
        "PREWARM_WATCHLIST",
        '[{"source":"binance","symbol":"ETH","interval":"1h"},'
        ' {"source":"yahoo","symbol":"AAPL","interval":"1h"}]',
    )

    calls = []

    def _fake(entry, start_ms, end_ms):
        calls.append((entry.source, entry.symbol, start_ms, end_ms))
        assert end_ms > start_ms
        return 42

    monkeypatch.setattr(prewarm, "_fetch_entry", _fake)

    succeeded = prewarm.run_prewarm(trailing_days=30)
    assert succeeded == 2
    assert [c[:2] for c in calls] == [("binance", "ETH"), ("yahoo", "AAPL")]


def test_run_prewarm_isolates_failures(monkeypatch):
    monkeypatch.setattr(prewarm.db, "is_enabled", lambda: True)
    monkeypatch.setenv(
        "PREWARM_WATCHLIST",
        '[{"source":"binance","symbol":"BOOM"},'
        ' {"source":"binance","symbol":"ETH"}]',
    )

    def _fake(entry, start_ms, end_ms):
        if entry.symbol == "BOOM":
            raise RuntimeError("provider down")
        return 1

    monkeypatch.setattr(prewarm, "_fetch_entry", _fake)
    # One entry fails, the other still completes.
    assert prewarm.run_prewarm() == 1


def test_fetch_entry_routes_to_provider(monkeypatch):
    captured = {}

    class _FakeBinance:
        def fetch(self, symbol, interval, start_ms, end_ms):
            captured["binance"] = (symbol, interval)
            return pd.DataFrame({"close": [1.0, 2.0]})

    monkeypatch.setattr(prewarm, "BinanceProvider", _FakeBinance)
    rows = prewarm._fetch_entry(
        prewarm.WatchEntry(source="binance", symbol="ETH", interval="1h"), 0, 1000
    )
    assert rows == 2
    assert captured["binance"] == ("ETH", "1h")
