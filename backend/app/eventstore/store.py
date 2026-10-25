"""One append-only JSONL file per namespace and project.

`events/{namespace}.jsonl`; namespace `curation` keeps `curation/events.jsonl` so nothing
migrates. Only the API process appends, under the project lock. Each append publishes
`{namespace}.appended` on the project's SSE stream, unless the caller publishes its own
payload. The derived state is last-writer-wins per key in append (= server) order, with history.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable, Sequence
from pathlib import Path
from typing import Any, Final, cast

from app.core.errors import ValidationProblem
from app.core.fsio import append_jsonl
from app.core.ids import new_ulid, utc_now
from app.core.locks import ProjectLocks
from app.events.bus import EventBus
from app.events.types import EventType
from app.projects.service import Workspace

NAMESPACE_FILES: Final = {"curation": Path("curation") / "events.jsonl"}
SSE_EVENT_MAX: Final = 500  # a larger batch publishes one summary event instead


def namespace_path(project_dir: Path, namespace: str) -> Path:
    if not namespace.isidentifier():
        raise ValidationProblem(f"Invalid event namespace {namespace!r}")
    return project_dir / NAMESPACE_FILES.get(namespace, Path("events") / f"{namespace}.jsonl")


def stamp(reviewer: str, session_id: str | None, body: dict[str, Any]) -> dict[str, Any]:
    """An event record: `event_id`, `at`, reviewer and session stamps, then the body."""
    return {
        "event_id": new_ulid(),
        "at": utc_now(),
        "reviewer": reviewer,
        "session_id": (session_id or "").strip() or None,
        **body,
    }


class EventStore:
    def __init__(self, workspace: Workspace, locks: ProjectLocks, bus: EventBus) -> None:
        self.workspace = workspace
        self.locks = locks
        self.bus = bus

    def append_locked(
        self, project_id: str, namespace: str, events: Sequence[dict[str, Any]]
    ) -> None:
        """Caller holds the project lock."""
        append_jsonl(namespace_path(self.workspace.project_dir(project_id), namespace), events)

    def publish(
        self,
        project_id: str,
        namespace: str,
        events: Sequence[dict[str, Any]],
        summary: dict[str, Any],
    ) -> None:
        name = cast(EventType, f"{namespace}.appended")
        if len(events) <= SSE_EVENT_MAX:
            for e in events:
                self.bus.publish(project_id, name, e)
        else:
            self.bus.publish(project_id, "project.updated", summary)

    async def append(
        self, project_id: str, namespace: str, events: Sequence[dict[str, Any]]
    ) -> None:
        async with self.locks(project_id):
            self.append_locked(project_id, namespace, events)
        self.publish(project_id, namespace, events, {"fields": [namespace]})


def latest(
    events: Iterable[dict[str, Any]], key: Callable[[dict[str, Any]], Hashable]
) -> dict[Hashable, dict[str, Any]]:
    """Last-writer-wins state per key, in append order."""
    out: dict[Hashable, dict[str, Any]] = {}
    for e in events:
        out[key(e)] = e
    return out
