"""HTTP routes for the backtesting API."""
from __future__ import annotations

import json
import os
from typing import List

from fastapi import APIRouter, HTTPException

from ..models import BacktestRequest, BacktestResult, SummaryRequest, SummaryResponse
from ..engine.simulator import run_backtest
from ..summary import generate_summary

router = APIRouter(prefix="/api")

EXAMPLES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "examples")


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/examples")
def list_examples() -> List[dict]:
    if not os.path.isdir(EXAMPLES_DIR):
        return []
    out = []
    for name in sorted(os.listdir(EXAMPLES_DIR)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(EXAMPLES_DIR, name), "r") as f:
            data = json.load(f)
        out.append({
            "name": name[:-5],
            "title": data.get("title", name[:-5]),
            "graph": data.get("graph", data),
        })
    return out


@router.post("/backtest", response_model=BacktestResult)
def backtest(req: BacktestRequest) -> BacktestResult:
    try:
        return run_backtest(req)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Backtest failed: {exc}")


@router.post("/summary", response_model=SummaryResponse)
def summary(req: SummaryRequest) -> SummaryResponse:
    try:
        return generate_summary(req)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Summary failed: {exc}")
