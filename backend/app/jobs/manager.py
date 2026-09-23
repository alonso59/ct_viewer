"""Job manager over a ProcessPoolExecutor (BE-06, BE-13). SKELETON: lane sub-agent D."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.events.bus import EventBus
from app.jobs.types import JobInfo, JobKind, JobSpec


class JobManager:
    def __init__(self, bus: EventBus, workers: int = 2, *, inline: bool = False) -> None:
        """`inline=True` (tests) runs units in a thread instead of worker processes."""
        self.bus = bus
        self.workers = workers
        self.inline = inline

    async def start(self) -> None:
        raise NotImplementedError

    async def shutdown(self) -> None:
        """Stop accepting jobs; running/queued jobs become `interrupted` (BE-13)."""
        raise NotImplementedError

    def submit(self, spec: JobSpec) -> JobInfo:
        """Schedule; raises JobConflict if `spec.exclusive` and (project, kind) is active."""
        raise NotImplementedError

    def get(self, job_id: str) -> JobInfo:
        raise NotImplementedError

    def list(self, project_id: str | None = None) -> list[JobInfo]:
        raise NotImplementedError

    def active(self, project_id: str, kind: JobKind) -> JobInfo | None:
        raise NotImplementedError

    def cancel(self, job_id: str) -> JobInfo:
        raise NotImplementedError

    async def wait(self, job_id: str, timeout: float | None = None) -> JobInfo:
        raise NotImplementedError

    async def run_in_worker(self, fn: Callable[..., Any], *args: Any) -> Any:
        """One-off worker call outside job tracking (e.g. npy→NIfTI conversion, IMP-10)."""
        raise NotImplementedError
