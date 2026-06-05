"""Read-through market-data repository over the Timescale store.

On each request we serve cached rows from the store and fetch only the missing
time gaps from the providers, persisting them back. Coverage segments let us
remember windows that were fetched but returned no rows (exchange gaps), and a
freshness horizon keeps the most recent (still-forming) candles refreshing.

The gap arithmetic is pure and unit-tested independently of any database.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional, Tuple

import pandas as pd

from . import db, store

Segment = Tuple[datetime, datetime]


# -- pure interval helpers (no DB) -----------------------------------------
def merge_segments(segments: List[Segment]) -> List[Segment]:
    """Merge overlapping/adjacent [start, end] segments into a minimal set."""
    if not segments:
        return []
    ordered = sorted(segments, key=lambda s: s[0])
    merged: List[Segment] = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged[-1] = (last_start, last_end)
            merged.append((start, end))
    return merged


def subtract_coverage(
    request: Segment, segments: List[Segment]
) -> List[Segment]:
    """Return the sub-ranges of ``request`` not covered by ``segments``."""
    start, end = request
    if end <= start:
        return []
    gaps: List[Segment] = []
    cursor = start
    for seg_start, seg_end in merge_segments(segments):
        if seg_end <= cursor:
            continue
        if seg_start >= end:
            break
        if seg_start > cursor:
            gaps.append((cursor, min(seg_start, end)))
        cursor = max(cursor, seg_end)
        if cursor >= end:
            break
    if cursor < end:
        gaps.append((cursor, end))
    return gaps


def compute_gaps(
    request: Segment, segments: List[Segment], horizon: datetime
) -> List[Segment]:
    """Gaps to fetch: uncovered sub-ranges, plus always the live tail past horizon.

    Any portion of the request after ``horizon`` (the last fully-closed candle)
    is treated as a gap regardless of stored coverage, so recent data refreshes
    on every run.
    """
    start, end = request
    if end <= start:
        return []
    # Only the part up to the horizon can be satisfied from coverage.
    settled_end = min(end, horizon)
    gaps: List[Segment] = []
    if settled_end > start:
        gaps.extend(subtract_coverage((start, settled_end), segments))
    if end > horizon:
        gaps.append((max(start, horizon), end))
    return merge_segments(gaps)


# -- repository -------------------------------------------------------------
# Candle fetcher signature: (symbol, interval, start_ms, end_ms) -> OHLCV frame
CandleFetcher = Callable[[str, str, int, int], pd.DataFrame]
# Funding fetcher signature: (symbol, start_ms, end_ms) -> funding frame
FundingFetcher = Callable[[str, int, int], pd.DataFrame]


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


class MarketRepository:
    """Read-through cache for candles and funding backed by the Timescale store."""

    def __init__(self, engine=None):
        self.engine = engine or db.get_engine()

    def get_candles(
        self,
        source: str,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
        fetcher: CandleFetcher,
        interval_ms: int,
    ) -> pd.DataFrame:
        horizon = _now_utc() - timedelta(milliseconds=interval_ms)
        existing = store.get_coverage(self.engine, source, symbol, interval)
        gaps = compute_gaps((start, end), existing, horizon)

        new_settled: List[Segment] = []
        for gap_start, gap_end in gaps:
            frame = fetcher(symbol, interval, _ms(gap_start), _ms(gap_end))
            store.upsert_candles(self.engine, source, symbol, interval, frame)
            # Only record coverage up to the horizon; never mark the live tail.
            settled_end = min(gap_end, horizon)
            if settled_end > gap_start:
                new_settled.append((gap_start, settled_end))

        if new_settled:
            merged = merge_segments(existing + new_settled)
            store.replace_coverage(self.engine, source, symbol, interval, merged)

        return store.get_candles(self.engine, source, symbol, interval, start, end)

    def get_funding(
        self,
        source: str,
        symbol: str,
        start: datetime,
        end: datetime,
        fetcher: FundingFetcher,
        interval_ms: int,
    ) -> pd.DataFrame:
        horizon = _now_utc() - timedelta(milliseconds=interval_ms)
        existing = store.get_coverage(self.engine, source, symbol, store.FUNDING_INTERVAL)
        gaps = compute_gaps((start, end), existing, horizon)

        new_settled: List[Segment] = []
        for gap_start, gap_end in gaps:
            frame = fetcher(symbol, _ms(gap_start), _ms(gap_end))
            store.upsert_funding(self.engine, source, symbol, frame)
            settled_end = min(gap_end, horizon)
            if settled_end > gap_start:
                new_settled.append((gap_start, settled_end))

        if new_settled:
            merged = merge_segments(existing + new_settled)
            store.replace_coverage(self.engine, source, symbol, store.FUNDING_INTERVAL, merged)

        return store.get_funding(self.engine, source, symbol, start, end)
