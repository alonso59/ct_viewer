"""Job contracts (BE-06). Implementation: `app.jobs.manager.JobManager`.

A job is a list of `WorkUnit`s executed in the process pool. Results come back to the API
process through `on_result` (the only place that may write project files), then
`on_finish` runs once and may return the job `ref` (e.g. an import_id).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

JobKind = Literal["index", "hash", "thumbnail", "radiomics", "mesh"]
JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled", "interrupted"]
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
