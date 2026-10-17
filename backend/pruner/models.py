"""Shared data shapes. The frontend mirrors these in frontend/src/types.ts.

Rules of thumb:
- Timestamps are epoch seconds (float) so they are trivial in JSON and TypeScript.
- Scores are 0..1 floats.
- Embeddings never leave the backend: the API only ever sends VaultItemView.
"""

from __future__ import annotations

import time
import uuid
from typing import Literal

from pydantic import BaseModel, Field, computed_field

VaultKind = Literal["paper", "note", "question", "correction", "learned"]
NodeType = Literal["hypothesis", "experiment", "reading"]
# pending = proposed and passed pre-scoring, waiting to run; pruned covers both pre- and
# post-scoring prunes (see Decision.stage).
NodeStatus = Literal["pending", "running", "done", "pruned", "failed"]
Verdict = Literal["keep", "prune"]
DecisionStage = Literal["pre", "post", "human"]
Decider = Literal["agent", "human"]
RunMode = Literal["pruned", "unpruned"]
RunStatus = Literal["running", "done", "failed"]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# --------------------------------------------------------------------------- vault


class VaultItemView(BaseModel):
    """Everything about a vault item except the embedding (safe to send to the UI)."""

    id: str = Field(default_factory=lambda: new_id("v"))
    person: str
    kind: VaultKind
    title: str
    summary: str
    tags: list[str] = Field(default_factory=list)
    source_text: str = ""
    retrieval_count: int = 0
    created_at: float = Field(default_factory=time.time)


class VaultItem(VaultItemView):
    embedding: list[float] | None = None

    def view(self) -> VaultItemView:
        return VaultItemView.model_validate(self.model_dump(exclude={"embedding"}))


class VaultEdge(BaseModel):
    source: str
    target: str
    weight: float  # cosine similarity


class VaultGraph(BaseModel):
    nodes: list[VaultItemView]
    edges: list[VaultEdge]


# --------------------------------------------------------------------------- scoring


class Criterion(BaseModel):
    id: str  # "c1", "c2", ...
    text: str


class PreScore(BaseModel):
    plausible: float = Field(ge=0, le=1)
    relevant: float = Field(ge=0, le=1)
    novel: float = Field(ge=0, le=1)  # new to this person, judged against their vault

    @computed_field  # type: ignore[prop-decorator]
    @property
    def overall(self) -> float:
        return round((self.plausible + self.relevant + self.novel) / 3, 4)


class Decision(BaseModel):
    """Why a node was kept or pruned, in one sentence, and which vault items it relied on."""

    verdict: Verdict
    stage: DecisionStage
    reason: str
    vault_items_used: list[str] = Field(default_factory=list)


class PersonScore(BaseModel):
    """P1: how one person's vault would judge the same node."""

    person: str
    verdict: Verdict
    score: float = Field(ge=0, le=1)
    reason: str
    vault_items_used: list[str] = Field(default_factory=list)


class TokenUsage(BaseModel):
    agent: int = 0  # planning, proposing, running steps, synthesis
    scorer: int = 0  # pre/post scoring (counted against the pruned run's savings)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total(self) -> int:
        return self.agent + self.scorer


# --------------------------------------------------------------------------- tree


class Node(BaseModel):
    id: str = Field(default_factory=lambda: new_id("n"))
    run_id: str
    parent_id: str | None = None  # None only for the root
    depth: int = 0
    type: NodeType
    description: str
    status: NodeStatus = "pending"
    pre_score: PreScore | None = None
    post_score: float | None = Field(default=None, ge=0, le=1)
    decision: Decision | None = None
    decided_by: Decider | None = None
    result: str | None = None  # what running the node produced
    criteria_progress: list[str] = Field(default_factory=list)  # criterion ids advanced
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    usefulness_count: int = 0  # times a later node or the final answer used this one
    person_scores: dict[str, PersonScore] = Field(default_factory=dict)  # P1
    created_at: float = Field(default_factory=time.time)


class Caps(BaseModel):
    max_depth: int
    branching: int
    node_budget: int


class RunTotals(BaseModel):
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    nodes_total: int = 0
    nodes_pruned: int = 0
    nodes_restored: int = 0
    elapsed_s: float = 0.0


class Run(BaseModel):
    id: str = Field(default_factory=lambda: new_id("r"))
    question: str
    checklist: list[Criterion] = Field(default_factory=list)
    people: list[str]
    primary_person: str  # whose vault drives pruning
    mode: RunMode = "pruned"
    status: RunStatus = "running"
    caps: Caps
    final_answer: str | None = None
    totals: RunTotals = Field(default_factory=RunTotals)
    created_at: float = Field(default_factory=time.time)


class DeadEnd(BaseModel):
    """A short note about a pruned or failed branch, injected into later prompts."""

    id: str = Field(default_factory=lambda: new_id("d"))
    run_id: str
    node_id: str
    description: str
    reason: str


class Question(BaseModel):
    """P1: a targeted question routed to a specific person."""

    id: str = Field(default_factory=lambda: new_id("q"))
    run_id: str
    node_id: str
    person: str
    text: str
    status: Literal["pending", "answered"] = "pending"
    answer: str | None = None
    created_at: float = Field(default_factory=time.time)


class RunSnapshot(BaseModel):
    """Full state of a run, for page reloads and replay. Live changes arrive as events."""

    run: Run
    nodes: list[Node]
    dead_ends: list[DeadEnd] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)


# --------------------------------------------------------------------------- API requests


class StartRunRequest(BaseModel):
    question: str
    mode: RunMode = "pruned"
    primary_person: str
    people: list[str] | None = None  # defaults to [primary_person]


class IngestRequest(BaseModel):
    person: str
    kind: VaultKind = "note"
    text: str
    title: str | None = None  # optional override; otherwise the ingest LLM writes one


class AnswerRequest(BaseModel):
    answer: str
