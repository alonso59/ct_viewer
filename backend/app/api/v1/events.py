"""API-40 SSE stream."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Header, Query
from sse_starlette import EventSourceResponse

from app.api.v1.deps import Ctx
from app.events.bus import EventBus

router = APIRouter(tags=["events"])

PING_S = 15


async def sse_messages(
    bus: EventBus, project_id: str, last_event_id: int | None
) -> AsyncIterator[dict[str, str]]:
    """Bus events as SSE messages; ends when the bus closes, unsubscribes on disconnect."""
    sub = bus.subscribe(project_id, last_event_id)
    try:
        async for ev in sub:
            yield {"id": str(ev.id), "event": ev.event, "data": json.dumps(ev.data)}
    finally:
        aclose = getattr(sub, "aclose", None)
        if aclose is not None:
            await aclose()


def _parse_id(value: str | None) -> int | None:
    try:
        return int(value) if value is not None and value.strip() else None
    except ValueError:
        return None


@router.get(
    "/projects/{pid}/events",
    response_class=EventSourceResponse,
    responses={200: {"content": {"text/event-stream": {}}, "description": "SSE stream"}},
)
async def project_events(
    ctx: Ctx,
    pid: str,
    last_event_id: Annotated[int | None, Query()] = None,
    last_event_id_header: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> EventSourceResponse:
    """Realtime stream; resumes from `Last-Event-ID` (header) or `?last_event_id=`."""
    ctx.workspace.project_dir(pid)  # NotFound for unknown projects
    header_id = _parse_id(last_event_id_header)
    start = header_id if header_id is not None else last_event_id
    return EventSourceResponse(sse_messages(ctx.bus, pid, start), ping=PING_S)
