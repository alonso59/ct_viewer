"""API-owned requests and acknowledgements of verified external cleanup."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

from app.core.errors import JobConflict
from app.core.fsio import atomic_write_json
from app.core.ids import new_ulid, utc_now
from app.jobs.types import TERMINAL
from app.tasks import protocol
from app.tasks.models import TERMINAL_TASK_RUN, TaskControl, TaskRunDetail, TaskRunRecord

if TYPE_CHECKING:
    from app.tasks.service import TaskService

PAUSE_GRACE_S: Final = 10.0  # in-flight batch deadline before the worker interrupts it
STOPPING: Final = frozenset({"pausing", "cancelling", "cleanup_pending"})


def pending(rec: TaskRunRecord) -> bool:
    return rec.control is not None and rec.control.acknowledged_at is None


def cleanup_confirmed(job: Path) -> bool:
    if protocol.read_claim(job) is None and not (job / "attempt.json").exists():
        return (job / "pause").exists() or (job / "cancel").exists()
    return protocol.external_finished(job)


def acknowledge(rec: TaskRunRecord, job: Path) -> bool:
    """Settle the pending request once the supervisor verified cleanup of the same attempt."""
    request = rec.control
    if request is None or request.acknowledged_at is not None:
        return request is not None
    if not cleanup_confirmed(job):
        return False
    attempt = protocol.read_attempt(job)
    if request.attempt is not None and (attempt or {}).get("attempt") != request.attempt:
        return False
    request.acknowledged_at = utc_now()
    if request.action == "cancel":
        rec.status = "cancelled"
    elif rec.status not in ("completed", "completed_with_errors"):
        rec.status = "paused"
    return True


async def settle(svc: TaskService, pid: str, run_dir: Path) -> None:
    """`cleanup_pending` → paused/cancelled once the supervisor confirms it."""
    rec = svc.runs.read(run_dir)
    if rec.status != "cleanup_pending" or not pending(rec) or rec.job_id is None:
        return
    job = svc.runs.job(rec.job_id)
    if job is not None and job.status not in TERMINAL:
        return  # the live driver settles it
    async with svc.locks(pid):
        rec = svc.runs.read(run_dir)
        if rec.status == "cleanup_pending" and acknowledge(rec, svc.queue_dir / str(rec.job_id)):
            svc.runs.write(run_dir, rec)


async def request_control(
    svc: TaskService, pid: str, rid: str, action: Literal["pause", "cancel"]
) -> TaskRunDetail:
    run_dir = svc.runs.run_dir(pid, rid)
    await svc._recover_external(pid, run_dir)
    await settle(svc, pid, run_dir)
    async with svc.locks(pid):
        rec = svc.runs.read(run_dir)
        if not rec.supervised:
            raise JobConflict("This run does not support supervised controls")
        if rec.archived:
            raise JobConflict("Archived runs are read-only")
        if rec.status in TERMINAL_TASK_RUN:
            if action == "cancel" or rec.status == "paused":
                return TaskRunDetail(**rec.model_dump())
            raise JobConflict(f"Cannot {action} a {rec.status} run")
        if pending(rec):
            assert rec.control is not None
            if rec.control.action == action:
                return TaskRunDetail(**rec.model_dump())
            if rec.control.action == "cancel":
                raise JobConflict("Cancellation is already pending")
        if rec.job_id is None:
            raise JobConflict("Run has no external job identity")
        job = svc.queue_dir / rec.job_id
        attempt = protocol.read_attempt(job)
        rec.control = TaskControl(
            id=new_ulid(),
            action=action,
            job_id=rec.job_id,
            attempt=(attempt or {}).get("attempt"),
            requested_at=utc_now(),
            deadline_mono=time.monotonic() + (PAUSE_GRACE_S if action == "pause" else 0),
        )
        atomic_write_json(job / "control.json", rec.control.model_dump())
        (job / action).touch(exist_ok=True)
        if rec.status != "cleanup_pending":
            rec.status = "pausing" if action == "pause" else "cancelling"
        svc.runs.write(run_dir, rec)
    if action == "cancel" and svc.runs.job(rec.job_id) is not None:
        svc.jobs.cancel(rec.job_id)
    return await svc.get_run(pid, rid)


async def archive(svc: TaskService, pid: str, rid: str) -> TaskRunDetail:
    run_dir = svc.runs.run_dir(pid, rid)
    await svc._recover_external(pid, run_dir)
    await settle(svc, pid, run_dir)
    async with svc.locks(pid):
        rec = svc.runs.read(run_dir)
        job = svc.runs.job(rec.job_id)
        if (
            not rec.supervised
            or rec.status not in TERMINAL_TASK_RUN
            or (job and job.status not in TERMINAL)
        ):
            raise JobConflict("Only inactive supervised runs can be archived")
        queued = svc.queue_dir / rec.job_id if rec.job_id else None
        if (
            queued is not None
            and (queued / "attempt.json").exists()
            and not protocol.external_finished(queued)
        ):
            raise JobConflict("External cleanup is pending; archive is blocked")
        if not rec.archived:
            rec.archived = True
            svc.runs.write(run_dir, rec)
    return await svc.get_run(pid, rid)
