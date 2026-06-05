"""Randomized (but valid) Catalyst graph generator for fuzz/property testing.

Produces graphs that exercise every action type (swap, perp, yield) and the
``price_threshold`` signal, wired with ``signal -> action`` and
``action -> action`` edges. Generation is driven by an injected
``random.Random`` so every graph is reproducible from its seed.

Assets are restricted to symbols that have offline synthetic price series
(see ``tests/synthetic.py``) so generated graphs are runnable without network:
ETH (EVM + Hyperliquid), AAPL/SPY (equity), and the USDC stablecoin.

Run as a script to emit a graph you can paste into the web/mobile UI::

    python -m tests.graph_gen --seed 7              # one graph
    python -m tests.graph_gen --count 5 --pretty    # five graphs
"""
from __future__ import annotations

import argparse
import json
import random
from typing import Any, Dict, List

STABLE = "USDC"

# Spot-tradable (symbol, chain) pairs that have synthetic prices.
SPOT_ASSETS = [
    ("ETH", "base"),         # EVM
    ("ETH", "hyperliquid"),  # Hyperliquid spot
    ("AAPL", "equity"),
    ("SPY", "equity"),
]

# Only ETH has a Hyperliquid perp + funding series offline.
PERP_SYMBOL = "ETH"
PERP_CHAIN = "hyperliquid"
LEVERAGES = [1, 2, 3, 5, 10]

# (signal symbol, market, plausible threshold range) within the synthetic paths.
SIGNAL_SPECS = [
    ("ETH", "crypto", (1400.0, 2800.0)),
    ("AAPL", "equity", (160.0, 200.0)),
    ("SPY", "equity", (420.0, 480.0)),
]
OPERATORS = ["<", ">", "<=", ">=", "below", "above"]

ACTION_KINDS = [
    "swap_buy",
    "swap_sell",
    "perp_open",
    "perp_close",
    "yield_deposit",
    "yield_withdraw",
]


def _amount_or_all(rng: random.Random, lo: float, hi: float) -> Any:
    """Sometimes a numeric amount, sometimes the 'all'/'max' sentinel."""
    roll = rng.random()
    if roll < 0.15:
        return "all"
    if roll < 0.2:
        return "max"
    # Mix of plausible and intentionally-too-large amounts to exercise the
    # insufficient-funds guards.
    return round(rng.uniform(lo, hi), 2)


def _action_config(rng: random.Random, kind: str) -> Dict[str, Any]:
    if kind == "swap_buy":
        sym, chain = rng.choice(SPOT_ASSETS)
        return {
            "from_asset": STABLE,
            "to_asset": sym,
            "amount": _amount_or_all(rng, 50, 20000),
            "chain": chain,
        }
    if kind == "swap_sell":
        sym, chain = rng.choice(SPOT_ASSETS)
        return {
            "from_asset": sym,
            "to_asset": STABLE,
            "amount": _amount_or_all(rng, 0.01, 5.0),
            "chain": chain,
        }
    if kind == "perp_open":
        return {
            "symbol": PERP_SYMBOL,
            "chain": PERP_CHAIN,
            "side": rng.choice(["long", "short"]),
            "size_usd": _amount_or_all(rng, 100, 20000),
            "leverage": rng.choice(LEVERAGES),
            "reduce_only": False,
        }
    if kind == "perp_close":
        return {
            "symbol": PERP_SYMBOL,
            "chain": PERP_CHAIN,
            "side": rng.choice(["long", "short"]),
            "size_usd": _amount_or_all(rng, 100, 20000),
            "reduce_only": True,
        }
    if kind == "yield_deposit":
        return {
            "chain": "base",
            "protocol": "aave",
            "pool": "",
            "asset": STABLE,
            "amount": _amount_or_all(rng, 50, 20000),
        }
    if kind == "yield_withdraw":
        return {
            "chain": "base",
            "protocol": "aave",
            "pool": "",
            "asset": STABLE,
            "amount": _amount_or_all(rng, 50, 20000),
        }
    raise ValueError(f"unknown action kind {kind!r}")


def _subtype_for(kind: str) -> str:
    return {
        "swap_buy": "swap",
        "swap_sell": "swap",
        "perp_open": "perp_order",
        "perp_close": "perp_order",
        "yield_deposit": "yield_deposit",
        "yield_withdraw": "yield_withdraw",
    }[kind]


def _signal_config(rng: random.Random) -> Dict[str, Any]:
    sym, market, (lo, hi) = rng.choice(SIGNAL_SPECS)
    return {
        "symbol": sym,
        "market": market,
        "operator": rng.choice(OPERATORS),
        "threshold": round(rng.uniform(lo, hi), 2),
    }


def generate_graph(rng: random.Random) -> Dict[str, Any]:
    """Return a randomized, schema-valid graph dict (nodes + edges)."""
    n_actions = rng.randint(1, 4)
    n_signals = rng.randint(0, 2)

    nodes: List[Dict[str, Any]] = []
    action_ids: List[str] = []
    for i in range(n_actions):
        kind = rng.choice(ACTION_KINDS)
        aid = f"a{i}"
        action_ids.append(aid)
        nodes.append(
            {
                "id": aid,
                "kind": "action",
                "subtype": _subtype_for(kind),
                "config": _action_config(rng, kind),
                # Occasionally disable a node to exercise the enabled flag.
                "enabled": rng.random() > 0.1,
            }
        )

    signal_ids: List[str] = []
    for j in range(n_signals):
        sid = f"s{j}"
        signal_ids.append(sid)
        nodes.append(
            {
                "id": sid,
                "kind": "signal",
                "subtype": "price_threshold",
                "config": _signal_config(rng),
                "enabled": True,
            }
        )

    edges: List[Dict[str, str]] = []
    seen = set()

    def _add_edge(src: str, dst: str) -> None:
        if (src, dst) not in seen:
            seen.add((src, dst))
            edges.append({"from": src, "to": dst})

    # action -> action chains, strictly forward to keep a DAG.
    for i in range(1, n_actions):
        if rng.random() < 0.4:
            parent = action_ids[rng.randint(0, i - 1)]
            _add_edge(parent, action_ids[i])

    # signal -> action triggers (targets must be actions).
    for sid in signal_ids:
        for dst in rng.sample(action_ids, k=rng.randint(1, len(action_ids))):
            _add_edge(sid, dst)

    return {"nodes": nodes, "edges": edges}


def _main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Generate randomized Catalyst graphs.")
    p.add_argument("--seed", type=int, default=0, help="Base RNG seed.")
    p.add_argument("--count", type=int, default=1, help="How many graphs to emit.")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    args = p.parse_args(argv)

    graphs = [generate_graph(random.Random(args.seed + i)) for i in range(args.count)]
    out: Any = graphs if args.count > 1 else graphs[0]
    print(json.dumps(out, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
