"""SQLAlchemy table definitions and low-level CRUD for the market-data store.

Three tables (mirrored by the Alembic initial migration):

- ``candles``  -- OHLCV keyed by (source, symbol, interval, ts)
- ``funding``  -- 8h funding rates keyed by (source, symbol, ts)
- ``coverage`` -- contiguous [seg_start, seg_end] windows we have already
  fetched per (source, symbol, interval), so we can distinguish "fetched and
  genuinely empty" from "never fetched".

All timestamps are timezone-aware UTC. Prices/volumes are doubles.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

import pandas as pd
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    MetaData,
    String,
    Table,
    and_,
    delete,
    select,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine

metadata = MetaData()

candles = Table(
    "candles",
    metadata,
    Column("source", String, primary_key=True),
    Column("symbol", String, primary_key=True),
    Column("interval", String, primary_key=True),
    Column("ts", DateTime(timezone=True), primary_key=True),
    Column("open", Float, nullable=False),
    Column("high", Float, nullable=False),
    Column("low", Float, nullable=False),
    Column("close", Float, nullable=False),
    Column("volume", Float, nullable=False),
)

funding = Table(
    "funding",
    metadata,
    Column("source", String, primary_key=True),
    Column("symbol", String, primary_key=True),
    Column("ts", DateTime(timezone=True), primary_key=True),
    Column("rate", Float, nullable=False),
)

coverage = Table(
    "coverage",
    metadata,
    Column("source", String, primary_key=True),
    Column("symbol", String, primary_key=True),
    Column("interval", String, primary_key=True),
    Column("seg_start", DateTime(timezone=True), primary_key=True),
    Column("seg_end", DateTime(timezone=True), nullable=False),
)


def _to_utc(ts) -> datetime:
    """Coerce a pandas/py datetime into a tz-aware UTC datetime."""
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    else:
        t = t.tz_convert("UTC")
    return t.to_pydatetime()


# -- candles ----------------------------------------------------------------
def upsert_candles(engine: Engine, source: str, symbol: str, interval: str, df: pd.DataFrame) -> int:
    """Upsert an OHLCV frame (index = tz-aware ts) for one series. Returns rows."""
    if df is None or df.empty:
        return 0
    rows = []
    for ts, row in df.iterrows():
        rows.append(
            {
                "source": source,
                "symbol": symbol.upper(),
                "interval": interval,
                "ts": _to_utc(ts),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            }
        )
    if not rows:
        return 0
    stmt = pg_insert(candles).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["source", "symbol", "interval", "ts"],
        set_={
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "volume": stmt.excluded.volume,
        },
    )
    with engine.begin() as conn:
        conn.execute(stmt)
    return len(rows)


def get_candles(
    engine: Engine, source: str, symbol: str, interval: str, start: datetime, end: datetime
) -> pd.DataFrame:
    """Read OHLCV in [start, end] inclusive as a frame indexed by tz-aware ts."""
    stmt = (
        select(candles.c.ts, candles.c.open, candles.c.high, candles.c.low, candles.c.close, candles.c.volume)
        .where(
            and_(
                candles.c.source == source,
                candles.c.symbol == symbol.upper(),
                candles.c.interval == interval,
                candles.c.ts >= _to_utc(start),
                candles.c.ts <= _to_utc(end),
            )
        )
        .order_by(candles.c.ts)
    )
    with engine.connect() as conn:
        result = conn.execute(stmt).fetchall()
    if not result:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    frame = pd.DataFrame(result, columns=["open_time", "open", "high", "low", "close", "volume"])
    frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True)
    frame = frame.set_index("open_time").sort_index()
    return frame[["open", "high", "low", "close", "volume"]]


# -- funding ----------------------------------------------------------------
def upsert_funding(engine: Engine, source: str, symbol: str, df: pd.DataFrame) -> int:
    """Upsert a funding frame (index = tz-aware ts, column ``funding_rate``)."""
    if df is None or df.empty:
        return 0
    rows = [
        {
            "source": source,
            "symbol": symbol.upper(),
            "ts": _to_utc(ts),
            "rate": float(row["funding_rate"]),
        }
        for ts, row in df.iterrows()
    ]
    if not rows:
        return 0
    stmt = pg_insert(funding).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["source", "symbol", "ts"],
        set_={"rate": stmt.excluded.rate},
    )
    with engine.begin() as conn:
        conn.execute(stmt)
    return len(rows)


def get_funding(
    engine: Engine, source: str, symbol: str, start: datetime, end: datetime
) -> pd.DataFrame:
    """Read funding in [start, end] inclusive as a frame with ``funding_rate``."""
    stmt = (
        select(funding.c.ts, funding.c.rate)
        .where(
            and_(
                funding.c.source == source,
                funding.c.symbol == symbol.upper(),
                funding.c.ts >= _to_utc(start),
                funding.c.ts <= _to_utc(end),
            )
        )
        .order_by(funding.c.ts)
    )
    with engine.connect() as conn:
        result = conn.execute(stmt).fetchall()
    if not result:
        return pd.DataFrame(columns=["funding_rate"])
    frame = pd.DataFrame(result, columns=["time", "funding_rate"])
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    frame = frame.set_index("time").sort_index()
    return frame[["funding_rate"]]


# -- coverage ---------------------------------------------------------------
# ``funding`` has no interval dimension; we store its coverage under this
# sentinel so the same table/logic can be reused.
FUNDING_INTERVAL = "__funding__"


def get_coverage(
    engine: Engine, source: str, symbol: str, interval: str
) -> List[Tuple[datetime, datetime]]:
    """Return stored coverage segments for a series, sorted by start."""
    stmt = (
        select(coverage.c.seg_start, coverage.c.seg_end)
        .where(
            and_(
                coverage.c.source == source,
                coverage.c.symbol == symbol.upper(),
                coverage.c.interval == interval,
            )
        )
        .order_by(coverage.c.seg_start)
    )
    with engine.connect() as conn:
        result = conn.execute(stmt).fetchall()
    return [(pd.Timestamp(r[0]).to_pydatetime(), pd.Timestamp(r[1]).to_pydatetime()) for r in result]


def replace_coverage(
    engine: Engine,
    source: str,
    symbol: str,
    interval: str,
    segments: List[Tuple[datetime, datetime]],
) -> None:
    """Replace all coverage rows for a series with the provided merged segments."""
    sym = symbol.upper()
    del_stmt = delete(coverage).where(
        and_(
            coverage.c.source == source,
            coverage.c.symbol == sym,
            coverage.c.interval == interval,
        )
    )
    rows = [
        {
            "source": source,
            "symbol": sym,
            "interval": interval,
            "seg_start": _to_utc(s),
            "seg_end": _to_utc(e),
        }
        for s, e in segments
    ]
    with engine.begin() as conn:
        conn.execute(del_stmt)
        if rows:
            conn.execute(pg_insert(coverage).values(rows))
