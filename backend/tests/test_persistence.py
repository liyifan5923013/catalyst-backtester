"""Tests for the persistence layer.

The gap/coverage/staleness arithmetic is pure and always runs. The read-through
repository round-trip is an integration test gated on DATABASE_URL (a real
Postgres/Timescale instance), so it is skipped in the default offline suite.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.data import db
from app.data.repository import compute_gaps, merge_segments, subtract_coverage


def dt(day: int, hour: int = 0) -> datetime:
    return datetime(2024, 1, day, hour, tzinfo=timezone.utc)


# -- pure interval logic ----------------------------------------------------
def test_merge_segments_combines_overlap_and_adjacency():
    segs = [(dt(1), dt(3)), (dt(2), dt(4)), (dt(4), dt(5)), (dt(7), dt(8))]
    assert merge_segments(segs) == [(dt(1), dt(5)), (dt(7), dt(8))]


def test_merge_segments_empty():
    assert merge_segments([]) == []


def test_subtract_coverage_no_coverage_returns_whole_request():
    assert subtract_coverage((dt(1), dt(10)), []) == [(dt(1), dt(10))]


def test_subtract_coverage_full_coverage_returns_nothing():
    assert subtract_coverage((dt(2), dt(5)), [(dt(1), dt(10))]) == []


def test_subtract_coverage_leaves_holes():
    gaps = subtract_coverage((dt(1), dt(10)), [(dt(3), dt(5)), (dt(7), dt(8))])
    assert gaps == [(dt(1), dt(3)), (dt(5), dt(7)), (dt(8), dt(10))]


def test_subtract_coverage_partial_left_and_right():
    gaps = subtract_coverage((dt(1), dt(10)), [(dt(4), dt(6))])
    assert gaps == [(dt(1), dt(4)), (dt(6), dt(10))]


def test_compute_gaps_settled_history_fully_cached():
    # Request entirely before the horizon and fully covered -> no gaps.
    horizon = dt(20)
    assert compute_gaps((dt(1), dt(10)), [(dt(1), dt(10))], horizon) == []


def test_compute_gaps_always_refetches_live_tail():
    # End is past the horizon; the tail past the horizon is always a gap even
    # if coverage claims it is stored.
    horizon = dt(10)
    gaps = compute_gaps((dt(1), dt(12)), [(dt(1), dt(12))], horizon)
    assert gaps == [(dt(10), dt(12))]


def test_compute_gaps_combines_history_hole_and_live_tail():
    horizon = dt(8)
    gaps = compute_gaps((dt(1), dt(12)), [(dt(1), dt(4))], horizon)
    # Hole [4,8] before horizon, plus live tail [8,12].
    assert gaps == [(dt(4), dt(12))]


def test_compute_gaps_empty_when_request_degenerate():
    assert compute_gaps((dt(5), dt(5)), [], dt(20)) == []


# -- integration (requires a real Postgres/Timescale via DATABASE_URL) ------
@pytest.mark.skipif(not db.is_enabled(), reason="DATABASE_URL not set")
def test_repository_read_through_only_fetches_gaps():
    from app.data import store
    from app.data.repository import MarketRepository

    engine = db.get_engine()
    store.metadata.create_all(engine)

    calls = {"n": 0}

    def fetcher(symbol, interval, start_ms, end_ms):
        calls["n"] += 1
        idx = pd.date_range(
            start=pd.Timestamp(start_ms, unit="ms", tz="UTC"),
            end=pd.Timestamp(end_ms, unit="ms", tz="UTC"),
            freq="1h",
        )
        return pd.DataFrame(
            {
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "volume": 1.0,
            },
            index=idx,
        )

    repo = MarketRepository(engine=engine)
    # A range well in the past so it is fully settled (no live-tail refetch).
    start = datetime(2023, 1, 1, tzinfo=timezone.utc)
    end = datetime(2023, 1, 2, tzinfo=timezone.utc)

    df1 = repo.get_candles("test", "ZZZ", "1h", start, end, fetcher, 3_600_000)
    assert not df1.empty
    assert calls["n"] >= 1

    before = calls["n"]
    df2 = repo.get_candles("test", "ZZZ", "1h", start, end, fetcher, 3_600_000)
    assert not df2.empty
    # Second identical, fully-settled request must not hit the provider again.
    assert calls["n"] == before

    with engine.begin() as conn:
        from sqlalchemy import delete

        conn.execute(delete(store.candles).where(store.candles.c.source == "test"))
        conn.execute(delete(store.coverage).where(store.coverage.c.source == "test"))
