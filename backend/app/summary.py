"""AI summary of backtest results.

If ``OPENAI_API_KEY`` is configured, a concise narrative + recommendations are
produced by an LLM (any OpenAI-compatible Chat Completions endpoint). Otherwise
- or if the LLM call fails for any reason - we fall back to a deterministic,
rule-based narrative so the endpoint never breaks the UX.
"""
from __future__ import annotations

import json
import os
from typing import List

import httpx

from .models import Metrics, SummaryRequest, SummaryResponse


def _llm_enabled() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


# -- formatting helpers -----------------------------------------------------
def _pct(x: float) -> str:
    return f"{x:+.2f}%"


def _money(x: float) -> str:
    return f"${x:,.2f}"


def _delta(curr: float, prev: float) -> float:
    return curr - prev


def _trend_word(d: float) -> str:
    if d > 0:
        return "increased"
    if d < 0:
        return "decreased"
    return "was unchanged"


# -- rule-based fallback ----------------------------------------------------
def _rule_based(req: SummaryRequest) -> SummaryResponse:
    m = req.metrics
    parts: List[str] = []
    strat = (req.strategy or "The strategy").rstrip(". ")
    parts.append(
        f"{strat} returned {_pct(m.total_return_pct)} over {req.start} to {req.end} "
        f"({req.interval} candles), ending at {_money(m.final_equity)} from "
        f"{_money(m.initial_capital)}."
    )
    parts.append(
        f"Risk: max drawdown {m.max_drawdown_pct:.2f}%, Sharpe {m.sharpe:.2f}. "
        f"{m.num_trades} trades, {_money(m.total_fees_usd)} in fees"
        + (f", win rate {m.win_rate_pct:.0f}%." if m.win_rate_pct is not None else ".")
    )

    cmp = req.comparison_metrics
    if cmp is not None:
        label = req.comparison_label or "the comparison period"
        dret = _delta(m.total_return_pct, cmp.total_return_pct)
        ddd = _delta(m.max_drawdown_pct, cmp.max_drawdown_pct)
        dsh = _delta(m.sharpe, cmp.sharpe)
        parts.append(
            f"Versus {label}, return {_trend_word(dret)} by {abs(dret):.2f} pts "
            f"({_pct(cmp.total_return_pct)} -> {_pct(m.total_return_pct)}); "
            f"drawdown {_trend_word(ddd)} by {abs(ddd):.2f} pts; "
            f"Sharpe {_trend_word(dsh)} by {abs(dsh):.2f}."
        )

    recs: List[str] = []
    if m.max_drawdown_pct > 20:
        recs.append("Drawdown is high (>20%); consider lower leverage or tighter risk limits.")
    if m.sharpe < 1:
        recs.append("Risk-adjusted return (Sharpe < 1) is weak; the strategy may not beat simply holding.")
    if m.num_trades > 0 and m.total_fees_usd > abs(m.final_equity - m.initial_capital):
        recs.append("Fees exceed net PnL; reduce trade frequency or sizes to cut cost drag.")
    if m.total_return_pct > 0 and m.max_drawdown_pct < 10 and m.sharpe >= 1:
        recs.append("Solid risk/return profile; test over additional date ranges to confirm robustness.")
    if cmp is not None and _delta(m.total_return_pct, cmp.total_return_pct) < 0:
        recs.append("Performance declined versus the comparison period; review what market regime changed.")
    if not recs:
        recs.append("Backtest over more periods and stress regimes before drawing conclusions.")

    return SummaryResponse(summary=" ".join(parts), recommendations=recs[:4], source="rule")


# -- LLM path ---------------------------------------------------------------
def _metrics_dict(m: Metrics) -> dict:
    return {
        "initial_capital": m.initial_capital,
        "final_equity": m.final_equity,
        "total_return_pct": m.total_return_pct,
        "max_drawdown_pct": m.max_drawdown_pct,
        "sharpe": m.sharpe,
        "num_trades": m.num_trades,
        "total_fees_usd": m.total_fees_usd,
        "win_rate_pct": m.win_rate_pct,
    }


def _build_prompt(req: SummaryRequest) -> str:
    payload = {
        "period": {"start": req.start, "end": req.end, "interval": req.interval},
        "strategy": req.strategy,
        "metrics": _metrics_dict(req.metrics),
    }
    if req.comparison_metrics is not None:
        payload["comparison"] = {
            "label": req.comparison_label,
            "start": req.comparison_start,
            "end": req.comparison_end,
            "metrics": _metrics_dict(req.comparison_metrics),
        }
    return (
        "You are a quantitative trading analyst. Given the backtest metrics below, "
        "write a concise, plain-English summary (2-4 sentences) and 2-4 specific, "
        "actionable recommendations. If a comparison period is present, explicitly "
        "call out whether each key metric improved or worsened and by how much "
        "(period-over-period). Be precise with numbers; do not invent data.\n\n"
        "Return STRICT JSON: {\"summary\": string, \"recommendations\": [string, ...]}.\n\n"
        f"DATA:\n{json.dumps(payload, indent=2)}"
    )


def _llm(req: SummaryRequest) -> SummaryResponse:
    api_key = os.environ["OPENAI_API_KEY"]
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a precise quantitative trading analyst. Respond only with the requested JSON."},
            {"role": "user", "content": _build_prompt(req)},
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
    }
    resp = httpx.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body,
        timeout=30,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    summary = str(parsed.get("summary", "")).strip()
    recs = [str(r).strip() for r in parsed.get("recommendations", []) if str(r).strip()]
    if not summary:
        raise ValueError("LLM returned empty summary")
    return SummaryResponse(summary=summary, recommendations=recs[:4], source="llm")


def generate_summary(req: SummaryRequest) -> SummaryResponse:
    """LLM summary when configured; deterministic fallback otherwise/on error."""
    if _llm_enabled():
        try:
            return _llm(req)
        except Exception:  # noqa: BLE001 - never fail the UX on LLM issues
            return _rule_based(req)
    return _rule_based(req)
