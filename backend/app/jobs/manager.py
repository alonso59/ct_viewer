"""Job manager over a ProcessPoolExecutor (BE-06, BE-13).

Each job is an asyncio task on the API loop that keeps at most `workers` units in flight on
the shared pool, relays results to `on_result`, then runs `on_finish` once. Progress and
completion are published on the event bus (API-40).
"""

from __future__ import annotations

import asyncio
import logging
import multiprocessing
import time
from collections import deque
from collections.abc import Callable, Iterator
from concurrent.futures import Executor, ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from app.core.errors import JobConflict, NotFound, ServerBusy
from app.core.ids import new_ulid, utc_now
from app.events.bus import EventBus
from app.jobs.types import TERMINAL, JobInfo, JobKind, JobSpec, JobStatus

log = logging.getLogger("app.jobs")

KEEP_TERMINAL = 500
PROGRESS_INTERVAL_S = 0.25  # ≤ 4 job.progress events per second per job
SHUTDOWN_FINISH_TIMEOUT_S = 5.0


@dataclass(eq=False)
class _Job:
    spec: JobSpec
    info: JobInfo
    done_evt: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None
    stop: bool = False
    inflight: set[asyncio.Future[Any]] = field(default_factory=set)
    started_mono: float = 0.0
    last_progress_mono: float = float("-inf")
    last_progress_done: int = -1
    announced: bool = False  # job.finished published


def _err(e: BaseException) -> str:
    return f"{type(e).__name__}: {e}"


