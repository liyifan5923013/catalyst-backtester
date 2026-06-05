"""FastAPI application entrypoint.

In production the built React frontend is served from the same origin: set the
``FRONTEND_DIST`` env var (or place the build at ``frontend/dist``) and it will
be mounted at ``/``. The API lives under ``/api`` and OpenAPI docs at ``/docs``.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .data import db

log = logging.getLogger(__name__)


# Never poll faster than this; protects the providers from runaway loops.
PREWARM_MIN_INTERVAL_SECONDS = 60.0


def _prewarm_enabled() -> bool:
    """Opt-in via PREWARM_ENABLED, and only when a persistence backend exists."""
    flag = os.environ.get("PREWARM_ENABLED", "").strip().lower()
    return flag in {"1", "true", "yes", "on"} and db.is_enabled()


def _prewarm_interval_seconds() -> float:
    """Resolve the loop cadence in seconds.

    ``PREWARM_INTERVAL_MINUTES`` (when > 0) takes precedence over
    ``PREWARM_INTERVAL_HOURS`` (default 24h), enabling minute-level pre-warm.
    The result is floored at :data:`PREWARM_MIN_INTERVAL_SECONDS`.
    """
    minutes = 0.0
    try:
        minutes = float(os.environ.get("PREWARM_INTERVAL_MINUTES", "0") or 0)
    except ValueError:
        minutes = 0.0

    if minutes > 0:
        seconds = minutes * 60.0
    else:
        try:
            hours = float(os.environ.get("PREWARM_INTERVAL_HOURS", "24"))
        except ValueError:
            hours = 24.0
        seconds = hours * 3600.0

    return max(PREWARM_MIN_INTERVAL_SECONDS, seconds)


def _prewarm_trailing_days() -> int:
    try:
        return int(os.environ.get("PREWARM_TRAILING_DAYS", "365"))
    except ValueError:
        return 365


async def _prewarm_loop() -> None:
    """Background task: warm the watchlist on boot, then every interval.

    Runs in-process on the web instance (App Runner has no native cron). The
    underlying gap-fill is idempotent, so multiple instances are harmless. Each
    cycle's blocking provider calls run in a thread to avoid blocking the event
    loop. Cadence is hour- or minute-level via env (see
    :func:`_prewarm_interval_seconds`).
    """
    from .data.prewarm import run_prewarm

    interval_seconds = _prewarm_interval_seconds()
    trailing_days = _prewarm_trailing_days()

    while True:
        try:
            count = await asyncio.to_thread(run_prewarm, trailing_days)
            log.info("prewarm cycle complete: %d entries warmed", count)
        except Exception:  # noqa: BLE001 - never let the loop die
            log.exception("prewarm cycle errored")
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task: asyncio.Task | None = None
    if _prewarm_enabled():
        log.info("starting scheduled prewarm loop")
        task = asyncio.create_task(_prewarm_loop())
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


app = FastAPI(
    title="Catalyst Backtesting Engine",
    description="Backtest Catalyst strategy graphs against historical market data.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


def _frontend_dist() -> str | None:
    candidate = os.environ.get("FRONTEND_DIST")
    if candidate and os.path.isdir(candidate):
        return candidate
    default = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "frontend", "dist"
    )
    return default if os.path.isdir(default) else None


_dist = _frontend_dist()
if _dist:
    # Serve the SPA at the root. API routes are registered first, so /api wins.
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
else:
    @app.get("/")
    def root() -> dict:
        return {"name": "Catalyst Backtesting Engine", "docs": "/docs", "api": "/api"}
