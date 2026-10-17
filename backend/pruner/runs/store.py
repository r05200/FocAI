"""Historical runs, saved to disk so they survive restarts and can be reopened or replayed.

Layout under cfg.runs_dir (git-ignored):
  <run_id>/events.jsonl   every event, appended as it is emitted (durable even if the run dies)
  <run_id>/snapshot.json  the full RunSnapshot, rewritten atomically by save_snapshot()
  <run_id>/forks.jsonl    fork requests from the amend agent, appended (forking is not built)

If a run was cut off before a snapshot was saved, snapshot() rebuilds one from its events
(nodes, questions and objectives; dead ends are only in saved snapshots).
"""

from __future__ import annotations

import re
from pathlib import Path

from pruner.core.config import Config, get_config
from pruner.core.events import (
    Event,
    NodeCreated,
    NodeUpdated,
    ObjectivesUpdated,
    QuestionAnswered,
    QuestionAsked,
    RunCompleted,
    RunFailed,
    RunStarted,
    parse_event,
)
from pruner.core.models import ForkRequest, Node, Question, Run, RunSnapshot

STOPPED_BY_USER = "Stopped by the user"
EVENTS_FILE = "events.jsonl"
FORKS_FILE = "forks.jsonl"
SNAPSHOT_FILE = "snapshot.json"
_RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")  # run ids become directory names


def rebuild_snapshot(events: list[Event]) -> RunSnapshot | None:
    """Fold a run's events into its latest state. None if the run never started."""
    run: Run | None = None
    nodes: dict[str, Node] = {}
    questions: dict[str, Question] = {}
    for e in events:
        if isinstance(e, (RunStarted, RunCompleted)):
            run = e.run
        elif isinstance(e, ObjectivesUpdated) and run is not None:
            run = run.model_copy(update={"objectives": e.objectives})
        elif isinstance(e, (NodeCreated, NodeUpdated)):
            nodes[e.node.id] = e.node
        elif isinstance(e, (QuestionAsked, QuestionAnswered)):
            questions[e.question.id] = e.question
    if run is None:
        return None
    return RunSnapshot(run=run, nodes=list(nodes.values()), questions=list(questions.values()))


class RunStore:
    def __init__(self, directory: Path | None = None, cfg: Config | None = None) -> None:
        self.dir = directory or (cfg or get_config()).runs_dir

    def _run_dir(self, run_id: str) -> Path | None:
        return self.dir / run_id if _RUN_ID.match(run_id) else None

    # ---- writes

    def append_event(self, event: Event) -> None:
        path = self.dir / event.run_id / EVENTS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(event.model_dump_json() + "\n")

    def save_snapshot(self, snapshot: RunSnapshot) -> None:
        path = self.dir / snapshot.run.id / SNAPSHOT_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(snapshot.model_dump_json(indent=1))
        tmp.replace(path)

    def append_fork(self, fork: ForkRequest) -> None:
        path = self.dir / fork.run_id / FORKS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(fork.model_dump_json() + "\n")

    def forks(self, run_id: str) -> list[ForkRequest]:
        d = self._run_dir(run_id)
        path = d / FORKS_FILE if d else None
        if path is None or not path.exists():
            return []
        return [ForkRequest.model_validate_json(line)
                for line in path.read_text().splitlines() if line.strip()]

    def last_seq(self, run_id: str) -> int:
        return max((e.seq for e in self.events(run_id)), default=0)

    def mark_stopped(self, run_id: str) -> RunFailed:
        """End a run the user stopped: append the final run_failed event ("Stopped by the user")
        and save the snapshot with status "failed". Raises KeyError for an unknown run."""
        snapshot = self.snapshot(run_id)
        if snapshot is None:
            raise KeyError(run_id)
        events = self.events(run_id)
        event = RunFailed(seq=max((e.seq for e in events), default=-1) + 1, run_id=run_id,
                          error=STOPPED_BY_USER)
        self.append_event(event)
        run = snapshot.run.model_copy(update={"status": "failed"})
        self.save_snapshot(snapshot.model_copy(update={"run": run}))
        return event

    # ---- reads

    def events(self, run_id: str, after: int = 0) -> list[Event]:
        """The run's saved events with seq greater than `after`, in order."""
        d = self._run_dir(run_id)
        path = d / EVENTS_FILE if d else None
        if path is None or not path.exists():
            return []
        events = [parse_event(line) for line in path.read_text().splitlines() if line.strip()]
        return [e for e in events if e.seq > after]

    def snapshot(self, run_id: str) -> RunSnapshot | None:
        d = self._run_dir(run_id)
        if d is None:
            return None
        saved = d / SNAPSHOT_FILE
        if saved.exists():
            return RunSnapshot.model_validate_json(saved.read_text())
        return rebuild_snapshot(self.events(run_id))

    def list(self) -> list[Run]:
        """Every saved run, newest first."""
        if not self.dir.exists():
            return []
        runs = [s.run for p in self.dir.iterdir() if p.is_dir()
                if (s := self.snapshot(p.name)) is not None]
        return sorted(runs, key=lambda r: r.created_at, reverse=True)
