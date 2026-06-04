"""Tests for the data layer that don't require network access."""
from app.data.providers import MarketData


def test_yield_only_synthesizes_timeline():
    """A strategy with no price/signal nodes (empty requirements) must still
    get a tick timeline built from the requested range."""
    md = MarketData.build([], [], "1h", "2024-01-01", "2024-01-05")
    assert len(md.timeline) > 0
    # 4 days of hourly ticks (inclusive endpoints) ~ 97 points
    assert 90 <= len(md.timeline) <= 100
    # No price series, and reference price is gracefully None.
    assert md.reference_price(md.timeline[0]) is None
