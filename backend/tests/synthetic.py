"""Synthetic market data for offline, deterministic tests.

Builds a :class:`MarketData` with an ETH price path that sweeps down through
the low thresholds and up through the high thresholds used by the example
graphs, so every signal fires at least once. No network required.
"""
from __future__ import annotations

import math
from typing import List, Tuple

import pandas as pd

from app.data.providers import MarketData


def make_market_data(
    start: str = "2024-01-01",
    periods: int = 400,
    interval: str = "1h",
    low: float = 1400.0,
    high: float = 2800.0,
) -> MarketData:
    idx = pd.date_range(start=start, periods=periods, freq="h", tz="UTC")
    mid = (low + high) / 2.0
    amp = (high - low) / 2.0
    # Two full sine cycles so thresholds are crossed repeatedly.
    prices = [mid + amp * math.sin(2 * math.pi * 2 * i / periods) for i in range(periods)]

    frame = pd.DataFrame(index=idx)
    frame["ETH@evm"] = prices
    frame["ETH@hyperliquid"] = [p * 1.001 for p in prices]  # tiny basis

    # One funding event per 8h, small positive rate.
    funding: List[Tuple[pd.Timestamp, str, float]] = []
    for ts in pd.date_range(start=idx[0], end=idx[-1], freq="8h", tz="UTC"):
        funding.append((ts, "ETH", 0.0001))

    return MarketData(timeline=idx, interval=interval, _price_frame=frame, funding_events=funding)
