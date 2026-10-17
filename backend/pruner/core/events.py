"""Server-sent event schema for one run.

Every event carries the full object it concerns (a node snapshot, not a diff), so the
frontend reducer is "replace by id" and replay is just re-sending saved events.
The SSE `event:` name is the `type` field; `data:` is the event as JSON.
"""

from __future__ import annotations

import time
from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter

from pruner.core.models import (
    Finding,
    Instruction,
    LogEntry,
    Node,
    Objective,
    Question,
    Run,
    RunIdea,
    VaultEdge,
    VaultItemView,
)


class EventBase(BaseModel):
    seq: int  # strictly increasing per run; lets the client detect gaps and resume
    run_id: str
    ts: float = Field(default_factory=time.time)


class RunStarted(EventBase):
    type: Literal["run_started"] = "run_started"
    run: Run


class ObjectivesUpdated(EventBase):
    """The run's objectives, in full: sent when they are first written and again whenever an
    instruction appends more."""

    type: Literal["objectives_updated"] = "objectives_updated"
    objectives: list[Objective]


class NodeCreated(EventBase):
    type: Literal["node_created"] = "node_created"
    node: Node


NodeChange = Literal["running", "scored", "done", "parked", "kept", "restored", "failed"]


class NodeUpdated(EventBase):
    type: Literal["node_updated"] = "node_updated"
    node: Node
    change: NodeChange  # what happened, so the UI can animate it; node holds the new state


class InstructionAdded(EventBase):
    """The user appended an instruction; it applies to everything the agent does from now on."""

    type: Literal["instruction_added"] = "instruction_added"
    instruction: Instruction


class VaultRetrieved(EventBase):
    """The agent or scorer searched the vault. Drives the pulse in both tabs."""

    type: Literal["vault_retrieved"] = "vault_retrieved"
    node_id: str | None
    person: str
    query: str
    item_ids: list[str]  # empty when nothing was close enough
    similarities: list[float]


class VaultItemAdded(EventBase):
    """An ingest, a human correction, or a 'learned this run' write-back."""

    type: Literal["vault_item_added"] = "vault_item_added"
    item: VaultItemView
    edges: list[VaultEdge]


class Activity(EventBase):
    """One plain-language line for the activity feed."""

    type: Literal["activity"] = "activity"
    message: str
    node_id: str | None = None


class QuestionAsked(EventBase):
    type: Literal["question_asked"] = "question_asked"
    question: Question


class QuestionAnswered(EventBase):
    type: Literal["question_answered"] = "question_answered"
    question: Question


class RunUpdated(EventBase):
    """Run-level state changed outside the other events (e.g. it now waits for an answer, or its
    workspace or command was set). Carries the whole run."""

    type: Literal["run_updated"] = "run_updated"
    run: Run


class NodeLog(EventBase):
    """One line was added to a node's log (GET /runs/{id}/nodes/{node_id}/logs has them all)."""

    type: Literal["node_log"] = "node_log"
    node_id: str
    entry: LogEntry


class FindingAdded(EventBase):
    type: Literal["finding_added"] = "finding_added"
    finding: Finding


class IdeaAdded(EventBase):
    """An entry was added to the run vault (GET /runs/{id}/vault)."""

    type: Literal["idea_added"] = "idea_added"
    idea: RunIdea


class RunCompleted(EventBase):
    type: Literal["run_completed"] = "run_completed"
    run: Run  # final totals and final_answer


class RunFailed(EventBase):
    type: Literal["run_failed"] = "run_failed"
    error: str


Event = Annotated[
    RunStarted
    | ObjectivesUpdated
    | NodeCreated
    | NodeUpdated
    | InstructionAdded
    | VaultRetrieved
    | VaultItemAdded
    | Activity
    | QuestionAsked
    | QuestionAnswered
    | RunUpdated
    | NodeLog
    | FindingAdded
    | IdeaAdded
    | RunCompleted
    | RunFailed,
    Field(discriminator="type"),
]

event_adapter: TypeAdapter[Event] = TypeAdapter(Event)


def parse_event(data: dict | str | bytes) -> Event:
    if isinstance(data, dict):
        return event_adapter.validate_python(data)
    return event_adapter.validate_json(data)
