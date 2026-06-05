"""Tests for the data layer that don't require network access."""
import pytest

from app.data.providers import MAX_TICKS, MarketData


def test_yield_only_synthesizes_timeline():
    """A strategy with no price/signal nodes (empty requirements) must still
    get a tick timeline built from the requested range."""
    md = MarketData.build([], [], "1h", "2024-01-01", "2024-01-05")
    assert len(md.timeline) > 0
    # 4 days of hourly ticks (inclusive endpoints) ~ 97 points
    assert 90 <= len(md.timeline) <= 100
    # No price series, and reference price is gracefully None.
    assert md.reference_price(md.timeline[0]) is None


def test_oversized_range_is_rejected():
    """A range exceeding MAX_TICKS candles fails fast before any fetch."""
    # ~5 years of 1m candles is far above the cap.
    with pytest.raises(ValueError, match="too large"):
        MarketData.build([], [], "1m", "2020-01-01", "2025-01-01")


def test_large_but_under_cap_range_is_allowed():
    """A wide 1m range that stays under the cap still builds."""
    from datetime import datetime, timedelta, timezone

    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(minutes=MAX_TICKS - 100)
    md = MarketData.build([], [], "1m", start.isoformat(), end.isoformat())
    assert md.timeline is not None and len(md.timeline) > 0
