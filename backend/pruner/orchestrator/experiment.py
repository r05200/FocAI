"""The experiment phase (no LLM): put the node's code in place, run the user's command, read the
result.

run(node):
  1. writes the node's code version to the user's files (Workspace.apply_version);
  2. runs the verified command in the run's root (workspace/runner.py: shell, timeout, output
     cap, killed with the run on Stop);
  3. finds the result JSON, in this order: the file the user named (RunCommand.result_file), the
     last line of stdout that is a JSON object, or the one *.json file under the root that the
     run created or changed; otherwise the experiment counts as failed ("no result JSON");
  4. flattens the result's numbers into `metrics` (dotted keys, e.g. "latency.p50").
A non-zero exit, a timeout or a missing result makes `error` set; the caller marks the node.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from pathlib import Path

from pruner.core.config import Config, get_config
from pruner.core.models import ExperimentRun, RunCommand
from pruner.runs.command import runnable
from pruner.workspace.paths import SKIP_DIRS, PathError
from pruner.workspace.runner import CommandResult, run_command
from pruner.workspace.workspace import Workspace

RESULT_MAX_BYTES = 256_000
TAIL_CHARS = 2000  # of stdout/stderr kept on the node
SCAN_MAX_FILES = 5000

Runner = Callable[..., Awaitable[CommandResult]]


def flatten_metrics(value: object, prefix: str = "") -> dict[str, float]:
    """Numeric leaves of a JSON value with dotted keys (booleans are not numbers here)."""
    out: dict[str, float] = {}
    if isinstance(value, dict):
        for k, v in value.items():
            out.update(flatten_metrics(v, f"{prefix}{k}."))
    elif isinstance(value, list):
        for i, v in enumerate(value[:50]):
            out.update(flatten_metrics(v, f"{prefix}{i}."))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        out[prefix.rstrip(".") or "value"] = float(value)
    return out


def json_mtimes(root: Path) -> dict[str, float]:
    """Modification times of the *.json files under `root` (skipping noise folders)."""
    out: dict[str, float] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.endswith(".json"):
                path = Path(dirpath) / name
                try:
                    out[path.relative_to(root).as_posix()] = path.stat().st_mtime
                except OSError:
                    continue
                if len(out) >= SCAN_MAX_FILES:
                    return out
    return out


def _load(path: Path) -> object | None:
    try:
        if path.stat().st_size > RESULT_MAX_BYTES:
            return None
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def find_result(ws: Workspace, command: RunCommand, stdout: str,
                before: dict[str, float]) -> tuple[object | None, str]:
    """(the result, where it came from) or (None, why nothing was found)."""
    root = ws.roots.root
    if command.result_file:
        try:
            rel = ws.roots.root / command.result_file
            if rel.resolve().is_relative_to(root):
                value = _load(rel)
                if value is not None:
                    return value, command.result_file
        except (OSError, PathError):
            pass
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith(("{", "[")):
            try:
                return json.loads(line), "stdout"
            except ValueError:
                continue
    after = json_mtimes(root)
    changed = [rel for rel, mtime in after.items() if before.get(rel) != mtime]
    if len(changed) == 1:
        value = _load(root / changed[0])
        if value is not None:
            return value, changed[0]
    where = (f"{len(changed)} JSON files changed ({', '.join(sorted(changed)[:5])})"
             if len(changed) > 1 else "no JSON on stdout and no JSON file was written")
    return None, f"no result JSON found: {where}"


class ExperimentPhase:
    def __init__(self, cfg: Config | None = None, runner: Runner = run_command) -> None:
        self.cfg = cfg or get_config()
        self.runner = runner

    async def run(self, ws: Workspace, command: RunCommand, version: str) -> ExperimentRun:
        await asyncio.to_thread(ws.apply_version, version)
        before = await asyncio.to_thread(json_mtimes, ws.roots.root)
        result = await self.runner(runnable(command.text), ws.roots.root,
                                   timeout_s=command.timeout_s or self.cfg.experiment_timeout_s,
                                   output_cap=self.cfg.experiment_output_cap)
        run = ExperimentRun(command=command.text, exit_code=result.exit_code,
                            timed_out=result.timed_out, duration_s=result.duration_s,
                            stdout_tail=result.stdout[-TAIL_CHARS:],
                            stderr_tail=result.stderr[-TAIL_CHARS:])
        if result.timed_out:
            run.error = f"timed out after {command.timeout_s or self.cfg.experiment_timeout_s:g}s"
            return run
        value, where = find_result(ws, command, result.stdout, before)
        if value is not None:
            run.result = value if isinstance(value, dict) else {"value": value}
            run.metrics = flatten_metrics(value)
        if result.exit_code != 0:
            run.error = f"the command exited with code {result.exit_code}"
        elif value is None:
            run.error = where
        return run


def describe(run: ExperimentRun) -> str:
    """A compact text of an experiment for prompts and Node.result."""
    if run.error:
        tail = (run.stderr_tail or run.stdout_tail).strip()[-800:]
        return f"FAILED: {run.error}." + (f"\nOutput:\n{tail}" if tail else "")
    metrics = ", ".join(f"{k}={v:g}" for k, v in list(run.metrics.items())[:30])
    return f"Measured in {run.duration_s:.1f}s: {metrics or json.dumps(run.result)[:800]}"
