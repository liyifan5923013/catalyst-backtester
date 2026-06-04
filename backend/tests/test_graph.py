import json
import os

import pytest

from app.models import Graph
from app.engine.graph import build_runtime

EXAMPLES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "examples")


def load_graph(name: str) -> Graph:
    with open(os.path.join(EXAMPLES_DIR, name)) as f:
        data = json.load(f)
    return Graph.model_validate(data["graph"])


def test_root_action_runs_at_t0():
    rt = build_runtime(load_graph("graph_01.json"))
    assert rt.root_action_ids == ["buy-eth-on-base"]
    assert rt.signal_ids == []


def test_action_chain():
    rt = build_runtime(load_graph("graph_03.json"))
    assert rt.root_action_ids == ["buy-eth-spot"]
    assert rt.action_children["buy-eth-spot"] == ["sell-eth-spot"]


def test_signal_triggers_action():
    rt = build_runtime(load_graph("graph_11.json"))
    assert "eth-below-1800" in rt.signal_ids
    assert rt.signal_children["eth-below-1800"] == ["buy-eth-on-base"]
    # signal-fed action is not a root
    assert "buy-eth-on-base" not in rt.root_action_ids


def test_repeating_ladder_structure():
    rt = build_runtime(load_graph("graph_04.json"))
    # initial inventory is a root; the rest are signal-triggered
    assert "build-initial-eth-inventory" in rt.root_action_ids
    assert rt.signal_children["eth-below-1900"] == ["buy-eth-spot-100"]
    assert rt.signal_children["eth-above-2500"] == ["sell-eth-spot-006"]


def test_data_requirements():
    rt = build_runtime(load_graph("graph_05.json"))
    prices, funding = rt.data_requirements()
    assert ("ETH", "hyperliquid") in prices
    assert funding == ["ETH"]


def test_invalid_edge_target_raises():
    g = Graph.model_validate({
        "nodes": [{"id": "a", "kind": "action", "subtype": "swap", "config": {}, "enabled": True}],
        "edges": [{"from": "a", "to": "missing"}],
    })
    with pytest.raises(ValueError):
        build_runtime(g)


def test_all_examples_parse():
    for name in sorted(os.listdir(EXAMPLES_DIR)):
        if name.endswith(".json"):
            build_runtime(load_graph(name))
