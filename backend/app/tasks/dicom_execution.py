"""BE-16: serialize owned DICOM attempts and retain admission until cleanup is proved."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

from app.config import Settings
from app.core.fsio import append_jsonl, atomic_write_json, read_json
from app.core.locks import FileLock, LockHeldError
from app.tasks import protocol
from app.tasks.dicom_process import group_running, process_identity, run_dicom_worker


def _valid_identity(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if any(type(value.get(k)) is not int or value[k] < 1 for k in ("pid", "group")):
        return False
    if not isinstance(value.get("start"), str) or not value["start"].isdigit():
        return False
    if not isinstance(value.get("namespace"), str) or not value["namespace"].startswith("pid:["):
        return False
    try:
        UUID(value["boot"])
    except (KeyError, ValueError, TypeError, AttributeError):
        return False
    return True


def attempt_cleaned(job: Path, attempt: int) -> bool:
    """Reconcile durable evidence, including a crash before the dispatch handshake."""
    try:
        outcome = protocol.read_exit(job)
        if (
            outcome
            and outcome.get("attempt") == attempt
            and outcome.get("cleanup_verified") is True
        ):
            return True
        if (job / "process.json").exists():
            owner = read_json(job / "process.json")
            if owner.get("attempt") != attempt or not _valid_identity(owner):
                return False
            boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
            if owner["boot"] != boot:
                return True
            if owner["namespace"] != os.readlink("/proc/self/ns/pid"):
                return False
            return not group_running(int(owner["group"]))
        if (job / "dispatch").exists():
            return False
        if (job / "launch.json").exists():
            launch = read_json(job / "launch.json")
            if launch.get("attempt") != attempt:
                return False
            parent = launch["parent"]
            if not _valid_identity(parent):
                return False
            try:
                return bool(process_identity(int(parent["pid"])) != parent)
            except (FileNotFoundError, ProcessLookupError):
                return True
        if (job / "reserved.json").exists():
            return bool(read_json(job / "reserved.json").get("attempt") == attempt)
        spec = read_json(job / protocol.JOB)
        return bool(spec.get("dicom_process_protocol") == 1 and spec.get("attempt", 1) == attempt)
    except (OSError, ValueError, KeyError, TypeError):
        return False


async def run_dicom_job(
    job: Path,
    *,
    workspace: Path,
    cancelled: Callable[[], bool] = lambda: False,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    on_started: Callable[[int], None] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    from app.tasks.dicom_allocation import HostAllocation
    from app.tasks.dicom_resources import require_pixel_budget

    config = settings or Settings(workspace_root=workspace, _env_file=None)  # type: ignore[call-arg]
    root = workspace / "plugins" / "dicom"
    lock = FileLock(root / "execution.lock")
    lease = root / "execution.json"
    spec = read_json(job / protocol.JOB)
    if spec.get("operation") == "open" or (
        spec.get("operation", "task") == "task" and spec.get("mode") != "estimate"
    ):
        require_pixel_budget(config)
    atomic_write_json(job / "resources.json", config.dicom_limits)
    atomic_write_json(job / "timing-history-path.json", {"path": str(root / "timing-history.json")})
    attempt = int(spec.get("attempt", 1))
    atomic_write_json(job / "reserved.json", {"attempt": attempt})
    allocation = HostAllocation(config, job, attempt)
    last_wait = 0.0

    def waiting(reason: str) -> None:
        nonlocal last_wait
        if time.monotonic() - last_wait < 1:
            return
        last_wait = time.monotonic()
        row = {
            "t": "stage",
            "stage": "waiting_for_resources",
            "done": 0,
            "total": 0,
            "resource_wait": {
                "reason": reason,
                "remedy": "configure:HOST_ALLOCATION_ROOT"
                if reason == "runner_policy_mismatch"
                else "wait:host_allocation",
            },
        }
        append_jsonl(job / protocol.PROGRESS, [row])
        if on_progress is not None:
            on_progress(row)

    while True:
        if cancelled() or (job / protocol.CANCEL).exists():
            result = {
                "attempt": attempt,
                "exit_code": -15,
                "cancelled": True,
                "cleanup_verified": True,
            }
            atomic_write_json(job / protocol.EXIT, result)
            return result
        try:
            lock.acquire()
        except LockHeldError:
            waiting("dicom_allocation")
            await asyncio.sleep(0.1)
            continue
        try:
            if lease.exists():
                old = read_json(lease)
                if not attempt_cleaned(Path(old["job"]), int(old["attempt"])):
                    lock.release()
                    waiting("cleanup_pending")
                    await asyncio.sleep(0.1)
                    continue
            if not allocation.acquire():
                lock.release()
                waiting(allocation.blocked_reason)
                await asyncio.sleep(0.1)
                continue
            break
        except BaseException:
            lock.release()
            raise
    try:
        append_jsonl(
            job / protocol.PROGRESS, [{"t": "stage", "stage": "admitted", "done": 0, "total": 0}]
        )
        atomic_write_json(lease, {"job": str(job), "attempt": attempt})
        outcome = await run_dicom_worker(
            job,
            cancelled=cancelled,
            on_progress=on_progress,
            on_started=on_started,
            grace_s=config.dicom_cleanup_seconds,
        )
    finally:
        # Retain the persistent lease if a process or its cleanup is still unknown.
        if attempt_cleaned(job, attempt):
            for _ in range(10):
                if allocation.release():
                    atomic_write_json(job / "allocation-exit.json", {"attempt": attempt})
                    lease.unlink(missing_ok=True)
                    break
                await asyncio.sleep(0.05)
        lock.release()
    result = protocol.read_result(job) or {}
    if outcome["cleanup_verified"] and result.get("resource_wait"):
        row = {
            "t": "stage",
            "stage": "waiting_for_resources",
            "done": 0,
            "total": 0,
            "resource_wait": result["resource_wait"],
        }
        append_jsonl(job / protocol.PROGRESS, [row])
        if on_progress is not None:
            on_progress(row)
        while not cancelled() and not (job / protocol.CANCEL).exists():
            await asyncio.sleep(0.1)
        return {**outcome, "cancelled": True}
    return outcome
