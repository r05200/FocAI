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

from pydantic import BaseModel, Field, computed_field, field_validator

# "directive" is in the palette so every client shares one set of kinds (the frontend colors by it),
# but directives are not vault items: they have their own class and routes (see Directive), and
# IngestRequest rejects this kind.
VaultKind = Literal["paper", "note", "question", "correction", "learned", "directive"]
# How a newly ingested item relates to one of its nearest neighbors, as judged by the vault LLM.
# supports = gives evidence for the other's claim; agrees = reaches the same view independently;
# contradicts = the claims conflict; investigate = one side is a question the user wants answered
# and the other is material relevant to it that does not settle it yet. The LLM may also answer
# "unrelated" (similar wording or topic, no bearing); such pairs are not stored as edges, so
# VaultEdge.relation never has that value.
VaultRelation = Literal["contradicts", "supports", "agrees", "investigate"]
VaultJudgement = Literal["contradicts", "supports", "agrees", "investigate", "unrelated"]
PERSON_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,31}$"  # also a filename; no leading "_" (reserved files)
NodeType = Literal["hypothesis", "experiment", "reading"]
# pending = proposed and passed pre-scoring, waiting to run; parked covers both pre- and
# post-scoring parks (see Decision.stage).
NodeStatus = Literal["pending", "running", "done", "parked", "failed"]
Verdict = Literal["keep", "park"]
DecisionStage = Literal["pre", "post", "human"]
Decider = Literal["agent", "human"]
RunMode = Literal["pruned", "unpruned"]
RunStatus = Literal["running", "done", "failed"]
# spec = the research specs the user gives at the start; steer = a later instruction that
# is appended to it. All of them are shown to the agent and the scorers, oldest first.
InstructionKind = Literal["spec", "steer"]


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
    # Something to look into ("investigate this", "look into", "maybe this could help"), as
    # judged by the ingest LLM. Questions count too, whatever this says.
    investigate: bool = False
    retrieval_count: int = 0
    created_at: float = Field(default_factory=time.time)


class VaultItem(VaultItemView):
    embedding: list[float] | None = None

    def view(self) -> VaultItemView:
        return VaultItemView.model_validate(self.model_dump(exclude={"embedding"}))


class VaultEdge(BaseModel):
    """Undirected link created at ingest time: source is the newer item, target the older one."""

    source: str
    target: str
    weight: float  # cosine similarity of the two embeddings
    relation: VaultRelation
    reason: str  # one line, written by the vault LLM


class VaultGraph(BaseModel):
    nodes: list[VaultItemView]
    edges: list[VaultEdge]


# --------------------------------------------------------------------------- scoring


class Objective(BaseModel):
    """One point-form goal of the research. Written by an LLM from the spec when the run
    starts; every later instruction can append more (nothing is ever rewritten or removed)."""

    id: str  # "o1", "o2", ...
    text: str
    source: str = "spec"  # "spec", or the id of the instruction that added it


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
    criteria_progress: list[str] = Field(default_factory=list)  # ids of the objectives advanced
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
    nodes_parked: int = 0
    nodes_restored: int = 0
    elapsed_s: float = 0.0


class Instruction(BaseModel):
    """A prompt typed in the frontend: first the research spec, then steering that builds on it."""

    id: str = Field(default_factory=lambda: new_id("i"))
    kind: InstructionKind
    text: str
    created_at: float = Field(default_factory=time.time)


class Run(BaseModel):
    id: str = Field(default_factory=lambda: new_id("r"))
    question: str
    objectives: list[Objective] = Field(default_factory=list)
    instructions: list[Instruction] = Field(default_factory=list)  # spec first, then steering
    # The directive texts the frontend last sent for this run, appended to every prompt.
    directives: list[str] = Field(default_factory=list)
    people: list[str]
    primary_person: str  # whose vault drives pruning
    vault_people: list[str] = Field(default_factory=list)  # whose vaults the scorers search
    mode: RunMode = "pruned"
    status: RunStatus = "running"
    caps: Caps
    final_answer: str | None = None
    totals: RunTotals = Field(default_factory=RunTotals)
    created_at: float = Field(default_factory=time.time)


class DeadEnd(BaseModel):
    """A short note about a parked or failed branch, injected into later prompts."""

    id: str = Field(default_factory=lambda: new_id("d"))
    run_id: str
    node_id: str
    description: str
    reason: str


class Directive(BaseModel):
    """A standing instruction a person files under the vault's Directives tab (for example
    "prefer optimizer changes"). Not a vault item: no embedding, no links, no LLM ranking.
    It is stored separately and handed to the agent and scorers as-is."""

    id: str = Field(default_factory=lambda: new_id("dir"))
    person: str
    text: str
    created_at: float = Field(default_factory=time.time)


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
    spec: str = ""  # the research specs; stored as the run's first instruction (kind "spec")
    mode: RunMode = "pruned"
    primary_person: str
    people: list[str] | None = None  # defaults to [primary_person]
    # Whose vaults the pre- and post-scorers search, e.g. just you, or you plus a teammate.
    # Defaults to [primary_person]; an empty list scores with no vault at all.
    vault_people: list[str] | None = None
    # The person's active directives (their texts), sent along with the spec. They are appended
    # to the prompts as-is.
    directives: list[str] = Field(default_factory=list)


class InstructionRequest(BaseModel):
    """Further instructions typed mid-run; appended to the spec and sent to the agent."""

    text: str = Field(min_length=1)
    # The current list of active directives, replacing the run's previous list. Omit to keep it.
    directives: list[str] | None = None


class IngestRequest(BaseModel):
    person: str = Field(pattern=PERSON_PATTERN)
    kind: VaultKind = "note"
    text: str = Field(min_length=1)
    title: str | None = None  # optional override; otherwise the ingest LLM writes one

    @field_validator("kind")
    @classmethod
    def _not_a_directive(cls, kind: str) -> str:
        if kind == "directive":
            raise ValueError("directives are not vault items; use POST /api/vault/directives")
        return kind


class CreateVaultRequest(BaseModel):
    person: str = Field(pattern=PERSON_PATTERN)


class VaultSummary(BaseModel):
    person: str
    item_count: int


class DirectiveRequest(BaseModel):
    person: str = Field(pattern=PERSON_PATTERN)
    text: str = Field(min_length=1)


class IngestResult(BaseModel):
    item: VaultItemView
    edges: list[VaultEdge]  # links to the new item's nearest neighbors, with relations


class AnswerRequest(BaseModel):
    answer: str
