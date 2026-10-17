"""Fake-but-valid data so the frontend can be built before the backend exists.

All content is PLACEHOLDER (titles are prefixed "[fixture]"); it is not the demo corpus.
The fixtures are built from the real pydantic models, so they cannot drift from the contract.

Regenerate with:  cd backend && uv run python -m pruner.fixtures
tests/test_fixtures.py fails if the committed JSON differs from what this module produces.

The story mirrors the demo's key moment: the agent parks a branch citing the user's own
vault note, the user restores it, and the agent finds something useful there.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pruner.core.config import REPO_ROOT
from pruner.core.events import (
    Activity,
    Event,
    NodeCreated,
    NodeUpdated,
    ObjectivesUpdated,
    QuestionAsked,
    RunCompleted,
    RunStarted,
    VaultItemAdded,
    VaultRetrieved,
)
from pruner.core.models import (
    Caps,
    DeadEnd,
    Decision,
    Instruction,
    Node,
    Objective,
    PersonScore,
    PreScore,
    Question,
    Run,
    RunSnapshot,
    RunTotals,
    TokenUsage,
    VaultEdge,
    VaultGraph,
    VaultItemView,
)

FIXTURES_DIR = REPO_ROOT / "frontend" / "src" / "fixtures"

T0 = 1_760_000_000.0
RUN_ID = "r_fixture"
QUESTION = "Which techniques reduce the inference cost of long-context LLMs? (placeholder question)"


def _vault_items() -> list[VaultItemView]:
    def item(id: str, person: str, kind: str, title: str, summary: str, tags: list[str],
             retrievals: int, t: float) -> VaultItemView:
        return VaultItemView(
            id=id, person=person, kind=kind, title=title, summary=summary, tags=tags,  # type: ignore[arg-type]
            source_text=f"{summary} (full source text placeholder)",
            retrieval_count=retrievals, created_at=T0 - 86_400 + t,
        )

    return [
        item("v_a1", "alice", "paper", "[fixture] KV-cache compression survey",
             "Surveys eviction, quantization and merging methods for the KV cache.",
             ["kv-cache", "compression", "long-context"], 3, 0),
        item("v_a2", "alice", "note", "[fixture] Speculative decoding is well understood",
             "My notes: the speculative decoding history and speedups are already covered; skip.",
             ["speculative-decoding", "latency"], 2, 60),
        item("v_a3", "alice", "question", "[fixture] Does KV quantization hurt recall?",
             "Open question: how much long-context recall is lost under 4-bit KV quantization.",
             ["kv-cache", "quantization", "long-context"], 1, 120),
        item("v_b1", "bob", "paper", "[fixture] Cognitive load in agent interfaces",
             "Studies how much intermediate agent output users can follow before overload.",
             ["hci", "agents", "cognitive-load"], 0, 30),
        item("v_b2", "bob", "note", "[fixture] Latency framing matters to end users",
             "My notes: users judge speculative decoding by perceived latency, not throughput.",
             ["speculative-decoding", "latency", "hci"], 1, 90),
        item("v_b3", "bob", "paper", "[fixture] Prompt compression for documents",
             "Evaluates prompt compression on long documents; quality drops on reasoning tasks.",
             ["prompt-compression", "long-context"], 0, 150),
    ]


def _vault_graph(items: list[VaultItemView]) -> VaultGraph:
    def edge(source: str, target: str, weight: float, relation: str, reason: str) -> VaultEdge:
        return VaultEdge(source=source, target=target, weight=weight,
                         relation=relation, reason=reason)  # type: ignore[arg-type]

    edges = [
        edge("v_a3", "v_a1", 0.83, "investigate",
             "The survey covers KV quantization; worth reading to answer the recall question."),
        edge("v_b2", "v_a2", 0.79, "contradicts",
             "Bob says latency framing still matters; Alice's note says the topic is settled."),
        edge("v_b2", "v_b1", 0.58, "agrees",
             "Both say users judge agents by what they perceive, not raw throughput."),
        edge("v_b3", "v_a1", 0.61, "supports",
             "Prompt compression results add evidence on accuracy cost of shrinking context."),
    ]
    return VaultGraph(nodes=items, edges=edges)


class _Emitter:
    def __init__(self) -> None:
        self.events: list[Event] = []

    def emit(self, cls: Any, dt: float, **kw: Any) -> None:
        self.events.append(cls(seq=len(self.events) + 1, run_id=RUN_ID, ts=T0 + dt, **kw))


def _build() -> dict[str, Any]:
    items = _vault_items()
    objectives = [
        Objective(id="o1", text="Names the main families of KV-cache reduction techniques"),
        Objective(id="o2", text="States the accuracy cost of each family"),
        Objective(id="o3", text="Addresses effect on long-context recall"),
        Objective(id="o4", text="Addresses end-user latency, not just throughput"),
    ]
    caps = Caps(max_depth=4, branching=3, node_budget=25)
    spec = Instruction(id="i_spec", kind="spec", created_at=T0,
                       text="Focus on methods that need no retraining. [fixture spec]")
    run = Run(
        id=RUN_ID, question=QUESTION, objectives=[], instructions=[spec], people=["alice", "bob"],
        primary_person="alice", vault_people=["alice"], mode="pruned", status="running",
        caps=caps, created_at=T0,
    )

    def node(id: str, parent: str | None, depth: int, type: str, description: str,
             t: float, **kw: Any) -> Node:
        return Node(id=id, run_id=RUN_ID, parent_id=parent, depth=depth,
                    type=type, description=description, created_at=T0 + t, **kw)  # type: ignore[arg-type]

    root = node("n_root", None, 0, "hypothesis", QUESTION, 1, status="done", decided_by="agent")

    kv = node("n_kv", "n_root", 1, "reading", "Survey KV-cache compression methods", 4,
              pre_score=PreScore(plausible=0.9, relevant=0.9, novel=0.7))
    quant = node("n_quant", "n_root", 1, "hypothesis",
                 "KV quantization preserves long-context recall", 4,
                 pre_score=PreScore(plausible=0.7, relevant=0.8, novel=0.8))
    spec = node("n_spec", "n_root", 1, "reading",
                "Review the history of speculative decoding", 4,
                pre_score=PreScore(plausible=0.6, relevant=0.4, novel=0.1))
    prompt = node("n_prompt", "n_kv", 2, "experiment",
                  "Test prompt compression on long documents", 14,
                  pre_score=PreScore(plausible=0.6, relevant=0.6, novel=0.6))

    ev = _Emitter()
    ev.emit(RunStarted, 0, run=run)
    ev.emit(NodeCreated, 1, node=root)
    ev.emit(ObjectivesUpdated, 2, objectives=objectives)
    run = run.model_copy(update={"objectives": objectives})
    ev.emit(Activity, 3, message="Planning: wrote a 4-item objectives for the question.")

    # Three candidates proposed; two pass pre-scoring, one is parked citing alice's own note.
    for n in (kv, quant, spec):
        ev.emit(NodeCreated, 4, node=n)
    ev.emit(VaultRetrieved, 5, node_id="n_spec", person="alice",
            query="history of speculative decoding", item_ids=["v_a2"], similarities=[0.81])
    spec_decision = Decision(
        verdict="park", stage="pre", vault_items_used=["v_a2"],
        reason="Your note 'Speculative decoding is well understood' already covers this.")
    spec = spec.model_copy(deep=True, update={
        "status": "parked", "decision": spec_decision, "decided_by": "agent",
        "tokens": TokenUsage(agent=0, scorer=410),
        "person_scores": {
            "alice": PersonScore(person="alice", verdict="park", score=0.37,
                                 reason="Already covered by your own note.",
                                 vault_items_used=["v_a2"]),
            "bob": PersonScore(person="bob", verdict="keep", score=0.78,
                               reason="Bob's note says latency framing matters to end users.",
                               vault_items_used=["v_b2"]),
        },
    })
    ev.emit(NodeUpdated, 5, node=spec, change="parked")
    ev.emit(Activity, 6, node_id="n_spec",
            message="Parked 'speculative decoding history': you already have a note on it.")

    # Run the two survivors.
    kv = kv.model_copy(deep=True, update={"status": "running"})
    ev.emit(NodeUpdated, 7, node=kv, change="running")
    ev.emit(VaultRetrieved, 8, node_id="n_kv", person="alice",
            query="KV-cache compression", item_ids=["v_a1", "v_a3"], similarities=[0.88, 0.74])
    kv = kv.model_copy(deep=True, update={
        "status": "done", "post_score": 0.82, "criteria_progress": ["o1", "o2"],
        "result": "Three families: eviction, quantization, merging. Accuracy cost varies.",
        "decision": Decision(verdict="keep", stage="post", vault_items_used=["v_a1"],
                             reason="Advances the technique-families and accuracy-cost objectives."),
        "decided_by": "agent", "tokens": TokenUsage(agent=1800, scorer=520),
    })
    ev.emit(NodeUpdated, 10, node=kv, change="done")
    quant = quant.model_copy(deep=True, update={
        "status": "done", "post_score": 0.66, "criteria_progress": ["o3"],
        "result": "Recall holds at 8-bit; degrades on retrieval-heavy prompts at 4-bit.",
        "decision": Decision(verdict="keep", stage="post", vault_items_used=["v_a3"],
                             reason="Advances the long-context recall objective."),
        "decided_by": "agent", "tokens": TokenUsage(agent=1500, scorer=480),
    })
    ev.emit(NodeUpdated, 12, node=quant, change="done")

    # A child that advances nothing is parked after running.
    ev.emit(NodeCreated, 14, node=prompt)
    prompt = prompt.model_copy(deep=True, update={
        "status": "parked", "post_score": 0.2, "criteria_progress": [],
        "result": "Compression helps cost but says nothing about the objectives items.",
        "decision": Decision(verdict="park", stage="post", vault_items_used=[],
                             reason="Advances none of the four objectives."),
        "decided_by": "agent", "tokens": TokenUsage(agent=1400, scorer=450),
    })
    ev.emit(NodeUpdated, 18, node=prompt, change="parked")
    ev.emit(Activity, 18, node_id="n_prompt",
            message="Parked 'prompt compression test': it advanced no objectives item.")

    # Human restores the parked branch; the agent finds something useful there.
    spec = spec.model_copy(deep=True, update={
        "status": "pending", "decided_by": "human",
        "decision": Decision(verdict="keep", stage="human", vault_items_used=["v_b2"],
                             reason="Restored by alice: latency framing is worth checking."),
    })
    ev.emit(NodeUpdated, 30, node=spec, change="restored")
    correction = VaultItemView(
        id="v_c1", person="alice", kind="correction",
        title="[fixture] Correction: latency framing is worth a look",
        summary="I restored a parked speculative-decoding branch; the latency angle was new.",
        tags=["speculative-decoding", "latency"], retrieval_count=0, created_at=T0 + 31,
        source_text="Human override: restore n_spec.")
    ev.emit(VaultItemAdded, 31, item=correction, edges=[
        VaultEdge(source="v_c1", target="v_a2", weight=0.81, relation="contradicts",
                  reason="The restored branch was useful, so the topic was not fully covered."),
        VaultEdge(source="v_c1", target="v_b2", weight=0.77, relation="agrees",
                  reason="Both conclude the end-user latency angle is worth keeping."),
    ])
    ev.emit(Activity, 31, message="Added your correction to your vault.")
    spec = spec.model_copy(deep=True, update={"status": "running"})
    ev.emit(NodeUpdated, 32, node=spec, change="running")
    spec = spec.model_copy(deep=True, update={
        "status": "done", "post_score": 0.74, "criteria_progress": ["o4"],
        "result": "Speculative decoding cuts perceived latency, which matters most to end users.",
        "usefulness_count": 1, "tokens": TokenUsage(agent=1600, scorer=410 + 470),
    })
    ev.emit(NodeUpdated, 40, node=spec, change="done")
    ev.emit(Activity, 40, node_id="n_spec",
            message="Restored branch advanced the end-user latency objective.")

    question = Question(
        id="q_fixture", run_id=RUN_ID, node_id="n_spec", person="bob", created_at=T0 + 41,
        text="Alice parked this and then restored it. Is the latency framing worth including?")
    ev.emit(QuestionAsked, 41, question=question)

    nodes = [root, kv, quant, spec, prompt]
    final = run.model_copy(deep=True, update={
        "status": "done",
        "final_answer": "Placeholder final answer synthesized from kept branches.",
        "totals": RunTotals(
            tokens=TokenUsage(agent=6300, scorer=2330), nodes_total=len(nodes),
            nodes_parked=1, nodes_restored=1, elapsed_s=94.2),
    })
    ev.emit(RunCompleted, 94, run=final)

    snapshot = RunSnapshot(
        run=final, nodes=nodes, questions=[question],
        dead_ends=[DeadEnd(id="d_fixture", run_id=RUN_ID, node_id="n_prompt",
                           description=prompt.description, reason=prompt.decision.reason)],  # type: ignore[union-attr]
    )
    return {
        "vault_items.json": [i.model_dump(mode="json") for i in items],
        "vault_graph.json": _vault_graph(items).model_dump(mode="json"),
        "run_events.json": [e.model_dump(mode="json") for e in ev.events],
        "run_snapshot.json": snapshot.model_dump(mode="json"),
    }


def build_fixtures() -> dict[str, Any]:
    """Filename -> JSON-serializable content."""
    return _build()


def write_fixtures(directory: Path = FIXTURES_DIR) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for name, content in build_fixtures().items():
        path = directory / name
        path.write_text(json.dumps(content, indent=2) + "\n")
        written.append(path)
    return written


if __name__ == "__main__":
    for p in write_fixtures():
        print(f"wrote {p.relative_to(REPO_ROOT)}")
