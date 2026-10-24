"""D17/D22/D27: owned DICOM attempts serialize and retain unconfirmed allocations."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.fsio import atomic_write_json, read_json
from app.tasks import protocol
from app.tasks.dicom_execution import run_dicom_job
from app.tasks.dicom_process import process_identity
from tools.dicom_fixtures import write_series


def test_waiting_attempt_can_cancel_without_launching_or_touching_the_owner(tmp_path: Path) -> None:
    source, workspace = tmp_path / "source", tmp_path / "workspace"
    write_series(source, shape=(3, 3, 3), marker=(1, 1, 2))
    first, second, third = [workspace / "attempts" / str(n) for n in range(3)]
    for job in (first, second, third):
        protocol.write_job(job, {"operation": "inventory", "source": str(source), "attempt": 1})

    async def scenario() -> None:
        started = asyncio.Event()

        def hold(pid: int) -> None:
            os.kill(pid, signal.SIGSTOP)
            started.set()

        active = asyncio.create_task(run_dicom_job(first, workspace=workspace, on_started=hold))
        try:
            await asyncio.wait_for(started.wait(), timeout=5)
            stop = False
            waiting = asyncio.create_task(
                run_dicom_job(second, workspace=workspace, cancelled=lambda: stop)
            )
            await asyncio.sleep(0.2)
            assert not (second / "process.json").exists()
            assert read_json(workspace / "plugins/dicom/execution.json")["job"] == str(first)
            stop = True
            outcome = await asyncio.wait_for(waiting, timeout=2)
            assert outcome["cancelled"] and outcome["cleanup_verified"]
            active.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await active
            assert read_json(first / protocol.EXIT)["cleanup_verified"]
            assert not (workspace / "plugins/dicom/execution.json").exists()
            fresh = await run_dicom_job(third, workspace=workspace)
            assert fresh["cleanup_verified"] and fresh["exit_code"] == 0
        finally:
            if not active.done():
                active.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await active

    asyncio.run(scenario())


def test_unknown_prior_cleanup_blocks_replacement_and_never_signals_it(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    first, second = workspace / "first", workspace / "second"
    first.mkdir(parents=True)
    protocol.write_job(second, {"operation": "inventory", "source": str(tmp_path), "attempt": 2})
    sentinel = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True
    )
    try:
        atomic_write_json(first / "process.json", {**process_identity(sentinel.pid), "attempt": 1})
        lease = workspace / "plugins/dicom/execution.json"
        atomic_write_json(lease, {"job": str(first), "attempt": 1})
        saved = lease.read_bytes()

        async def scenario() -> None:
            stop = False
            waiting = asyncio.create_task(
                run_dicom_job(second, workspace=workspace, cancelled=lambda: stop)
            )
            await asyncio.sleep(0.2)
            assert not waiting.done() and not (second / "launch.json").exists()
            stop = True
            result = await asyncio.wait_for(waiting, timeout=2)
            assert result["cancelled"] and result["cleanup_verified"]

        asyncio.run(scenario())
        assert sentinel.poll() is None and lease.read_bytes() == saved
    finally:
        sentinel.terminate()
        sentinel.wait(timeout=5)


@pytest.mark.parametrize("missing", ["boot", "start", "pid", "group"])
def test_incomplete_owner_is_not_verified_cleanup(tmp_path: Path, missing: str) -> None:
    from app.tasks.dicom_execution import attempt_cleaned

    job = tmp_path / "attempt"
    job.mkdir()
    owner = {**process_identity(os.getpid()), "attempt": 1}
    owner.pop(missing)
    atomic_write_json(job / "process.json", owner)
    assert not attempt_cleaned(job, 1)
