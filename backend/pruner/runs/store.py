"""Historical runs, saved to disk so they survive restarts and can be reopened or replayed.

Layout under cfg.runs_dir (git-ignored):
  <run_id>/events.jsonl   every event, appended as it is emitted (durable even if the run dies)
  <run_id>/snapshot.json  the full RunSnapshot, rewritten atomically by save_snapshot()
  <run_id>/forks.jsonl    fork requests from the amend agent (rewritten as their status changes)
  <run_id>/fork_snapshots/<fork_id>.json  the tree just before a fork was confirmed (undo)
  <run_id>/findings.jsonl the run's shared findings log (orchestrator lines and agent ones)
  <run_id>/vault.json     the run vault: ideas and whole-branch findings (write_findings_vault)
  <run_id>/logs/<node>.jsonl  a node's log: tool calls with their reasons, results, decisions
  <run_id>/final.patch    the changes left applied to the user's files, from the originals
  <run_id>/level_start.json  the tree as it was when the current level was created (rewritten
                          whenever a level is created or completed); a reload of an unfinished
                          run goes back to it, so the nodes of the level in progress recover their
                          original state

If a run was cut off before a snapshot was saved, snapshot() rebuilds one from its events
(nodes, questions and objectives; dead ends are only in saved snapshots).
"""

from __future__ import annotations

import re
from pathlib import Path

from pruner.core.config import Config, get_config
from pruner.core.events import (
    Event,
    FindingAdded,
    NodeCreated,
    NodeRemoved,
    NodeUpdated,
    ObjectivesUpdated,
    QuestionAnswered,
    QuestionAsked,
    RunCompleted,
    RunFailed,
    RunStarted,
    RunUpdated,
    SuggestionResolved,
    SuggestionsReady,
    parse_event,
)
from pruner.core.fs import write_atomic
from pruner.core.models import (
    Finding,
    ForkRequest,
    LogEntry,
    Node,
    Question,
    Run,
    RunSnapshot,
    RunVault,
    Suggestion,
)

STOPPED_BY_USER = "Stopped by the user"
EVENTS_FILE = "events.jsonl"
FORKS_FILE = "forks.jsonl"
SNAPSHOT_FILE = "snapshot.json"
LEVEL_START_FILE = "level_start.json"
FINDINGS_FILE = "findings.jsonl"
RUN_VAULT_FILE = "vault.json"
LOGS_DIR = "logs"
PATCH_FILE = "final.patch"
FORK_SNAPSHOTS_DIR = "fork_snapshots"  # the tree before each confirmed fork (for undo)
_NODE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")  # node ids become log file names
_RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")  # run ids become directory names


def rebuild_snapshot(events: list[Event]) -> RunSnapshot | None:
    """Fold a run's events into its latest state. None if the run never started."""
    run: Run | None = None
    nodes: dict[str, Node] = {}
    questions: dict[str, Question] = {}
    findings: list[Finding] = []
    suggestions: dict[str, Suggestion] = {}
    for e in events:
        if isinstance(e, (RunStarted, RunCompleted, RunUpdated)):
            run = e.run
        elif isinstance(e, FindingAdded):
            findings.append(e.finding)
        elif isinstance(e, SuggestionsReady):
            for sid in e.replaced:
                if sid in suggestions:
                    suggestions[sid] = suggestions[sid].model_copy(update={"status": "replaced"})
            suggestions.update({s.id: s for s in e.suggestions})
        elif isinstance(e, SuggestionResolved):
            suggestions[e.suggestion.id] = e.suggestion
        elif isinstance(e, ObjectivesUpdated) and run is not None:
            run = run.model_copy(update={"objectives": e.objectives})
        elif isinstance(e, (NodeCreated, NodeUpdated)):
            nodes[e.node.id] = e.node
        elif isinstance(e, NodeRemoved):
            nodes.pop(e.node_id, None)
        elif isinstance(e, (QuestionAsked, QuestionAnswered)):
            questions[e.question.id] = e.question
    if run is None:
        return None
    return RunSnapshot(run=run, nodes=list(nodes.values()), questions=list(questions.values()),
                       findings=findings, suggestions=list(suggestions.values()))


