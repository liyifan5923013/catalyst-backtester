"""Graph parsing, validation, and trigger-structure construction.

Turns a Catalyst :class:`~app.models.Graph` into a runtime structure the
simulator can execute, encoding the semantics described in the README:

- root actions (no incoming edge) run once at t0,
- ``signal -> action`` edges fire on a rising edge (with re-arm),
- ``action -> action`` edges chain sequentially.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from ..models import Graph, Node
from ..data.equity_providers import EQUITY_CHAINS

ACTION_SUBTYPES = {"swap", "perp_order", "yield_deposit", "yield_withdraw"}
SIGNAL_SUBTYPES = {"price_threshold"}
EVM_CHAINS = {"base", "ethereum", "eth", "arbitrum", "optimism", "polygon", "evm"}


def _venue_for_chain(chain: str) -> str:
    cl = chain.lower()
    if cl == "hyperliquid":
        return "hyperliquid"
    if cl in EQUITY_CHAINS:
        return "equity"
    return "evm"


@dataclass
class GraphRuntime:
    nodes: Dict[str, Node]
    root_action_ids: List[str]  # actions with no incoming edge (run at t0)
    signal_ids: List[str]  # evaluated every tick
    action_children: Dict[str, List[str]]  # action_id -> downstream action ids
    signal_children: Dict[str, List[str]]  # signal_id -> downstream action ids

    def node(self, node_id: str) -> Node:
        return self.nodes[node_id]

    # -- requirements for the data layer --------------------------------
    def data_requirements(self) -> Tuple[List[Tuple[str, str]], List[str]]:
        """Return ``(price_requirements, funding_symbols)``.

        ``price_requirements`` is a list of ``(symbol, venue)`` where venue is
        ``"evm"``, ``"hyperliquid"``, or ``"equity"``. ``funding_symbols`` lists perp symbols
        that need funding-rate data.
        """
        prices: set[Tuple[str, str]] = set()
        funding: set[str] = set()
        for node in self.nodes.values():
            if not node.enabled:
                continue
            cfg = node.config
            if node.kind == "signal" and node.subtype == "price_threshold":
                sym = str(cfg.get("symbol", "")).upper()
                market = str(cfg.get("market", "crypto")).lower()
                venue = "equity" if market in ("equity", "stock") else "evm"
                prices.add((sym, venue))
            elif node.subtype == "swap":
                symbol = _swap_symbol(cfg)
                venue = _venue_for_chain(str(cfg.get("chain", "base")))
                prices.add((symbol, venue))
            elif node.subtype == "perp_order":
                symbol = str(cfg.get("symbol", "")).upper()
                prices.add((symbol, "hyperliquid"))
                funding.add(symbol)
            # yield nodes need no price series (stablecoin principal)
        prices.discard(("", "evm"))
        return sorted(prices), sorted(funding)


def _swap_symbol(cfg: dict) -> str:
    """The traded (non-stablecoin) symbol of a swap."""
    frm = str(cfg.get("from_asset", "")).upper()
    to = str(cfg.get("to_asset", "")).upper()
    stables = {"USDC", "USDT", "DAI", "USD"}
    if frm in stables:
        return to
    return frm


def build_runtime(graph: Graph) -> GraphRuntime:
    nodes: Dict[str, Node] = {}
    for node in graph.nodes:
        if node.id in nodes:
            raise ValueError(f"Duplicate node id: {node.id}")
        nodes[node.id] = node

    # Validate node kinds/subtypes.
    for node in nodes.values():
        if node.kind == "action" and node.subtype not in ACTION_SUBTYPES:
            raise ValueError(f"Unsupported action subtype '{node.subtype}' on node '{node.id}'")
        if node.kind == "signal" and node.subtype not in SIGNAL_SUBTYPES:
            raise ValueError(f"Unsupported signal subtype '{node.subtype}' on node '{node.id}'")
        if node.kind not in {"action", "signal"}:
            raise ValueError(f"Unsupported node kind '{node.kind}' on node '{node.id}'")

    indegree: Dict[str, int] = {nid: 0 for nid in nodes}
    action_children: Dict[str, List[str]] = {nid: [] for nid in nodes}
    signal_children: Dict[str, List[str]] = {nid: [] for nid in nodes}

    for edge in graph.edges:
        if edge.from_ not in nodes:
            raise ValueError(f"Edge references unknown source node '{edge.from_}'")
        if edge.to not in nodes:
            raise ValueError(f"Edge references unknown target node '{edge.to}'")
        src = nodes[edge.from_]
        dst = nodes[edge.to]
        if dst.kind != "action":
            raise ValueError(
                f"Edge target '{edge.to}' must be an action (signals are not triggered by edges)."
            )
        indegree[edge.to] += 1
        if src.kind == "signal":
            signal_children[edge.from_].append(edge.to)
        else:  # action -> action
            action_children[edge.from_].append(edge.to)

    root_action_ids = [
        nid
        for nid, node in nodes.items()
        if node.kind == "action" and node.enabled and indegree[nid] == 0
    ]
    signal_ids = [nid for nid, node in nodes.items() if node.kind == "signal" and node.enabled]

    return GraphRuntime(
        nodes=nodes,
        root_action_ids=root_action_ids,
        signal_ids=signal_ids,
        action_children=action_children,
        signal_children=signal_children,
    )
