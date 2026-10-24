"""D17 / BE-16: actual owned DICOM processes terminate without touching unrelated work."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.fsio import read_json
from app.tasks import protocol
from app.tasks.dicom_process import run_dicom_worker
from tools.dicom_fixtures import write_series


def test_cleanup_never_signals_a_group_after_losing_its_leader_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D17/BE-16: a remaining group number alone cannot prove that its members are ours."""
    from app.tasks import dicom_process

    monkeypatch.setattr(dicom_process, "group_running", lambda group: True)

    def missing(pid: int) -> dict[str, object]:
        raise FileNotFoundError("leader was reaped")

    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(dicom_process, "process_identity", missing)
    monkeypatch.setattr(dicom_process.os, "killpg", lambda group, sig: signals.append((group, sig)))
    assert not asyncio.run(dicom_process._stop_group({"pid": 12345, "group": 12345}))
    assert not signals


def test_real_inventory_worker_persists_result_and_verified_cleanup(tmp_path: Path) -> None:
    root = tmp_path / "source"
    write_series(root / "nested" / "series", shape=(3, 3, 3), marker=(1, 1, 2))
    job = tmp_path / "workspace" / "attempt"
    protocol.write_job(job, {"source": str(root), "operation": "inventory", "attempt": 1})
    outcome = asyncio.run(run_dicom_worker(job))
    assert outcome["cleanup_verified"] and outcome["exit_code"] == 0
    result = read_json(job / "result.json")
    assert result["summary"]["complete"] and result["summary"]["dicom"] == 3
    assert outcome["attempt"] == 1
    assert read_json(job / "exit.json")["cleanup_verified"]


def test_cancel_stopped_native_worker_kills_only_its_process_group(tmp_path: Path) -> None:
    root = tmp_path / "source"
    write_series(root / "series", shape=(3, 3, 1), marker=(1, 1, 0))
    job = tmp_path / "workspace" / "attempt"
    protocol.write_job(job, {"source": str(root), "operation": "inventory", "attempt": 2})
    sentinel = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True
    )

    async def scenario() -> dict[str, object]:
        stopped = False

        def before_work(pid: int) -> None:
            nonlocal stopped
            os.kill(pid, signal.SIGSTOP)
            stopped = True

        return await run_dicom_worker(
            job, cancelled=lambda: stopped, grace_s=0.15, on_started=before_work
        )

    try:
        outcome = asyncio.run(scenario())
        assert outcome["cleanup_verified"] and outcome["cancelled"]
        assert outcome["exit_code"] == -signal.SIGKILL
        assert sentinel.poll() is None
        pid = int(outcome["pid"])
        assert not Path(f"/proc/{pid}").exists()
    finally:
        sentinel.terminate()
        sentinel.wait(timeout=5)


def test_driver_interruption_records_cleanup_before_propagating_cancel(tmp_path: Path) -> None:
    """D16/D17: a cancelled coroutine needs actual process exit proof before resume."""
    job = tmp_path / "attempt"
    protocol.write_job(job, {"source": str(tmp_path), "operation": "inventory", "attempt": 3})

    async def scenario() -> None:
        started = asyncio.Event()
        pid = 0

        def stop_before_work(worker_pid: int) -> None:
            nonlocal pid
            pid = worker_pid
            os.kill(pid, signal.SIGSTOP)
            started.set()

        driver = asyncio.create_task(run_dicom_worker(job, on_started=stop_before_work))
        await asyncio.wait_for(started.wait(), timeout=5)
        driver.cancel()
        try:
            await driver
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("The interrupted driver must propagate cancellation")
        outcome = read_json(job / protocol.EXIT)
        assert outcome["cleanup_verified"] and outcome["attempt"] == 3
        assert outcome["exit_code"] == -signal.SIGKILL
        assert not Path(f"/proc/{pid}").exists()

    asyncio.run(scenario())


def test_backend_death_cannot_leave_a_worker_at_the_launch_barrier(tmp_path: Path) -> None:
    """D16: abrupt API death after dispatch cannot leave a writer alive for resume."""
    import json
    import time

    from app.tasks.dicom_process import group_running, process_identity, signal_owned

    job = tmp_path / "attempt"
    protocol.write_job(job, {"source": str(tmp_path), "operation": "inventory", "attempt": 1})
    helper = tmp_path / "api_driver.py"
    helper.write_text(
        "import asyncio, os, signal, sys\n"
        "from pathlib import Path\n"
        "from app.core.fsio import atomic_write_json\n"
        "from app.tasks.dicom_process import run_dicom_worker\n"
        "job = Path(sys.argv[1])\n"
        "def stop(pid):\n"
        "    os.kill(pid, signal.SIGSTOP)\n"
        "    atomic_write_json(job / 'barrier.json', {'pid': pid})\n"
        "asyncio.run(run_dicom_worker(job, on_started=stop))\n"
    )
    backend = Path(__file__).resolve().parents[1]
    driver = subprocess.Popen(
        [sys.executable, str(helper), str(job)],
        env={**os.environ, "PYTHONPATH": os.pathsep.join([str(backend), str(backend.parent)])},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    owner = None
    try:
        deadline = time.monotonic() + 8
        while not (job / "barrier.json").exists() and time.monotonic() < deadline:
            assert driver.poll() is None
            time.sleep(0.01)
        pid = json.loads((job / "barrier.json").read_text())["pid"]
        owner = process_identity(pid)
        driver.kill()
        driver.wait(timeout=5)
        deadline = time.monotonic() + 3
        while group_running(owner["group"]) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not group_running(owner["group"]), "Worker survived its backend's SIGKILL"
    finally:
        if driver.poll() is None:
            driver.kill()
            driver.wait(timeout=5)
        if owner is not None:
            signal_owned(owner, signal.SIGKILL)
