"""BE-16: one owned in-image process group per DICOM attempt; never kills a shared pool."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.core.fsio import atomic_write_json, read_json
from app.tasks import protocol


def process_identity(pid: int) -> dict[str, Any]:
    """PID plus kernel start identity prevents recovery from signalling a recycled PID."""
    stat = Path(f"/proc/{pid}/stat").read_text().rpartition(") ")[2].split()
    return {
        "pid": pid,
        "start": stat[19],
        "group": int(stat[2]),
        "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "namespace": os.readlink(f"/proc/{pid}/ns/pid"),
    }


def group_running(group: int) -> bool:
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    for path in Path("/proc").iterdir():
        if not path.name.isdecimal():
            continue
        try:
            fields = (path / "stat").read_text().rpartition(") ")[2].split()
            if int(fields[2]) == group and fields[0] not in {"Z", "X"}:
                return True
        except (OSError, ValueError, IndexError):
            continue
    return False


def signal_owned(identity: dict[str, Any], sig: signal.Signals) -> None:
    """Signal only the process group whose leader still has the recorded identity."""
    try:
        if process_identity(int(identity["pid"])) != identity:
            raise RuntimeError("DICOM worker process identity changed; cleanup is unconfirmed")
        os.killpg(int(identity["group"]), sig)
    except (ProcessLookupError, FileNotFoundError):
        return


async def _stop_group(identity: dict[str, Any]) -> bool:
    if not group_running(identity["group"]):
        return True
    try:
        current = process_identity(identity["pid"])
    except FileNotFoundError:
        return False  # a group number without its pinned leader is not ownership proof
    if current != identity:
        return False
    with contextlib.suppress(ProcessLookupError):
        os.killpg(identity["group"], signal.SIGKILL)
    for _ in range(20):
        if not group_running(identity["group"]):
            return True
        await asyncio.sleep(0.05)
    return False


async def run_dicom_worker(
    job_dir: Path,
    *,
    cancelled: Callable[[], bool] = lambda: False,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    on_started: Callable[[int], None] | None = None,
    grace_s: float = 30.0,
) -> dict[str, Any]:
    if not 0 < grace_s <= 30:
        raise ValueError("DICOM cleanup grace must be in (0, 30] seconds")
    spec = read_json(job_dir / protocol.JOB)
    atomic_write_json(
        job_dir / "launch.json",
        {"parent": process_identity(os.getpid()), "attempt": spec.get("attempt", 1)},
    )
    backend = Path(__file__).resolve().parents[2]
    env = {
        **os.environ,
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS": "1",
        "PYTHONPATH": os.pathsep.join([str(backend), str(backend.parent)]),
    }
    with (job_dir / protocol.LOG).open("ab", buffering=0) as log:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "app.tasks.dicom_worker",
            str(job_dir),
            cwd=backend,
            env=env,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    identity = process_identity(process.pid)
    ownership = {**identity, "attempt": spec.get("attempt", 1)}
    tail = protocol.Tail(job_dir / protocol.PROGRESS)
    deadline = None
    requested = False
    dispatched = False
    waiter = asyncio.create_task(process.wait())
    try:
        atomic_write_json(job_dir / "process.json", ownership)
        while process.returncode is None:
            if not dispatched and (job_dir / "worker-ready.json").exists():
                ready = read_json(job_dir / "worker-ready.json")
                if ready.get("pid") != process.pid:
                    raise RuntimeError("DICOM worker startup identity is inconsistent")
                stopping = cancelled() or (job_dir / protocol.CANCEL).exists()
                if not stopping and on_started is not None:
                    on_started(process.pid)
                # The native worker cannot start before ownership and parent-death cleanup.
                if stopping or cancelled() or (job_dir / protocol.CANCEL).exists():
                    requested = True
                    signal_owned(identity, signal.SIGKILL)
                else:
                    atomic_write_json(job_dir / "dispatch", {"pid": process.pid})
                dispatched = True
            if (cancelled() or (job_dir / protocol.CANCEL).exists()) and not requested:
                requested = True
                protocol.request_cancel(job_dir)
                deadline = time.monotonic() + grace_s
            if deadline is not None and time.monotonic() >= deadline:
                signal_owned(identity, signal.SIGKILL)
                deadline = None
                try:
                    await asyncio.wait_for(asyncio.shield(waiter), timeout=1)
                except TimeoutError:
                    break  # uninterruptible I/O: return cleanup_pending evidence, not success
            if on_progress is not None:
                for row in tail.read():
                    on_progress(row)
            try:
                await asyncio.wait_for(asyncio.shield(waiter), timeout=0.1)
            except TimeoutError:
                continue
        if on_progress is not None:
            for row in tail.read():
                on_progress(row)
    except BaseException:
        cleanup = await _stop_group(identity)
        try:
            await asyncio.wait_for(asyncio.shield(waiter), timeout=1)
        except TimeoutError:
            cleanup = False
        atomic_write_json(
            job_dir / protocol.EXIT,
            {
                **ownership,
                "exit_code": process.returncode,
                "interrupted": True,
                "cleanup_verified": cleanup,
            },
        )
        raise
    cleanup = not group_running(identity["group"])
    if not cleanup:
        cleanup = await _stop_group(identity)
    outcome = {
        **ownership,
        "exit_code": process.returncode,
        "cancelled": requested,
        "cleanup_verified": cleanup,
    }
    atomic_write_json(job_dir / protocol.EXIT, outcome)
    return outcome