class RunStore:
    def __init__(self, directory: Path | None = None, cfg: Config | None = None) -> None:
        self.dir = directory or (cfg or get_config()).runs_dir

    def _file(self, run_id: str, name: str) -> Path | None:
        """A file in the run's folder, or None if `run_id` is not a safe folder name."""
        return self.dir / run_id / name if _RUN_ID.match(run_id) else None

    def _lines(self, run_id: str, name: str) -> list[str]:
        path = self._file(run_id, name)
        if path is None or not path.exists():
            return []
        return [line for line in path.read_text().splitlines() if line.strip()]

    def _append(self, run_id: str, name: str, line: str) -> None:
        path = self.dir / run_id / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(line + "\n")

    # ---- writes

    def append_event(self, event: Event) -> None:
        self._append(event.run_id, EVENTS_FILE, event.model_dump_json())

    def save_snapshot(self, snapshot: RunSnapshot) -> None:
        write_atomic(self.dir / snapshot.run.id / SNAPSHOT_FILE, snapshot.model_dump_json(indent=1))

    def save_level_start(self, snapshot: RunSnapshot) -> None:
        write_atomic(self.dir / snapshot.run.id / LEVEL_START_FILE,
                     snapshot.model_dump_json(indent=1))

    def append_fork(self, fork: ForkRequest) -> None:
        self._append(fork.run_id, FORKS_FILE, fork.model_dump_json())

    def save_forks(self, run_id: str, forks: list[ForkRequest]) -> None:
        """Rewrite the run's fork requests (their status changes)."""
        write_atomic(self.dir / run_id / FORKS_FILE,
                     "".join(f.model_dump_json() + "\n" for f in forks))

    def save_fork_snapshot(self, run_id: str, fork_id: str, snapshot: RunSnapshot) -> None:
        """The tree just before a fork was confirmed (what undo restores)."""
        write_atomic(self.dir / run_id / FORK_SNAPSHOTS_DIR / f"{fork_id}.json",
                     snapshot.model_dump_json())

    def fork_snapshot(self, run_id: str, fork_id: str) -> RunSnapshot | None:
        path = self._file(run_id, f"{FORK_SNAPSHOTS_DIR}/{fork_id}.json")
        if path is None or not _NODE_ID.match(fork_id) or not path.exists():
            return None
        return RunSnapshot.model_validate_json(path.read_text())

    def delete_node_logs(self, run_id: str, node_id: str) -> None:
        path = self._file(run_id, f"{LOGS_DIR}/{node_id}.jsonl")
        if path is not None and _NODE_ID.match(node_id) and path.exists():
            path.unlink()

    def save_findings(self, run_id: str, findings: list[Finding]) -> None:
        """Rewrite the findings log (undoing a fork drops the findings of deleted nodes)."""
        write_atomic(self.dir / run_id / FINDINGS_FILE,
                     "".join(f.model_dump_json() + "\n" for f in findings))

    def forks(self, run_id: str) -> list[ForkRequest]:
        return [ForkRequest.model_validate_json(line) for line in self._lines(run_id, FORKS_FILE)]

    def append_log(self, run_id: str, node_id: str, entry: LogEntry) -> None:
        """Add a line to a node's log (data/runs/<run>/logs/<node>.jsonl)."""
        if _NODE_ID.match(node_id):
            self._append(run_id, f"{LOGS_DIR}/{node_id}.jsonl", entry.model_dump_json())

    def logs(self, run_id: str, node_id: str) -> list[LogEntry]:
        if not _NODE_ID.match(node_id):
            return []
        return [LogEntry.model_validate_json(line)
                for line in self._lines(run_id, f"{LOGS_DIR}/{node_id}.jsonl")]

    def append_finding(self, finding: Finding) -> None:
        self._append(finding.run_id, FINDINGS_FILE, finding.model_dump_json())

    def findings(self, run_id: str) -> list[Finding]:
        return [Finding.model_validate_json(line) for line in self._lines(run_id, FINDINGS_FILE)]

    def run_vault(self, run_id: str) -> RunVault | None:
        path = self._file(run_id, RUN_VAULT_FILE)
        if path is None or not path.exists():
            return None
        return RunVault.model_validate_json(path.read_text())

    def save_run_vault(self, vault: RunVault) -> None:
        write_atomic(self.dir / vault.run_id / RUN_VAULT_FILE, vault.model_dump_json(indent=1))

    def save_patch(self, run_id: str, patch: str) -> None:
        write_atomic(self.dir / run_id / PATCH_FILE, patch)

    def patch(self, run_id: str) -> str | None:
        path = self._file(run_id, PATCH_FILE)
        return path.read_text() if path is not None and path.exists() else None

    def last_seq(self, run_id: str) -> int:
        return max((e.seq for e in self.events(run_id)), default=0)

    def mark_stopped(self, run_id: str, snapshot: RunSnapshot | None = None) -> RunFailed:
        """End a run the user stopped: append the final run_failed event ("Stopped by the user")
        and save the tree as it is (`snapshot`, normally the run's live state; the last saved
        one if not given) with status "failed". Raises KeyError for an unknown run."""
        snapshot = snapshot or self.snapshot(run_id)
        if snapshot is None:
            raise KeyError(run_id)
        event = RunFailed(seq=self.last_seq(run_id) + 1, run_id=run_id, error=STOPPED_BY_USER)
        self.append_event(event)
        run = snapshot.run.model_copy(update={"status": "failed", "paused": False,
                                               "end_reason": "stopped"})
        self.save_snapshot(snapshot.model_copy(update={"run": run}))
        return event

    # ---- reads

    def events(self, run_id: str, after: int = 0) -> list[Event]:
        """The run's saved events with seq greater than `after`, in order."""
        events = [parse_event(line) for line in self._lines(run_id, EVENTS_FILE)]
        return [e for e in events if e.seq > after]

    def snapshot(self, run_id: str) -> RunSnapshot | None:
        saved = self._file(run_id, SNAPSHOT_FILE)
        if saved is None:
            return None
        if saved.exists():
            return RunSnapshot.model_validate_json(saved.read_text())
        return rebuild_snapshot(self.events(run_id))

    def level_start(self, run_id: str) -> RunSnapshot | None:
        """The tree as it was when the run's current level was created, if one was saved."""
        saved = self._file(run_id, LEVEL_START_FILE)
        if saved is None or not saved.exists():
            return None
        return RunSnapshot.model_validate_json(saved.read_text())

    def list(self) -> list[Run]:
        """Every saved run, newest first."""
        if not self.dir.exists():
            return []
        runs = [s.run for p in self.dir.iterdir() if p.is_dir()
                if (s := self.snapshot(p.name)) is not None]
        return sorted(runs, key=lambda r: r.created_at, reverse=True)
