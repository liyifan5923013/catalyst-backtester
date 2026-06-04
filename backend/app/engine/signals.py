"""Signal evaluation with rising-edge (re-arming) trigger state.

A ``price_threshold`` signal is a boolean predicate over the current price.
We only *fire* downstream actions on the transition false -> true, and we
re-arm once the predicate goes back to false. This gives the repeating
ladder / round-trip behavior without firing every tick.
"""
from __future__ import annotations

from typing import Dict

from ..models import Node


class SignalState:
    """Tracks the previous boolean value of each signal for edge detection."""

    def __init__(self, signal_ids):
        self._prev: Dict[str, bool] = {sid: False for sid in signal_ids}

    @staticmethod
    def evaluate(node: Node, price: float) -> bool:
        cfg = node.config
        operator = str(cfg.get("operator", cfg.get("op", "")))
        threshold = float(cfg.get("threshold"))
        if operator in ("<", "lt", "below", "less_than"):
            return price < threshold
        if operator in ("<=", "lte"):
            return price <= threshold
        if operator in (">", "gt", "above", "greater_than"):
            return price > threshold
        if operator in (">=", "gte"):
            return price >= threshold
        raise ValueError(f"Unsupported signal operator '{operator}' on node '{node.id}'")

    def rising_edge(self, signal_id: str, current: bool) -> bool:
        """Return True if this signal just transitioned false -> true."""
        prev = self._prev.get(signal_id, False)
        self._prev[signal_id] = current
        return current and not prev
