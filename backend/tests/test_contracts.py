"""The data shapes and event schema are the contract between backend and frontend."""

import json

import pytest
from pydantic import ValidationError

from pruner.config import get_config
from pruner.events import NodeUpdated, event_adapter, parse_event
from pruner.fixtures import build_fixtures
from pruner.models import (
    Node,
    PreScore,
    RunSnapshot,
    TokenUsage,
    VaultGraph,
    VaultItem,
    VaultItemView,
)


def test_config_defaults_match_prd_caps():
    cfg = get_config()
    assert (cfg.max_depth, cfg.branching, cfg.node_budget) == (4, 3, 25)
    assert 0 <= cfg.similarity_threshold <= 1


def test_vault_item_view_never_contains_embedding():
    item = VaultItem(person="alice", kind="note", title="t", summary="s", embedding=[0.1, 0.2])
    view = item.view()
    assert isinstance(view, VaultItemView)
    assert "embedding" not in view.model_dump()


def test_scores_are_bounded():
    with pytest.raises(ValidationError):
        PreScore(plausible=1.2, relevant=0.5, novel=0.5)


def test_computed_totals_serialize():
    assert PreScore(plausible=0.6, relevant=0.3, novel=0.9).model_dump()["overall"] == 0.6
    assert TokenUsage(agent=10, scorer=5).model_dump()["total"] == 15


def test_node_requires_run_and_type():
    with pytest.raises(ValidationError):
        Node(description="x")  # type: ignore[call-arg]


def test_unknown_event_type_is_rejected():
    with pytest.raises(ValidationError):
        parse_event({"type": "nope", "seq": 1, "run_id": "r"})


def test_fixture_events_parse_and_roundtrip():
    events = build_fixtures()["run_events.json"]
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert [e["ts"] for e in events] == sorted(e["ts"] for e in events)
    for raw in events:
        parsed = parse_event(raw)
        assert json.loads(event_adapter.dump_json(parsed)) == raw


def test_fixture_story_has_the_key_moment():
    parsed = [parse_event(e) for e in build_fixtures()["run_events.json"]]
    updates = [e for e in parsed if isinstance(e, NodeUpdated) and e.node.id == "n_spec"]
    changes = [e.change for e in updates]
    # pruned citing a vault note -> restored by a human -> runs -> done and useful
    assert changes == ["pruned", "restored", "running", "done"]
    assert updates[0].node.decision.vault_items_used == ["v_a2"]
    assert updates[1].node.decided_by == "human"
    assert updates[-1].node.usefulness_count == 1


def test_fixture_event_nodes_reference_known_parents_and_vault_items():
    fx = build_fixtures()
    vault_ids = {i["id"] for i in fx["vault_items.json"]} | {"v_c1"}
    seen_nodes: set[str] = set()
    for raw in fx["run_events.json"]:
        ev = parse_event(raw)
        node = getattr(ev, "node", None)
        if node is not None:
            if ev.type == "node_created":
                assert node.parent_id is None or node.parent_id in seen_nodes
                seen_nodes.add(node.id)
            assert set(node.decision.vault_items_used if node.decision else []) <= vault_ids
        if ev.type == "vault_retrieved":
            assert set(ev.item_ids) <= vault_ids
            assert ev.node_id is None or ev.node_id in seen_nodes


def test_fixture_snapshot_and_graph_validate():
    fx = build_fixtures()
    snap = RunSnapshot.model_validate(fx["run_snapshot.json"])
    ids = {n.id for n in snap.nodes}
    assert all(n.parent_id is None or n.parent_id in ids for n in snap.nodes)
    graph = VaultGraph.model_validate(fx["vault_graph.json"])
    node_ids = {n.id for n in graph.nodes}
    assert all(e.source in node_ids and e.target in node_ids for e in graph.edges)
