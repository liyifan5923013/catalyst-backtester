"""Optional scheduled pre-warm of the persistence layer.

Pre-warming is never *required*: the read-through repository
(:mod:`app.data.repository`) fetches any missing time gaps on demand during a
backtest and persists them. This module just keeps a watchlist of common
symbols warm so the first user-facing run for them is instant instead of paying
provider latency.

It deliberately reuses the exact same provider ``fetch`` calls as the manual
CLI (:mod:`app.data.backfill`), which route through ``MarketRepository`` when
``DATABASE_URL`` is set. Because gap-fill is idempotent (coverage segments
dedupe), running this on multiple instances is safe; it just refetches the
live tail.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List

from . import db
from .providers import INTERVAL_MS, BinanceProvider, EquityProvider, HyperliquidProvider

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class WatchEntry:
    """One symbol/interval to keep warm."""

    source: str  # binance | hyperliquid | yahoo
    symbol: str
    interval: str = "1h"
    funding: bool = False  # hyperliquid funding history instead of candles


# Default watchlist derived from the bundled example graphs (ETH/BTC spot on
# Binance, ETH perp + funding on Hyperliquid, AAPL/SPY equities).
DEFAULT_WATCHLIST: List[WatchEntry] = [
    WatchEntry(source="binance", symbol="ETH", interval="1h"),
    WatchEntry(source="binance", symbol="BTC", interval="1h"),
    WatchEntry(source="hyperliquid", symbol="ETH", interval="1h"),
    WatchEntry(source="hyperliquid", symbol="ETH", funding=True),
    WatchEntry(source="yahoo", symbol="AAPL", interval="1h"),
    WatchEntry(source="yahoo", symbol="SPY", interval="1h"),
]


# Minimum seconds between warming the *same* entry, keyed by source. This caps
# how often we touch rate-limited providers regardless of the loop cadence:
# Yahoo can fail over to Alpha Vantage, whose free tier is ~25 requests/day, so
# we warm equities at most every 6h (2 symbols x 4/day = 8/day worst case).
# Crypto providers are generous, so they default to 0 (governed by the loop).
DEFAULT_SOURCE_MIN_INTERVAL_SECONDS: Dict[str, float] = {
    "yahoo": 6 * 3600.0,
}
_DEFAULT_MIN_INTERVAL = 0.0

# In-process record of the last warm attempt per entry. Resets on restart,
# which is fine: a restart just allows one extra (bounded) warm per entry.
_LAST_RUN: Dict[WatchEntry, datetime] = {}


def _source_min_intervals() -> Dict[str, float]:
    """Per-source minimum intervals, overridable via ``PREWARM_SOURCE_MIN_INTERVAL``.

    The env var, when set, is a JSON object of ``{"source": seconds}`` that is
    merged over the defaults, e.g. ``{"yahoo": 3600, "binance": 0}``.
    """
    merged = dict(DEFAULT_SOURCE_MIN_INTERVAL_SECONDS)
    raw = os.environ.get("PREWARM_SOURCE_MIN_INTERVAL")
    if raw and raw.strip():
        try:
            for source, seconds in json.loads(raw).items():
                merged[str(source).lower()] = float(seconds)
        except (json.JSONDecodeError, TypeError, ValueError):
            log.warning("PREWARM_SOURCE_MIN_INTERVAL is invalid; using defaults")
    return merged


def _is_due(entry: WatchEntry, now: datetime, min_intervals: Dict[str, float]) -> bool:
    """True if ``entry`` has not been warmed within its source's min interval."""
    min_interval = min_intervals.get(entry.source, _DEFAULT_MIN_INTERVAL)
    if min_interval <= 0:
        return True
    last = _LAST_RUN.get(entry)
    if last is None:
        return True
    return (now - last).total_seconds() >= min_interval


def load_watchlist() -> List[WatchEntry]:
    """Return the watchlist, overridable via the ``PREWARM_WATCHLIST`` env var.

    The env var, when set, is a JSON array of objects, e.g.::

        [{"source": "binance", "symbol": "SOL", "interval": "1h"},
         {"source": "hyperliquid", "symbol": "BTC", "funding": true}]
    """
    raw = os.environ.get("PREWARM_WATCHLIST")
    if not raw or not raw.strip():
        return list(DEFAULT_WATCHLIST)
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("PREWARM_WATCHLIST is not valid JSON; using default watchlist")
        return list(DEFAULT_WATCHLIST)
    entries: List[WatchEntry] = []
    for item in items:
        try:
            entries.append(
                WatchEntry(
                    source=str(item["source"]).lower(),
                    symbol=str(item["symbol"]),
                    interval=str(item.get("interval", "1h")),
                    funding=bool(item.get("funding", False)),
                )
            )
        except (KeyError, TypeError) as exc:
            log.warning("skipping malformed PREWARM_WATCHLIST entry %r: %s", item, exc)
    return entries or list(DEFAULT_WATCHLIST)


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _fetch_entry(entry: WatchEntry, start_ms: int, end_ms: int) -> int:
    """Fetch one watchlist entry through the read-through repository.

    Returns the number of rows now in the store for the window.
    """
    if entry.funding:
        df = HyperliquidProvider().fetch_funding(entry.symbol, start_ms, end_ms)
    elif entry.source == "binance":
        df = BinanceProvider().fetch(entry.symbol, entry.interval, start_ms, end_ms)
    elif entry.source == "hyperliquid":
        df = HyperliquidProvider().fetch_candles(entry.symbol, entry.interval, start_ms, end_ms)
    elif entry.source == "yahoo":
        df = EquityProvider().fetch(entry.symbol, entry.interval, start_ms, end_ms)
    else:
        raise ValueError(f"unknown prewarm source: {entry.source!r}")
    return len(df)


def run_prewarm(trailing_days: int = 365) -> int:
    """Warm every watchlist entry over a trailing window ending now.

    Each entry is isolated: a failure is logged and the loop continues. Returns
    the count of entries that completed without raising.
    """
    if not db.is_enabled():
        log.info("prewarm skipped: DATABASE_URL not set")
        return 0

    now = datetime.now(tz=timezone.utc)
    start = now - timedelta(days=max(1, trailing_days))
    start_ms, end_ms = _ms(start), _ms(now)

    min_intervals = _source_min_intervals()
    watchlist = load_watchlist()
    succeeded = 0
    for entry in watchlist:
        if not entry.funding and entry.interval not in INTERVAL_MS:
            log.warning("prewarm skip %s: unknown interval %s", entry, entry.interval)
            continue
        if not _is_due(entry, now, min_intervals):
            log.debug("prewarm throttled %s (per-source min interval)", entry)
            continue
        # Record the attempt before fetching so failures are throttled too;
        # otherwise a persistently failing rate-limited source could be hit
        # every cycle and exhaust its quota.
        _LAST_RUN[entry] = now
        try:
            rows = _fetch_entry(entry, start_ms, end_ms)
            kind = "funding" if entry.funding else entry.interval
            log.info("prewarm %s:%s %s -> %d rows", entry.source, entry.symbol, kind, rows)
            succeeded += 1
        except Exception:  # noqa: BLE001 - one bad symbol must not kill the loop
            log.exception("prewarm failed for %s", entry)
    return succeeded
