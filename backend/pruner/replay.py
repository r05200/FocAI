"""Replays: saved copies of runs, streamed back with their original timing. A demo fallback that
makes no LLM calls and runs nothing.

    cd backend
    uv run python -m pruner.replay export <run_id> <name>   # copy a run to data/replays/<name>
    uv run python -m pruner.replay list

A replay folder has the same layout as a run folder (events, snapshot, logs, run vault, findings,
patch; see runs/store.py), so RunStore reads it. GET /api/replays lists them and
GET /api/replays/{name}/events?speed= streams one: each event waits for the gap since the previous
one (at most MAX_GAP_S) divided by `speed`.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import shutil
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

from pruner.core.config import Config, get_config
from pruner.core.events import Event
from pruner.runs.store import EVENTS_FILE, RunStore
from pruner.runs.stream import frame

NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")  # replay names (and run ids) become folder names
MAX_GAP_S = 2.0


class ReplayError(ValueError):
    pass


def export(run_id: str, name: str, cfg: Config | None = None, *,
           overwrite: bool = False) -> Path:
    """Copy a saved run's folder to cfg.replays_dir/<name>."""
    cfg = cfg or get_config()
    for what, value in (("run id", run_id), ("replay name", name)):
        if not NAME.match(value):
            raise ReplayError(f"bad {what} {value!r}: letters, digits, _ and - only")
    src, dst = cfg.runs_dir / run_id, cfg.replays_dir / name
    if not (src / EVENTS_FILE).exists():
        raise ReplayError(f"no saved run {run_id} in {cfg.runs_dir}")
    if dst.exists():
        if not overwrite:
            raise ReplayError(f"replay {name} already exists (use --overwrite)")
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("level_start.json"))
    return dst


def list_replays(cfg: Config | None = None) -> list[str]:
    root = (cfg or get_config()).replays_dir
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir()
                  if p.is_dir() and NAME.match(p.name) and (p / EVENTS_FILE).exists())


def replay_events(name: str, cfg: Config | None = None) -> list[Event] | None:
    """A replay's events, or None if there is no such replay."""
    cfg = cfg or get_config()
    if not NAME.match(name) or not (cfg.replays_dir / name / EVENTS_FILE).exists():
        return None
    return RunStore(cfg.replays_dir).events(name)


async def replay_stream(events: list[Event], speed: float = 1.0,
                        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                        ) -> AsyncIterator[str]:
    """The events as SSE frames, spaced like the original run (gaps capped, divided by speed)."""
    previous = None
    for e in events:
        if previous is not None:
            await sleep(min(max(0.0, e.ts - previous.ts), MAX_GAP_S) / speed)
        yield frame(e)
        previous = e


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pruner.replay")
    sub = parser.add_subparsers(dest="command", required=True)
    exp = sub.add_parser("export", help="copy a saved run to data/replays/<name>")
    exp.add_argument("run_id")
    exp.add_argument("name")
    exp.add_argument("--overwrite", action="store_true")
    sub.add_parser("list", help="list the saved replays")
    args = parser.parse_args(argv)
    if args.command == "list":
        print("\n".join(list_replays()) or "(no replays)")
        return 0
    try:
        print(f"wrote {export(args.run_id, args.name, overwrite=args.overwrite)}")
    except ReplayError as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
