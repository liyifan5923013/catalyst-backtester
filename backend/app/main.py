"""FastAPI application entrypoint.

In production the built React frontend is served from the same origin: set the
``FRONTEND_DIST`` env var (or place the build at ``frontend/dist``) and it will
be mounted at ``/``. The API lives under ``/api`` and OpenAPI docs at ``/docs``.
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api.routes import router

app = FastAPI(
    title="Catalyst Backtesting Engine",
    description="Backtest Catalyst strategy graphs against historical market data.",
    version="0.1.0",
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
