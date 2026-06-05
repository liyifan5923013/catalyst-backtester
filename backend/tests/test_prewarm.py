"""Tests for the scheduled pre-warm watchlist + run loop (offline)."""
from __future__ import annotations

import threading

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import main as app_main
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


def test_interval_defaults_to_24h(monkeypatch):
    monkeypatch.delenv("PREWARM_INTERVAL_MINUTES", raising=False)
    monkeypatch.delenv("PREWARM_INTERVAL_HOURS", raising=False)
    assert app_main._prewarm_interval_seconds() == 24 * 3600.0


def test_interval_hours_env(monkeypatch):
    monkeypatch.delenv("PREWARM_INTERVAL_MINUTES", raising=False)
    monkeypatch.setenv("PREWARM_INTERVAL_HOURS", "2")
    assert app_main._prewarm_interval_seconds() == 2 * 3600.0


def test_interval_minutes_takes_precedence(monkeypatch):
    monkeypatch.setenv("PREWARM_INTERVAL_HOURS", "24")
    monkeypatch.setenv("PREWARM_INTERVAL_MINUTES", "5")
    assert app_main._prewarm_interval_seconds() == 5 * 60.0


def test_interval_floored_at_minimum(monkeypatch):
    monkeypatch.setenv("PREWARM_INTERVAL_MINUTES", "0.1")  # 6s -> floored
    assert app_main._prewarm_interval_seconds() == app_main.PREWARM_MIN_INTERVAL_SECONDS


def test_interval_invalid_values_fall_back(monkeypatch):
    monkeypatch.setenv("PREWARM_INTERVAL_MINUTES", "abc")
    monkeypatch.setenv("PREWARM_INTERVAL_HOURS", "xyz")
    assert app_main._prewarm_interval_seconds() == 24 * 3600.0


def test_lifespan_starts_loop_when_enabled(monkeypatch):
    """With PREWARM_ENABLED=1 and a DB, the app fires the warmer on startup."""
    called = threading.Event()

    monkeypatch.setenv("PREWARM_ENABLED", "1")
    monkeypatch.setattr(app_main.db, "is_enabled", lambda: True)

    def _fake_run(trailing_days):
        called.set()
        return 0

    # The loop imports run_prewarm from app.data.prewarm at runtime.
    monkeypatch.setattr(prewarm, "run_prewarm", _fake_run)

    with TestClient(app_main.app):
        assert called.wait(timeout=5.0), "prewarm loop did not run on startup"


def test_lifespan_skips_loop_when_disabled(monkeypatch):
    """Default (PREWARM_ENABLED unset) must not start the loop."""
    called = threading.Event()

    monkeypatch.delenv("PREWARM_ENABLED", raising=False)
    monkeypatch.setattr(app_main.db, "is_enabled", lambda: True)
    monkeypatch.setattr(prewarm, "run_prewarm", lambda trailing_days: called.set())

    with TestClient(app_main.app):
        assert not called.wait(timeout=1.0), "loop ran despite being disabled"


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


def test_fetch_entry_routes_hyperliquid_candles_and_funding(monkeypatch):
    captured = {}

    class _FakeHL:
        def fetch_candles(self, coin, interval, start_ms, end_ms):
            captured["candles"] = (coin, interval)
            return pd.DataFrame({"close": [1.0]})

        def fetch_funding(self, coin, start_ms, end_ms):
            captured["funding"] = coin
            return pd.DataFrame({"funding": [0.0, 0.0, 0.0]})

    monkeypatch.setattr(prewarm, "HyperliquidProvider", _FakeHL)

    assert (
        prewarm._fetch_entry(
            prewarm.WatchEntry(source="hyperliquid", symbol="ETH", interval="1h"), 0, 1
        )
        == 1
    )
    assert captured["candles"] == ("ETH", "1h")

    assert (
        prewarm._fetch_entry(
            prewarm.WatchEntry(source="hyperliquid", symbol="ETH", funding=True), 0, 1
        )
        == 3
    )
    assert captured["funding"] == "ETH"


def test_fetch_entry_routes_yahoo(monkeypatch):
    captured = {}

    class _FakeEquity:
        def fetch(self, symbol, interval, start_ms, end_ms):
            captured["yahoo"] = (symbol, interval)
            return pd.DataFrame({"close": [1.0, 2.0, 3.0, 4.0]})

    monkeypatch.setattr(prewarm, "EquityProvider", _FakeEquity)
    rows = prewarm._fetch_entry(
        prewarm.WatchEntry(source="yahoo", symbol="AAPL", interval="1h"), 0, 1
    )
    assert rows == 4
    assert captured["yahoo"] == ("AAPL", "1h")


def test_fetch_entry_unknown_source_raises():
    with pytest.raises(ValueError):
        prewarm._fetch_entry(prewarm.WatchEntry(source="bogus", symbol="X"), 0, 1)


def test_run_prewarm_skips_unknown_interval(monkeypatch):
    monkeypatch.setattr(prewarm.db, "is_enabled", lambda: True)
    monkeypatch.setenv(
        "PREWARM_WATCHLIST",
        '[{"source":"binance","symbol":"ETH","interval":"7y"},'
        ' {"source":"binance","symbol":"BTC","interval":"1h"}]',
    )
    seen = []
    monkeypatch.setattr(prewarm, "_fetch_entry", lambda e, s, x: seen.append(e.symbol) or 1)
    # The unknown-interval entry is skipped before any fetch.
    assert prewarm.run_prewarm() == 1
    assert seen == ["BTC"]


def test_run_prewarm_window_reflects_trailing_days(monkeypatch):
    monkeypatch.setattr(prewarm.db, "is_enabled", lambda: True)
    monkeypatch.setenv("PREWARM_WATCHLIST", '[{"source":"binance","symbol":"ETH"}]')
    windows = []
    monkeypatch.setattr(
        prewarm, "_fetch_entry", lambda e, s, x: windows.append((s, x)) or 1
    )
    prewarm.run_prewarm(trailing_days=10)
    start_ms, end_ms = windows[0]
    span_days = (end_ms - start_ms) / 86_400_000.0
    assert 9.9 <= span_days <= 10.1