class JobManager:
    def __init__(self, bus: EventBus, workers: int = 2, *, inline: bool = False) -> None:
        """`inline=True` (tests) runs units in a thread instead of worker processes."""
        self.bus = bus
        self.workers = max(1, workers)
        self.inline = inline
        self._executor: Executor | None = None
        self._closing = False
        self._shut_down = False
        self._jobs: dict[str, _Job] = {}
        self._terminal: deque[str] = deque()
        # Called with the final JobInfo after `job.finished` (e.g. the cache budget, AUD-A4-16)
        self.on_finished: list[Callable[[JobInfo], None]] = []

    async def start(self) -> None:
        asyncio.get_running_loop()  # must run inside the loop
        if self._executor is not None:
            return
        if self.inline:
            self._executor = ThreadPoolExecutor(self.workers, thread_name_prefix="job")
        else:
            self._executor = ProcessPoolExecutor(
                max_workers=self.workers, mp_context=multiprocessing.get_context("spawn")
            )

    async def shutdown(self) -> None:
        """Stop accepting jobs; running/queued jobs become `interrupted` (BE-13)."""
        if self._shut_down:
            return
        self._shut_down = True
        self._closing = True
        live = [j for j in self._jobs.values() if not j.done_evt.is_set()]
        for job in live:
            if job.info.status not in TERMINAL:
                self._set_terminal(job, "interrupted")
            self._halt(job)
        tasks = [j.task for j in live if j.task is not None and not j.task.done()]
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=SHUTDOWN_FINISH_TIMEOUT_S)
            for t in pending:
                t.cancel()
            if pending:
                log.warning("job finalizers timed out on shutdown", extra={"n": len(pending)})
                await asyncio.wait(pending, timeout=1.0)
        for job in live:
            self._announce(job)  # no-op for jobs whose task already did
        if live:
            log.info("jobs interrupted on shutdown", extra={"n": len(live)})
        ex, self._executor = self._executor, None
        if ex is not None:
            ex.shutdown(wait=False, cancel_futures=True)

    def submit(self, spec: JobSpec) -> JobInfo:
        """Schedule; raises JobConflict if `spec.exclusive` and (project, kind[, key]) is active."""
        if self._closing or self._executor is None:
            raise ServerBusy("Job manager is not accepting jobs")
        if spec.exclusive:
            cur = self.active(spec.project_id, spec.kind, spec.key)
            if cur is not None:
                raise JobConflict(f"A {spec.kind} job is already active: {cur.job_id}")
        job_id = spec.job_id or new_ulid()
        if job_id in self._jobs:
            raise JobConflict(f"Job id already exists: {job_id}")
        info = JobInfo(
            job_id=job_id,
            kind=spec.kind,
            project_id=spec.project_id,
            status="queued",
            total=len(spec.units),
            created_at=utc_now(),
            key=spec.key,
        )
        job = _Job(spec=spec, info=info)
        self._jobs[job_id] = job
        job.task = asyncio.get_running_loop().create_task(self._run(job), name=f"job-{job_id}")
        log.info("job queued", extra={"job_id": job_id, "kind": spec.kind, "total": info.total})
        return info

    def get(self, job_id: str) -> JobInfo:
        job = self._jobs.get(job_id)
        if job is None:
            raise NotFound(f"Job not found: {job_id}")
        return job.info

    def list(self, project_id: str | None = None) -> list[JobInfo]:
        """Newest first."""
        return [
            j.info
            for j in reversed(self._jobs.values())
            if project_id is None or j.info.project_id == project_id
        ]

    def active(self, project_id: str, kind: JobKind, key: str | None = None) -> JobInfo | None:
        for j in self._jobs.values():
            i = j.info
            live = i.project_id == project_id and i.kind == kind and i.status not in TERMINAL
            if live and (key is None or i.key == key):
                return i
        return None

    def busy(self, project_id: str) -> JobInfo | None:
        """Any live job of the project, whatever its kind (PRJ-06: no archive while one runs)."""
        for j in self._jobs.values():
            if j.info.project_id == project_id and j.info.status not in TERMINAL:
                return j.info
        return None

    def cancel(self, job_id: str) -> JobInfo:
        job = self._jobs.get(job_id)
        if job is None:
            raise NotFound(f"Job not found: {job_id}")
        if job.info.status in TERMINAL:
            return job.info
        self._set_terminal(job, "cancelled")
        self._halt(job)
        log.info("job cancelled", extra={"job_id": job_id, "kind": job.info.kind})
        return job.info

    async def wait(self, job_id: str, timeout: float | None = None) -> JobInfo:
        """Returns once the job is terminal and `on_finish` has run; asyncio.TimeoutError."""
        job = self._jobs.get(job_id)
        if job is None:
            raise NotFound(f"Job not found: {job_id}")
        await asyncio.wait_for(job.done_evt.wait(), timeout)
        return job.info

    async def run_in_worker(self, fn: Callable[..., Any], *args: Any) -> Any:
        """One-off worker call outside job tracking (e.g. npy→NIfTI conversion, IMP-10)."""
        if self._closing or self._executor is None:
            raise ServerBusy("Job manager is not accepting work")
        return await asyncio.get_running_loop().run_in_executor(self._executor, fn, *args)

    # -- internals -------------------------------------------------------------------------

    async def _run(self, job: _Job) -> None:
        spec, info = job.spec, job.info
        try:
            if not job.stop:
                info.status = "running"
                info.started_at = utc_now()
                job.started_mono = time.monotonic()
                self._progress(job)
                if spec.driver is not None:
                    await self._drive(job)
                else:
                    await self._execute(job)
            if info.status not in TERMINAL:
                self._set_terminal(job, "succeeded")
            self._progress(job, force=True)
            ref: str | None = None
            if spec.on_finish is not None:
                try:
                    ref = await spec.on_finish(info)
                except Exception as e:
                    log.exception("job on_finish failed", extra={"job_id": info.job_id})
                    if info.status != "interrupted":
                        info.status = "failed"
                        info.error = info.error or _err(e)
            info.ref = ref or spec.ref
        finally:
            if info.status not in TERMINAL:  # task cancelled mid-way
                self._set_terminal(job, "interrupted")
            self._halt(job)
            self._announce(job)

    async def _execute(self, job: _Job) -> None:
        spec, info = job.spec, job.info
        loop = asyncio.get_running_loop()
        units: Iterator[Any] = iter(spec.units)
        exhausted = False
        try:
            while not job.stop:
                while not exhausted and not job.stop and len(job.inflight) < self.workers:
                    unit = next(units, None)
                    if unit is None:
                        exhausted = True
                        break
                    if self._executor is None:
                        raise ServerBusy("Job manager is shut down")
                    job.inflight.add(loop.run_in_executor(self._executor, unit.fn, *unit.args))
                if not job.inflight:
                    break
                done, _ = await asyncio.wait(job.inflight, return_when=asyncio.FIRST_COMPLETED)
                for fut in done:
                    job.inflight.discard(fut)
                    if job.stop or fut.cancelled():
                        continue
                    result = fut.result()
                    if spec.on_result is not None:
                        await spec.on_result(result)
                    if job.stop:
                        continue
                    info.done += 1
                    self._progress(job)
        except Exception as e:
            if info.status not in TERMINAL:
                self._set_terminal(job, "failed")
                info.error = _err(e)
                log.warning(
                    "job failed", extra={"job_id": info.job_id, "kind": info.kind, "error": _err(e)}
                )
            self._halt(job)

    async def _drive(self, job: _Job) -> None:
        assert job.spec.driver is not None
        try:
            await job.spec.driver(_Handle(self, job))
        except Exception as e:
            if job.info.status not in TERMINAL:
                self._set_terminal(job, "failed")
                job.info.error = _err(e)
                log.warning("job driver failed", extra={"job_id": job.info.job_id})

    def _set_status(self, job: _Job, status: JobStatus) -> None:
        if job.info.status in TERMINAL or job.info.status == status:
            return
        job.info.status = status
        self.bus.publish(
            job.info.project_id, "job.status", {"job_id": job.info.job_id, "status": status}
        )

    def _halt(self, job: _Job) -> None:
        job.stop = True
        for fut in job.inflight:
            fut.cancel()  # not-started units are dropped; running ones finish, result ignored
        job.inflight.clear()

    def _set_terminal(self, job: _Job, status: JobStatus) -> None:
        job.info.status = status
        job.info.finished_at = utc_now()

    def _progress(self, job: _Job, *, force: bool = False) -> None:
        info = job.info
        if info.done > 0 and job.started_mono:
            elapsed = time.monotonic() - job.started_mono
            info.eta_s = round(elapsed / info.done * max(info.total - info.done, 0), 3)
        now = time.monotonic()
        if force:
            if info.done == job.last_progress_done:
                return
        elif now - job.last_progress_mono < PROGRESS_INTERVAL_S:
            return
        job.last_progress_mono = now
        job.last_progress_done = info.done
        self.bus.publish(
            info.project_id,
            "job.progress",
            {
                "job_id": info.job_id,
                "kind": info.kind,
                "done": info.done,
                "total": info.total,
                "eta_s": info.eta_s,
            },
        )

    def _announce(self, job: _Job) -> None:
        if job.announced:
            return
        job.announced = True
        info = job.info
        self.bus.publish(
            info.project_id,
            "job.finished",
            {"job_id": info.job_id, "kind": info.kind, "status": info.status, "ref": info.ref},
        )
        log.info(
            "job finished",
            extra={"job_id": info.job_id, "kind": info.kind, "status": info.status},
        )
        job.done_evt.set()
        for hook in self.on_finished:
            try:
                hook(info)
            except Exception:
                log.exception("job finished hook failed", extra={"job_id": info.job_id})
        self._terminal.append(info.job_id)
        while len(self._terminal) > KEEP_TERMINAL:
            self._jobs.pop(self._terminal.popleft(), None)


class _Handle:
    """`JobHandle` for driver jobs (see `JobSpec.driver`)."""

    def __init__(self, manager: JobManager, job: _Job) -> None:
        self._m = manager
        self._job = job

    @property
    def stopped(self) -> bool:
        return self._job.stop

    def set_total(self, total: int) -> None:
        self._job.info.total = total
        self._m._progress(self._job, force=True)

    def set_done(self, done: int) -> None:
        if done != self._job.info.done:
            self._job.info.done = done
            self._m._progress(self._job)

    def set_status(self, status: JobStatus) -> None:
        self._m._set_status(self._job, status)

    async def run_in_worker(self, fn: Callable[..., Any], *args: Any) -> Any:
        return await self._m.run_in_worker(fn, *args)
