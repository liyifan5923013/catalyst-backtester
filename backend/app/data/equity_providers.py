"""Free-tier US equity OHLCV providers.

Primary: **Yahoo Finance** chart API (no API key; unofficial but widely used).
Fallback: **Alpha Vantage** when ``ALPHA_VANTAGE_API_KEY`` is set (free tier:
25 requests/day on the standard plan — suitable for demos, not heavy backfills).

Supported intervals match the backtester: ``15m``, ``1h``, ``4h``, ``1d``.
``4h`` bars are resampled from hourly data when the upstream only offers 60m.
"""
from __future__ import annotations

import os
import time
from typing import List, Optional

import pandas as pd
import requests

from . import cache

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"

# Map backtest interval -> Yahoo interval string.
YAHOO_INTERVAL = {
    "15m": "15m",
    "1h": "60m",
    "4h": "60m",  # resampled below
    "1d": "1d",
}

# User-Agent avoids occasional 403s from Yahoo's edge.
_YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CatalystBacktester/1.0)",
}

EQUITY_CHAINS = frozenset({"equity", "stock", "us_equity", "nasdaq", "nyse"})


def _empty_ohlcv() -> pd.DataFrame:
    return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


def _persistence_enabled() -> bool:
    try:
        from . import db

        return db.is_enabled()
    except Exception:  # noqa: BLE001
        return False


def _ms_to_dt(ms: int):
    from datetime import datetime, timezone

    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


def _resample_4h(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.resample("4h").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    return out.dropna(subset=["close"])


def _clip_range(df: pd.DataFrame, start_ms: int, end_ms: int) -> pd.DataFrame:
    if df.empty:
        return df
    start = pd.Timestamp(start_ms, unit="ms", tz="UTC")
    end = pd.Timestamp(end_ms, unit="ms", tz="UTC")
    return df.loc[(df.index >= start) & (df.index <= end)]


def fetch_yahoo(symbol: str, interval: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """Fetch OHLCV from Yahoo Finance chart API."""
    if interval not in YAHOO_INTERVAL:
        raise ValueError(f"Unsupported interval '{interval}' for equity data.")
    yint = YAHOO_INTERVAL[interval]
    url = YAHOO_CHART_URL.format(symbol=symbol.upper())
    params = {
        "interval": yint,
        "period1": start_ms // 1000,
        "period2": end_ms // 1000,
        "includePrePost": "false",
    }
    resp = requests.get(url, params=params, headers=_YAHOO_HEADERS, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    results = payload.get("chart", {}).get("result") or []
    if not results:
        return _empty_ohlcv()

    block = results[0]
    timestamps: List[int] = block.get("timestamp") or []
    quote = (block.get("indicators") or {}).get("quote", [{}])[0]
    if not timestamps:
        return _empty_ohlcv()

    rows = []
    for i, ts in enumerate(timestamps):
        o = quote.get("open", [None] * len(timestamps))[i]
        h = quote.get("high", [None] * len(timestamps))[i]
        lo = quote.get("low", [None] * len(timestamps))[i]
        c = quote.get("close", [None] * len(timestamps))[i]
        v = quote.get("volume", [None] * len(timestamps))[i]
        if c is None:
            continue
        rows.append(
            {
                "open_time": pd.Timestamp(ts, unit="s", tz="UTC"),
                "open": float(o if o is not None else c),
                "high": float(h if h is not None else c),
                "low": float(lo if lo is not None else c),
                "close": float(c),
                "volume": float(v or 0),
            }
        )
    if not rows:
        return _empty_ohlcv()

    df = pd.DataFrame(rows).set_index("open_time").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    if interval == "4h":
        df = _resample_4h(df)
    return _clip_range(df[["open", "high", "low", "close", "volume"]], start_ms, end_ms)


def fetch_alphavantage(symbol: str, interval: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """Fetch OHLCV from Alpha Vantage (requires ``ALPHA_VANTAGE_API_KEY``)."""
    api_key = os.environ.get("ALPHA_VANTAGE_API_KEY", "").strip()
    if not api_key:
        return _empty_ohlcv()

    sym = symbol.upper()
    if interval == "1d":
        params = {
            "function": "TIME_SERIES_DAILY",
            "symbol": sym,
            "outputsize": "full",
            "apikey": api_key,
        }
        time.sleep(0.25)  # gentle rate limit for free tier
        resp = requests.get(ALPHA_VANTAGE_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        series = data.get("Time Series (Daily)", {})
        rows = []
        for day, bar in series.items():
            ts = pd.Timestamp(day, tz="UTC")
            rows.append(
                {
                    "open_time": ts,
                    "open": float(bar["1. open"]),
                    "high": float(bar["2. high"]),
                    "low": float(bar["3. low"]),
                    "close": float(bar["4. close"]),
                    "volume": float(bar["5. volume"]),
                }
            )
    else:
        av_interval = "15min" if interval == "15m" else "60min"
        params = {
            "function": "TIME_SERIES_INTRADAY",
            "symbol": sym,
            "interval": av_interval,
            "outputsize": "full",
            "apikey": api_key,
        }
        time.sleep(0.25)
        resp = requests.get(ALPHA_VANTAGE_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        key = f"Time Series ({av_interval})"
        series = data.get(key, {})
        if not series and "Note" in data:
            # Rate-limit message from Alpha Vantage.
            return _empty_ohlcv()
        rows = []
        for stamp, bar in series.items():
            ts = pd.Timestamp(stamp, tz="UTC")
            rows.append(
                {
                    "open_time": ts,
                    "open": float(bar["1. open"]),
                    "high": float(bar["2. high"]),
                    "low": float(bar["3. low"]),
                    "close": float(bar["4. close"]),
                    "volume": float(bar["5. volume"]),
                }
            )

    if not rows:
        return _empty_ohlcv()

    df = pd.DataFrame(rows).set_index("open_time").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    if interval == "4h":
        df = _resample_4h(df)
    return _clip_range(df[["open", "high", "low", "close", "volume"]], start_ms, end_ms)


def fetch_equity_raw(symbol: str, interval: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """Yahoo first; Alpha Vantage if Yahoo returns empty and a key is configured."""
    df = fetch_yahoo(symbol, interval, start_ms, end_ms)
    if not df.empty:
        return df
    if os.environ.get("ALPHA_VANTAGE_API_KEY", "").strip():
        return fetch_alphavantage(symbol, interval, start_ms, end_ms)
    return _empty_ohlcv()


class EquityProvider:
    """US equity OHLCV via Yahoo Finance (free) with optional Alpha Vantage fallback."""

    def fetch(self, symbol: str, interval: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        from .providers import INTERVAL_MS

        if interval not in INTERVAL_MS:
            raise ValueError(f"Unsupported interval '{interval}'.")

        if _persistence_enabled():
            from .repository import MarketRepository

            return MarketRepository().get_candles(
                source="yahoo",
                symbol=symbol.upper(),
                interval=interval,
                start=_ms_to_dt(start_ms),
                end=_ms_to_dt(end_ms),
                fetcher=fetch_equity_raw,
                interval_ms=INTERVAL_MS[interval],
            )

        key = f"yahoo_{symbol.upper()}_{interval}_{start_ms}_{end_ms}"
        cached = cache.load(key)
        if cached is not None:
            return cached
        df = fetch_equity_raw(symbol, interval, start_ms, end_ms)
        cache.store(key, df)
        return df

