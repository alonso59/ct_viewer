"""In-process pub/sub with per-project replay buffers (API-40).

Single-threaded: every method runs on the event-loop thread. Event ids are process-wide,
monotonic, and seeded from the wall clock so they keep increasing across restarts.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import AsyncIterator
from typing import Any

from app.core.ids import utc_now
from app.events.types import REPLAY_MAX, Event, EventType

log = logging.getLogger("app.events")

QUEUE_MAX = 1000  # per subscriber; overflow drops the subscriber (it reconnects + replays)


class Subscription(AsyncIterator[Event]):
    """Replayed events first, then live ones; ends on overflow, `aclose()` or `bus.close()`."""

    def __init__(self, bus: EventBus, project_id: str, replay: list[Event]) -> None:
        self._bus = bus
        self.project_id = project_id
        self._replay = deque(replay)
        self._queue: asyncio.Queue[Event | None] = asyncio.Queue(maxsize=QUEUE_MAX)
        self._ended = False

    def __aiter__(self) -> Subscription:
        return self

    async def __anext__(self) -> Event:
        if self._replay:
            return self._replay.popleft()
        if self._ended and self._queue.empty():
            raise StopAsyncIteration
        ev = await self._queue.get()
        if ev is None:
            self._ended = True
            self._bus._discard(self)
            raise StopAsyncIteration
        return ev

    async def aclose(self) -> None:
        self._replay.clear()
        self._end(drain=True)
        self._bus._discard(self)

    def _offer(self, ev: Event) -> bool:
        try:
            self._queue.put_nowait(ev)
        except asyncio.QueueFull:
            return False
        return True

    def _end(self, *, drain: bool) -> None:
        if self._ended:
            return
        self._ended = True
        if drain or self._queue.full():
            while not self._queue.empty():
                self._queue.get_nowait()
        self._queue.put_nowait(None)


class EventBus:
    def __init__(self, replay_max: int = REPLAY_MAX) -> None:
        self.replay_max = replay_max
        self._next_id = time.time_ns() // 1000
        self._buffers: dict[str, deque[Event]] = {}
        self._subs: dict[str, set[Subscription]] = {}
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def publish(self, project_id: str, event: EventType, data: dict[str, Any]) -> Event:
        """Record + fan out. Must be called on the event-loop thread; never blocks."""
        ev = Event(id=self._next_id, project_id=project_id, event=event, data=data, at=utc_now())
        self._next_id += 1
        if self._closed:
            return ev
        buf = self._buffers.get(project_id)
        if buf is None:
            buf = self._buffers[project_id] = deque(maxlen=self.replay_max)
        buf.append(ev)
        for sub in list(self._subs.get(project_id, ())):
            if not sub._offer(ev):
                log.warning("SSE subscriber too slow; dropped", extra={"project_id": project_id})
                sub._end(drain=True)
                self._discard(sub)
        return ev

    def subscribe(self, project_id: str, last_event_id: int | None = None) -> AsyncIterator[Event]:
        """Replay buffered events with id > last_event_id (all buffered if unknown), then live.

        `last_event_id=None` replays nothing. An id outside the buffered range (older than the
        oldest - 1, or newer than the newest, e.g. from before a restart) replays everything.
        """
        replay: list[Event] = []
        buf = self._buffers.get(project_id)
        if last_event_id is not None and buf:
            oldest, newest = buf[0].id, buf[-1].id
            if last_event_id < oldest - 1 or last_event_id > newest:
                replay = list(buf)
            else:
                replay = [e for e in buf if e.id > last_event_id]
        sub = Subscription(self, project_id, replay)
        if self._closed:
            sub._end(drain=True)
        else:
            self._subs.setdefault(project_id, set()).add(sub)
        return sub

    def subscriber_count(self, project_id: str) -> int:
        return len(self._subs.get(project_id, ()))

    def close(self) -> None:
        """Shutdown: end all subscriptions; later publishes are ignored."""
        self._closed = True
        for subs in self._subs.values():
            for sub in subs:
                sub._end(drain=False)
        self._subs.clear()

    def _discard(self, sub: Subscription) -> None:
        subs = self._subs.get(sub.project_id)
        if subs is not None:
            subs.discard(sub)
            if not subs:
                del self._subs[sub.project_id]
