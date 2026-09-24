"""Event contracts (API-40). Implementation: `app.events.bus.EventBus`."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

EventType = Literal[
    "curation.appended",
    "job.progress",
    "job.finished",
    "job.status",
    "index.rebuilt",
    "project.updated",
]
REPLAY_MAX = 1000


class Event(BaseModel):
    id: int  # monotonic across the process and across restarts (SSE `id`)
    project_id: str
    event: EventType
    data: dict[str, Any]
    at: str
