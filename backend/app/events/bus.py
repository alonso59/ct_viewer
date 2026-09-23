"""In-process pub/sub with per-project replay buffers (API-40). SKELETON: lane sub-agent D."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.events.types import REPLAY_MAX, Event, EventType


class EventBus:
    def __init__(self, replay_max: int = REPLAY_MAX) -> None:
        self.replay_max = replay_max

    def publish(self, project_id: str, event: EventType, data: dict[str, Any]) -> Event:
        """Record + fan out. Must be called on the event-loop thread; never blocks."""
        raise NotImplementedError

    def subscribe(self, project_id: str, last_event_id: int | None = None) -> AsyncIterator[Event]:
        """Replay buffered events with id > last_event_id (all buffered if unknown), then live."""
        raise NotImplementedError

    def close(self) -> None:
        """Shutdown: end all subscriptions."""
        raise NotImplementedError
