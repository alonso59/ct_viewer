"""Shared run lifecycle (AUD-A6-06): `run.json` I/O, status transitions, reconcile, cancel,
resume guard and job submission for task runs (`tasks/runs/`, TSK-06..10) and radiomics runs
(`radiomics/runs/`, RAD-06..09, RAD-13).

Only the API process writes `run.json`, atomically through `core.fsio` and under the project lock
(BE-05). A non-terminal run whose job the manager no longer knows (server restart) is reported
`interrupted` (BE-06). What a run *does* (its job, its outputs) stays with its service.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Final, Protocol

from pydantic import BaseModel

from app.core.errors import JobConflict, NotFound, Problem
from app.core.fsio import atomic_write_json, read_json
from app.core.ids import is_ulid, utc_now
from app.core.locks import ProjectLocks
from app.jobs.manager import JobManager
from app.jobs.types import TERMINAL, JobInfo, JobSpec

RUN_JSON: Final = "run.json"


class _Run(Protocol):
    status: Any
    job_id: Any
    error: Any
    started_at: Any
    finished_at: Any


class RunStore[R: BaseModel]:
    """The run records of one kind (`{project}/{root}/{run_id}/run.json`)."""

    def __init__(
        self,
        model: type[R],
        runs_dir: Callable[[str], Path],
        jobs: JobManager,
        locks: ProjectLocks,
        *,
        terminal: frozenset[str],
        resumable: frozenset[str],
        noun: str,
    ) -> None:
        self.model = model
        self.runs_dir = runs_dir
        self.jobs = jobs
        self.locks = locks
        self.terminal = terminal
        self.resumable_states = resumable
        self.noun = noun  # "Run" / "Task run" in the 404 title

    # -- records ----------------------------------------------------------------------------

    def read(self, run_dir: Path) -> R:
        return self.model.model_validate(read_json(run_dir / RUN_JSON))

    def write(self, run_dir: Path, rec: R) -> None:
        """Temp file + fsync + rename (RAD-09, NFR-15)."""
        atomic_write_json(run_dir / RUN_JSON, rec.model_dump(mode="json"))

    def has(self, pid: str, rid: str) -> bool:
        return is_ulid(rid) and (self.runs_dir(pid) / rid / RUN_JSON).is_file()

    def run_dir(self, pid: str, rid: str) -> Path:
        if not self.has(pid, rid):
            raise NotFound(f"{self.noun} {rid!r} not found")
        return self.runs_dir(pid) / rid

    def run_dirs(self, pid: str) -> Iterator[Path]:
        """Every run folder with a record, newest first."""
        d = self.runs_dir(pid)
        if not d.is_dir():
            return
        for run_dir in sorted(d.iterdir(), key=lambda p: p.name, reverse=True):
            if is_ulid(run_dir.name) and (run_dir / RUN_JSON).is_file():
                yield run_dir

    async def update(self, pid: str, run_dir: Path, edit: Callable[[R], bool | None]) -> R:
        """Read, edit, write under the project lock; `edit` returning False skips the write."""
        async with self.locks(pid):
            rec = self.read(run_dir)
            if edit(rec) is not False:
                self.write(run_dir, rec)
            return rec

    # -- status ------------------------------------------------------------------------------

    def job(self, job_id: str | None) -> JobInfo | None:
        if job_id is None:
            return None
        try:
            return self.jobs.get(job_id)
        except NotFound:
            return None

    async def set_status(self, pid: str, run_dir: Path, status: str) -> None:
        """Forward only: a terminal run keeps its status; `running` stamps `started_at` once."""

        def edit(rec: Any) -> bool:
            run: _Run = rec
            if run.status in self.terminal or run.status == status:
                return False
            run.status = status
            if status == "running":
                run.started_at = run.started_at or utc_now()
            return True

        await self.update(pid, run_dir, edit)

    async def reconcile(self, pid: str, run_dir: Path) -> R:
        """A non-terminal run whose job is unknown (server restart) → `interrupted` (BE-06)."""
        rec = self.read(run_dir)
        run: _Run = rec  # type: ignore[assignment]
        if run.status in self.terminal or self.job(run.job_id) is not None:
            return rec

        def edit(rec: Any) -> bool:
            run: _Run = rec
            if run.status in self.terminal or self.job(run.job_id) is not None:
                return False
            run.status, run.finished_at = "interrupted", utc_now()
            return True

        return await self.update(pid, run_dir, edit)

    # -- control -----------------------------------------------------------------------------

    async def cancel(self, pid: str, run_dir: Path, grace_s: float) -> None:
        """Cancel the run's live job and wait up to `grace_s`; idempotent for finished runs."""
        rec: _Run = await self.reconcile(pid, run_dir)  # type: ignore[assignment]
        job = self.job(rec.job_id)
        if rec.status not in self.terminal and job is not None and rec.job_id is not None:
            if job.status not in TERMINAL:
                self.jobs.cancel(rec.job_id)
            with contextlib.suppress(TimeoutError):
                await self.jobs.wait(rec.job_id, grace_s)

    async def resumable(self, pid: str, run_dir: Path) -> R:
        """The reconciled record, or 409 unless it is interrupted, cancelled or failed."""
        rec = await self.reconcile(pid, run_dir)
        status = rec.status  # type: ignore[attr-defined]
        if status not in self.resumable_states:
            raise JobConflict(f"Run is {status}; only interrupted, cancelled or failed resume")
        return rec

    async def submit(
        self,
        pid: str,
        run_dir: Path,
        spec: JobSpec,
        *,
        prepare: Callable[[Any], None] | None = None,
        on_error: Callable[[], None] | None = None,
    ) -> None:
        """Record the attempt (`job_id`, `queued`, then `prepare`), submit; a refused submit
        (busy, conflict) records `failed` with the problem's detail and re-raises."""

        def queued(rec: Any) -> None:
            run: _Run = rec
            run.job_id, run.status = spec.job_id, "queued"
            if prepare is not None:
                prepare(rec)

        await self.update(pid, run_dir, queued)
        try:
            self.jobs.submit(spec)
        except Problem as exc:
            detail = exc.detail

            def failed(rec: Any) -> None:
                run: _Run = rec
                run.status, run.error, run.finished_at = "failed", detail, utc_now()

            await self.update(pid, run_dir, failed)
            if on_error is not None:
                on_error()
            raise
