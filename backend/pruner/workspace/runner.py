"""Running the user's experiment command.

The command text always comes from the user (see runs/command.py), so it runs as they wrote it:
through /bin/sh, in the run's root folder, with the server's environment. There is no sandbox.
What is kept is operational: a timeout, a cap on the output kept, and the whole process group is
killed on timeout or when the run is stopped (the caller's task is cancelled), so no experiment
outlives its run.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

KILL_GRACE_S = 3.0


@dataclass
class CommandResult:
    exit_code: int | None  # None when it was killed
    timed_out: bool
    duration_s: float
    stdout: str  # the tail, at most `output_cap` bytes
    stderr: str


async def _read_tail(stream: asyncio.StreamReader, cap: int) -> str:
    chunks: deque[bytes] = deque()
    size = 0
    while chunk := await stream.read(65536):
        chunks.append(chunk)
        size += len(chunk)
        while size - len(chunks[0]) >= cap and len(chunks) > 1:
            size -= len(chunks.popleft())
    data = b"".join(chunks)[-cap:]
    return data.decode("utf-8", errors="replace")


def _kill_group(proc: asyncio.subprocess.Process, sig: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, sig)


async def _stop(proc: asyncio.subprocess.Process) -> None:
    """SIGTERM the process group, then SIGKILL it if it is still there after a grace period."""
    if proc.returncode is not None:
        return
    _kill_group(proc, signal.SIGTERM)
    try:
        await asyncio.wait_for(proc.wait(), KILL_GRACE_S)
    except TimeoutError:
        _kill_group(proc, signal.SIGKILL)
        await proc.wait()


async def run_command(command: str, cwd: Path, *, timeout_s: float,
                      output_cap: int = 20_000) -> CommandResult:
    start = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        "/bin/sh", "-c", command, cwd=str(cwd), stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True)
    assert proc.stdout is not None and proc.stderr is not None
    readers = asyncio.gather(_read_tail(proc.stdout, output_cap),
                             _read_tail(proc.stderr, output_cap))
    timed_out = False
    try:
        try:
            await asyncio.wait_for(proc.wait(), timeout_s)
        except TimeoutError:
            timed_out = True
            await _stop(proc)
        stdout, stderr = await readers
    except asyncio.CancelledError:  # the run was stopped: take the experiment down with it
        await _stop(proc)
        readers.cancel()
        raise
    return CommandResult(exit_code=None if timed_out else proc.returncode, timed_out=timed_out,
                         duration_s=round(time.monotonic() - start, 3), stdout=stdout,
                         stderr=stderr)
