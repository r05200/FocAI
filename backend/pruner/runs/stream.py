"""Live events: the per-run EventBus and the SSE stream built on it.

EventBus: Emitter.emit appends every event to the run's log first, then publishes it here. Each
subscriber (one per open stream) has a bounded queue; a subscriber that falls that far behind is
dropped (its stream ends) and simply reconnects with Last-Event-ID / ?after=, since the log on
disk is the source of truth.

run_events(): what GET /runs/{id}/events sends. It subscribes BEFORE reading the saved history,
so no event can fall in between; events are deduplicated by seq. It sends the history after
`after`, then live events, a ": ping" comment every `ping_s` seconds, and ends after
run_completed / run_failed (or at once for a finished run with nothing newer to send).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable

from pruner.core.events import Event, EventBase
from pruner.runs.store import RunStore

TERMINAL = ("run_completed", "run_failed")
QUEUE_SIZE = 1000
PING_S = 15.0


def frame(event: EventBase) -> str:
    """One SSE message: id = seq, event = type, data = the event JSON."""
    return (f"id: {event.seq}\nevent: {event.type}\n"  # type: ignore[attr-defined]
            f"data: {event.model_dump_json()}\n\n")


class EventBus:
    def __init__(self, queue_size: int = QUEUE_SIZE) -> None:
        self.queue_size = queue_size
        self._subs: dict[str, set[asyncio.Queue]] = {}

    def subscribe(self, run_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self.queue_size)
        self._subs.setdefault(run_id, set()).add(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue) -> None:
        subs = self._subs.get(run_id)
        if subs is not None:
            subs.discard(queue)
            if not subs:
                del self._subs[run_id]

    def subscribers(self, run_id: str) -> int:
        return len(self._subs.get(run_id, ()))

    def publish(self, event: EventBase) -> None:
        for queue in list(self._subs.get(event.run_id, ())):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:  # too slow: drop it; it resumes from the log
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(None)
                self.unsubscribe(event.run_id, queue)


async def run_events(store: RunStore, bus: EventBus, run_id: str, after: int = 0, *,
                     ping_s: float = PING_S,
                     is_disconnected: Callable[[], Awaitable[bool]] | None = None,
                     ) -> AsyncIterator[str]:
    queue = bus.subscribe(run_id)
    try:
        last = after
        history: list[Event] = await asyncio.to_thread(store.events, run_id, after)
        for e in history:
            yield frame(e)
            last = e.seq
            if e.type in TERMINAL:
                return
        snap = await asyncio.to_thread(store.snapshot, run_id)
        if snap is not None and snap.run.status != "running":
            while not queue.empty():  # anything published while the history was read
                e = queue.get_nowait()
                if e is not None and e.seq > last:
                    yield frame(e)
                    last = e.seq
            return
        while True:
            try:
                e = await asyncio.wait_for(queue.get(), ping_s)
            except TimeoutError:
                if is_disconnected is not None and await is_disconnected():
                    return
                yield ": ping\n\n"
                continue
            if e is None:  # dropped for falling behind; the client resumes after `last`
                return
            if e.seq <= last:
                continue
            yield frame(e)
            last = e.seq
            if e.type in TERMINAL:
                return
    finally:
        bus.unsubscribe(run_id, queue)
