"""Restart evidence and recovery for durable DICOM source operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.errors import NotFound
from app.tasks.dicom_execution import attempt_cleaned
from app.tasks.models import TaskRunStatus
from app.tasks.source_models import SourceOperation

if TYPE_CHECKING:
    from app.tasks.source_operations import SourceOperations

ACTIVE = {"queued", "running", "cancelling"}


def execution_state(operations: SourceOperations, record: SourceOperation) -> tuple[bool, bool]:
    attempt = operations._attempt_dir(record)
    retained = any(
        (attempt / name).exists() for name in ("launch.json", "process.json", "dispatch")
    )
    cleaned = attempt_cleaned(attempt, record.attempt) if record.job_id or retained else True
    return retained, cleaned


async def recover_source(operations: SourceOperations, record: SourceOperation) -> SourceOperation:
    info = None
    if record.job_id:
        try:
            info = operations.jobs.get(record.job_id)
            if info.status not in {"failed", "cancelled", "interrupted"}:
                return record
            await operations.jobs.wait(record.job_id, timeout=0.01)
        except NotFound:
            info = None
        except TimeoutError:
            return record
    current = operations.get(record.operation_id)
    if (
        current.attempt != record.attempt
        or current.job_id != record.job_id
        or current.status not in ACTIVE | {"cleanup_pending"}
    ):
        return current
    _, cleaned = execution_state(operations, current)
    status: TaskRunStatus
    if not cleaned:
        status = "cleanup_pending"
    elif info and info.status == "cancelled":
        status = "cancelled"
    elif info and info.status == "failed":
        status = "failed"
    else:
        status = "interrupted"
    error = None if status == "cancelled" else current.error
    if status != "cancelled" and (not error or current.status == "cleanup_pending"):
        error = (
            "Source work stopped; verify its source/storage and resume"
            if cleaned
            else "Source cleanup is not yet verified"
        )
    if (current.status, current.cleanup_verified, current.error) != (status, cleaned, error):
        current.status, current.cleanup_verified, current.error = status, cleaned, error
        operations._write(current)
    return current


async def recover_all(operations: SourceOperations) -> None:
    for record in operations.list():
        if record.status not in ACTIVE | {"cleanup_pending"}:
            continue
        attempt = operations._attempt_dir(record)
        cleaned = attempt_cleaned(attempt, record.attempt)
        if record.status == "queued" and not (attempt / "launch.json").exists():
            cleaned = True
        record.status = "interrupted" if cleaned else "cleanup_pending"
        record.cleanup_verified = cleaned
        record.error = "Backend interrupted; resume after verified cleanup"
        operations._write(record)
