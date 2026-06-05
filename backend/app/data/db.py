"""Database engine wiring for the optional TimescaleDB persistence layer.

The whole persistence layer is opt-in: if ``DATABASE_URL`` is not set we fall
back to the legacy direct-fetch + parquet cache path so the zero-ops demo keeps
working. When it *is* set, candles/funding are served read-through from
Postgres/Timescale (see :mod:`app.data.repository`).
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from sqlalchemy import Engine, create_engine


def database_url() -> Optional[str]:
    """Return the configured DATABASE_URL, normalized for SQLAlchemy+psycopg3.

    Accepts the common ``postgres://`` / ``postgresql://`` prefixes (e.g. from
    managed providers) and rewrites them to ``postgresql+psycopg://`` so we use
    the psycopg v3 driver.
    """
    raw = os.environ.get("DATABASE_URL")
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://"):]
    if raw.startswith("postgresql://"):
        raw = "postgresql+psycopg://" + raw[len("postgresql://"):]
    return raw


def is_enabled() -> bool:
    """True when a persistence backend is configured."""
    return database_url() is not None


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Return a process-wide SQLAlchemy engine.

    Raises if no DATABASE_URL is configured; callers should guard with
    :func:`is_enabled` first.
    """
    url = database_url()
    if url is None:
        raise RuntimeError("DATABASE_URL is not set; persistence layer is disabled.")
    return create_engine(url, pool_pre_ping=True, future=True)
