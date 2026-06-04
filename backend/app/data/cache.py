"""Simple parquet-backed cache for fetched market data.

Keyed by an opaque string; data is stored under ``backend/.cache/``.
This makes repeated backtests over the same range fast and reproducible
(and keeps us well under public-API rate limits).
"""
from __future__ import annotations

import hashlib
import os
from typing import Optional

import pandas as pd

_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".cache")


def _path_for(key: str) -> str:
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    safe = "".join(c if c.isalnum() else "_" for c in key)[:60]
    return os.path.join(_CACHE_DIR, f"{safe}_{digest}.parquet")


def load(key: str) -> Optional[pd.DataFrame]:
    path = _path_for(key)
    if os.path.exists(path):
        try:
            return pd.read_parquet(path)
        except Exception:
            return None
    return None


def store(key: str, df: pd.DataFrame) -> None:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    try:
        df.to_parquet(_path_for(key))
    except Exception:
        # Cache is best-effort; never fail a backtest because caching failed.
        pass
