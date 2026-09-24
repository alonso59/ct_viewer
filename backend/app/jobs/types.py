"""Job contracts (BE-06). Implementation: `app.jobs.manager.JobManager`.

A job is a list of `WorkUnit`s executed in the process pool. Results come back to the API
process through `on_result` (the only place that may write project files), then
`on_finish` runs once and may return the job `ref` (e.g. an import_id).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel

JobKind = Literal["index", "hash", "thumbnail", "radiomics", "mesh", "task", "open-convert"]
JobStatus = Literal[
    "queued", "waiting_for_runner", "running", "succeeded", "failed", "cancelled", "interrupted"
]
TERMINAL: frozenset[str] = frozenset({"succeeded", "failed", "cancelled", "interrupted"})


@dataclass(frozen=True)
class WorkUnit:
    """`fn(*args)` runs in a worker process: `fn` must be a module-level (picklable) function."""

    fn: Callable[..., Any]
    args: tuple[Any, ...] = ()


class JobInfo(BaseModel):
    """API-41 payload."""

    job_id: str
    kind: JobKind
    project_id: str
    status: JobStatus
    done: int = 0
    total: int = 0
    eta_s: float | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    ref: str | None = None
    error: str | None = None
    key: str | None = None  # e.g. the task id of a `task` job (TSK-12)


class JobHandle(Protocol):
    """What a driver coroutine sees of its job (task runs, TSK-06/07)."""

    @property
    def stopped(self) -> bool: ...  # cancelled, or the server is shutting down

    def set_total(self, total: int) -> None: ...
    def set_done(self, done: int) -> None: ...
    def set_status(self, status: JobStatus) -> None: ...  # `waiting_for_runner` ↔ `running`
    async def run_in_worker(self, fn: Callable[..., Any], *args: Any) -> Any: ...


@dataclass
class JobSpec:
    project_id: str
    kind: JobKind
    units: Sequence[WorkUnit]
    # API process, once per unit result (completion order). Exceptions fail the job.
    on_result: Callable[[Any], Awaitable[None]] | None = None
    # API process, once, with the final status (succeeded | failed | cancelled). Returns `ref`.
    on_finish: Callable[[JobInfo], Awaitable[str | None]] | None = None
    # One queued/running job per (project_id, kind); a second submit raises JobConflict.
    exclusive: bool = True
    ref: str | None = None
    job_id: str | None = None  # pre-allocated id (optional)
    meta: dict[str, Any] = field(default_factory=dict)
    # Instead of `units`: a coroutine that drives the job itself (progress, status, workers).
    # Its exception fails the job; it must return soon after `handle.stopped` turns true.
    driver: Callable[[JobHandle], Awaitable[None]] | None = None
    # (kind, key) exclusivity instead of (kind): one task run per (project, task_id) (TSK-12).
    key: str | None = None
