"""Historical market-data providers (free public APIs) + a unified MarketData.

- EVM spot prices come from Binance klines (``ETHUSDT`` etc). USDC is treated
  as a $1 stablecoin.
- Hyperliquid spot and perp prices come from the Hyperliquid ``candleSnapshot``
  info endpoint (perp candles closely track spot for MVP purposes).
- Perp funding comes from the Hyperliquid ``fundingHistory`` endpoint (8h).

Everything is reindexed onto a single master timeline derived from the
requested ``[start, end]`` range and ``interval`` so the simulator can iterate
one candle = one tick.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests

from . import cache

# The primary Binance API geo-blocks some regions (HTTP 451). The public data
# mirror and the US endpoint are used as fallbacks.
BINANCE_BASES = [
    "https://data-api.binance.vision",
    "https://api.binance.us",
    "https://api.binance.com",
]
HYPERLIQUID_URL = "https://api.hyperliquid.xyz/info"

INTERVAL_MS = {
    "1m": 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "30m": 30 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}

EVM_CHAINS = {"base", "ethereum", "eth", "arbitrum", "optimism", "polygon", "evm"}


def to_ms(iso: str) -> int:
    """Parse an ISO date or datetime string into a UTC epoch in milliseconds."""
    s = iso.strip()
    if len(s) == 10:  # date only
        s = s + "T00:00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _empty_ohlcv() -> pd.DataFrame:
    return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


class BinanceProvider:
    """Fetches spot OHLCV from Binance (max 1000 candles/request, paginated)."""

    def fetch(self, symbol: str, interval: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        pair = f"{symbol.upper()}USDT"
        key = f"binance_{pair}_{interval}_{start_ms}_{end_ms}"
        cached = cache.load(key)
        if cached is not None:
            return cached

        step = INTERVAL_MS[interval]
        base = self._pick_base(pair, interval)
        rows: List[list] = []
        cursor = start_ms
        while cursor < end_ms:
            params = {
                "symbol": pair,
                "interval": interval,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": 1000,
            }
            resp = requests.get(f"{base}/api/v3/klines", params=params, timeout=30)
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            rows.extend(batch)
            last_open = batch[-1][0]
            cursor = last_open + step
            if len(batch) < 1000:
                break
            time.sleep(0.05)

        df = self._to_frame(rows)
        cache.store(key, df)
        return df

    @staticmethod
    def _pick_base(pair: str, interval: str) -> str:
        """Return the first reachable Binance base URL for this symbol."""
        last_err: Optional[Exception] = None
        for base in BINANCE_BASES:
            try:
                resp = requests.get(
                    f"{base}/api/v3/klines",
                    params={"symbol": pair, "interval": interval, "limit": 1},
                    timeout=15,
                )
                if resp.status_code == 200:
                    return base
            except Exception as exc:  # noqa: BLE001
                last_err = exc
        if last_err is not None:
            raise last_err
        return BINANCE_BASES[0]

    @staticmethod
    def _to_frame(rows: List[list]) -> pd.DataFrame:
        if not rows:
            return _empty_ohlcv()
        df = pd.DataFrame(
            [
                {
                    "open_time": int(r[0]),
                    "open": float(r[1]),
                    "high": float(r[2]),
                    "low": float(r[3]),
                    "close": float(r[4]),
                    "volume": float(r[5]),
                }
                for r in rows
            ]
        )
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df = df.drop_duplicates(subset="open_time").set_index("open_time").sort_index()
        return df[["open", "high", "low", "close", "volume"]]


class HyperliquidProvider:
    """Fetches perp/spot candles and funding from the Hyperliquid info API."""

    def fetch_candles(self, coin: str, interval: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        key = f"hl_{coin.upper()}_{interval}_{start_ms}_{end_ms}"
        cached = cache.load(key)
        if cached is not None:
            return cached

        step = INTERVAL_MS[interval]
        # Stay under the 5000-candle cap per request.
        window = step * 4800
        rows: List[dict] = []
        cursor = start_ms
        while cursor < end_ms:
            req_end = min(cursor + window, end_ms)
            body = {
                "type": "candleSnapshot",
                "req": {
                    "coin": coin.upper(),
                    "interval": interval,
                    "startTime": cursor,
                    "endTime": req_end,
                },
            }
            resp = requests.post(HYPERLIQUID_URL, json=body, timeout=30)
            resp.raise_for_status()
            batch = resp.json() or []
            if not batch:
                cursor = req_end + step
                continue
            rows.extend(batch)
            last_open = int(batch[-1]["t"])
            cursor = max(last_open + step, req_end + step)
            time.sleep(0.05)

        df = self._candles_to_frame(rows)
        cache.store(key, df)
        return df

    def fetch_funding(self, coin: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        key = f"hlfund_{coin.upper()}_{start_ms}_{end_ms}"
        cached = cache.load(key)
        if cached is not None:
            return cached

        rows: List[dict] = []
        cursor = start_ms
        # fundingHistory returns chronological pages; advance by last time.
        for _ in range(200):  # hard cap on pages
            body = {"type": "fundingHistory", "coin": coin.upper(), "startTime": cursor, "endTime": end_ms}
            resp = requests.post(HYPERLIQUID_URL, json=body, timeout=30)
            resp.raise_for_status()
            batch = resp.json() or []
            if not batch:
                break
            rows.extend(batch)
            last_time = int(batch[-1]["time"])
            if last_time <= cursor or last_time >= end_ms:
                break
            cursor = last_time + 1
            time.sleep(0.05)

        df = self._funding_to_frame(rows)
        cache.store(key, df)
        return df

    @staticmethod
    def _candles_to_frame(rows: List[dict]) -> pd.DataFrame:
        if not rows:
            return _empty_ohlcv()
        df = pd.DataFrame(
            [
                {
                    "open_time": int(r["t"]),
                    "open": float(r["o"]),
                    "high": float(r["h"]),
                    "low": float(r["l"]),
                    "close": float(r["c"]),
                    "volume": float(r["v"]),
                }
                for r in rows
            ]
        )
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df = df.drop_duplicates(subset="open_time").set_index("open_time").sort_index()
        return df[["open", "high", "low", "close", "volume"]]

    @staticmethod
    def _funding_to_frame(rows: List[dict]) -> pd.DataFrame:
        if not rows:
            return pd.DataFrame(columns=["funding_rate"])
        df = pd.DataFrame(
            [{"time": int(r["time"]), "funding_rate": float(r["fundingRate"])} for r in rows]
        )
        df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
        df = df.drop_duplicates(subset="time").set_index("time").sort_index()
        return df[["funding_rate"]]


@dataclass
class MarketData:
    """Unified, tick-aligned market data for a single backtest run."""

    timeline: pd.DatetimeIndex
    interval: str
    _price_frame: pd.DataFrame  # columns "SYMBOL@venue" -> close price
    funding_events: List[Tuple[pd.Timestamp, str, float]] = field(default_factory=list)

    @staticmethod
    def _venue_for_chain(chain: str) -> str:
        return "hyperliquid" if chain.lower() == "hyperliquid" else "evm"

    @staticmethod
    def _col(symbol: str, venue: str) -> str:
        return f"{symbol.upper()}@{venue}"

    @classmethod
    def build(
        cls,
        requirements: List[Tuple[str, str]],  # (symbol, venue) where venue in {evm, hyperliquid}
        funding_symbols: List[str],
        interval: str,
        start: str,
        end: str,
    ) -> "MarketData":
        if interval not in INTERVAL_MS:
            raise ValueError(f"Unsupported interval '{interval}'. Use one of {list(INTERVAL_MS)}")
        start_ms, end_ms = to_ms(start), to_ms(end)
        if end_ms <= start_ms:
            raise ValueError("`end` must be after `start`.")

        binance = BinanceProvider()
        hl = HyperliquidProvider()

        # De-duplicate requirements.
        reqs = sorted(set((s.upper(), v) for s, v in requirements))

        series: Dict[str, pd.Series] = {}
        master: Optional[pd.DatetimeIndex] = None
        for symbol, venue in reqs:
            if venue == "hyperliquid":
                frame = hl.fetch_candles(symbol, interval, start_ms, end_ms)
            else:
                frame = binance.fetch(symbol, interval, start_ms, end_ms)
            if frame.empty:
                continue
            close = frame["close"]
            series[cls._col(symbol, venue)] = close
            master = close.index if master is None else master.union(close.index)

        if master is None or len(master) == 0:
            if not reqs:
                # Pure time-based strategy (e.g. yield-only, no price/signal
                # nodes): synthesize a tick timeline from the requested range.
                step = pd.Timedelta(milliseconds=INTERVAL_MS[interval])
                master = pd.date_range(
                    start=pd.Timestamp(start_ms, unit="ms", tz="UTC"),
                    end=pd.Timestamp(end_ms, unit="ms", tz="UTC"),
                    freq=step,
                )
            else:
                raise RuntimeError(
                    "No market data returned for the requested range. "
                    "Check the symbols, chains, and date range."
                )

        master = master[(master >= pd.Timestamp(start_ms, unit="ms", tz="UTC"))
                        & (master <= pd.Timestamp(end_ms, unit="ms", tz="UTC"))]
        price_frame = pd.DataFrame(index=master)
        for col, s in series.items():
            price_frame[col] = s.reindex(master).ffill().bfill()

        # Funding events (8h) for any perp symbols.
        funding_events: List[Tuple[pd.Timestamp, str, float]] = []
        for symbol in sorted(set(s.upper() for s in funding_symbols)):
            fdf = hl.fetch_funding(symbol, start_ms, end_ms)
            for ts, row in fdf.iterrows():
                funding_events.append((ts, symbol, float(row["funding_rate"])))
        funding_events.sort(key=lambda x: x[0])

        return cls(timeline=master, interval=interval, _price_frame=price_frame, funding_events=funding_events)

    # -- accessors -------------------------------------------------------
    def price(self, symbol: str, chain: str, ts: pd.Timestamp) -> float:
        venue = self._venue_for_chain(chain)
        col = self._col(symbol, venue)
        if col not in self._price_frame.columns:
            # Fall back to the EVM (Binance) price if the venue-specific series
            # is unavailable.
            col = self._col(symbol, "evm")
        if col not in self._price_frame.columns:
            raise KeyError(f"No price series for {symbol} on {chain}")
        return float(self._price_frame.at[ts, col])

    def signal_price(self, symbol: str, ts: pd.Timestamp) -> float:
        """Canonical price used to evaluate signals (prefers EVM/Binance)."""
        for venue in ("evm", "hyperliquid"):
            col = self._col(symbol, venue)
            if col in self._price_frame.columns:
                return float(self._price_frame.at[ts, col])
        raise KeyError(f"No price series to evaluate signal for {symbol}")

    def reference_price(self, ts: pd.Timestamp) -> Optional[float]:
        if self._price_frame.shape[1] == 0:
            return None
        return float(self._price_frame.iloc[:, 0].loc[ts])
