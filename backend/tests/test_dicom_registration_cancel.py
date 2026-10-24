"""D16/D20/U09/B06: durable registration cancellation never reconverts pixels."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.ingest import indexer
from app.jobs.manager import JobManager
from app.main import create_app
from app.tasks import registration
from tests.test_api_ingest import ctx_of, wait
from tests.test_dicom_resume import digest
from tests.test_source_operation_conversion import native_run, prepared_operation
from tests.test_source_operations_api import API


@pytest.mark.parametrize("barrier", ["before_import", "before_dispatch", "during_probe"])
@pytest.mark.parametrize("lost_response", [None, "before", "after"])
def test_cancel_registration_drains_then_resumes_only_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, barrier: str, lost_response: str | None
) -> None:
    original_execute, original_probe = JobManager._execute, indexer.probe_batch
    original_hash = registration.sha256_file
    entered, release_thread = threading.Event(), threading.Event()
    release_loop = asyncio.Event()

    async def execute(manager: Any, job: Any) -> None:
        if job.info.kind == "index" and barrier == "before_dispatch":
            entered.set()
            await release_loop.wait()
        await original_execute(manager, job)

    def probe(*args: Any) -> Any:
        if barrier == "during_probe":
            entered.set()
            assert release_thread.wait(10)
        return original_probe(*args)

    def hash_output(path: Path) -> str:
        if barrier == "before_import" and path.name.endswith(".nii.gz"):
            entered.set()
            assert release_thread.wait(10)
        return original_hash(path)

    monkeypatch.setattr(JobManager, "_execute", execute)
    monkeypatch.setattr(indexer, "probe_batch", probe)
    monkeypatch.setattr(registration, "sha256_file", hash_output)
    with prepared_operation(tmp_path, True) as prepared:
        client, _, source, derived, record, request = prepared
        oid, pid = record["operation_id"], record["project_id"]
        inputs = {p: digest(p) for p in source.rglob("*") if p.is_file()}
        assert client.post(f"{API}/{oid}/convert", json=request).status_code == 202
        native = native_run(client, oid)
        requests = ThreadPoolExecutor(max_workers=1)
        try:
            assert entered.wait(10)
            before = {
                p: (digest(p), p.stat().st_mtime_ns)
                for p in derived.rglob("*.nii.gz")
                if p.is_file()
            }
            assert len(before) == 1
            operation = client.get(f"{API}/{oid}").json()
            command = {
                "expected_revision": operation["revision"],
                "expected_attempt": operation["attempt"],
                "expected_run_attempt": 1,
            }
            service = ctx_of(client).source_operations.tasks
            original_cancel = service.cancel

            async def lose(*args: Any, **kwargs: Any) -> Any:
                if lost_response == "before":
                    raise OSError("Lost cancellation response")
                await original_cancel(*args, **kwargs)
                raise OSError("Lost cancellation response")

            if lost_response:
                with monkeypatch.context() as fault:
                    fault.setattr(service, "cancel", lose)
                    with pytest.raises(OSError, match="Lost cancellation response"):
                        client.post(f"{API}/{oid}/cancel", json=command)
            response = requests.submit(client.post, f"{API}/{oid}/cancel", json=command).result(1)
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "cancelling", response.json()
            assert client.post(f"{API}/{oid}/cancel", json=command).json()["status"] == "cancelling"
            current = client.get(f"{API}/{oid}").json()
            early_resume = {
                "expected_revision": current["revision"],
                "expected_attempt": current["attempt"],
                "expected_run_attempt": 1,
            }
            assert client.post(f"{API}/{oid}/resume", json=early_resume).status_code == 409
        finally:
            release_thread.set()
            client.portal.call(release_loop.set)
            requests.shutdown(wait=True)
        wait(client, native["job_id"])
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            stopped = client.get(f"{API}/{oid}").json()
            if stopped["status"] == "cancelled":
                break
            time.sleep(0.01)
        assert stopped["status"] == "cancelled" and stopped["error"] is None, stopped
        assert client.get(f"/api/v1/projects/{pid}/items").json()["total"] == 0
        if barrier == "before_import":
            jobs = client.get(f"/api/v1/jobs?project={pid}").json()
            assert not [job for job in jobs if job["kind"] == "index"]
        assert before == {p: (digest(p), p.stat().st_mtime_ns) for p in before}
        resume = {
            "expected_revision": stopped["revision"],
            "expected_attempt": stopped["attempt"],
            "expected_run_attempt": 1,
        }
        resumed = client.post(f"{API}/{oid}/resume", json=resume)
        assert resumed.status_code == 202, resumed.text
        from tests.test_dicom_registration import wait_registration

        restored = wait_registration(client, pid, native["run_id"])
        assert restored["error"] is None and restored["status"] == "completed", restored
        assert restored["attempts"] == 1 and restored["job_id"] == native["job_id"]
        assert client.get(f"{API}/{oid}").json()["status"] == "completed"
        assert client.post(f"{API}/{oid}/resume", json=resume).status_code == 202
        assert client.get(f"/api/v1/projects/{pid}/items").json()["total"] == 1
        assert len(client.get(f"/api/v1/projects/{pid}/imports").json()["items"]) == 1
        assert before == {p: (digest(p), p.stat().st_mtime_ns) for p in before}
        assert inputs == {p: digest(p) for p in source.rglob("*") if p.is_file()}


def cancelled_registration_child(root: Path) -> None:
    """Kill a disposable API after acknowledging cancellation, before metadata drain finishes."""
    original = JobManager._execute
    entered = threading.Event()

    async def execute(manager: Any, job: Any) -> None:
        if job.info.kind == "index":
            entered.set()
            await asyncio.Event().wait()
        await original(manager, job)

    JobManager._execute = execute
    with prepared_operation(root, True) as prepared:
        client, _, _, _, record, request = prepared
        oid = record["operation_id"]
        assert client.post(f"{API}/{oid}/convert", json=request).status_code == 202
        native = native_run(client, oid)
        assert entered.wait(10)
        current = client.get(f"{API}/{oid}").json()
        command = {
            "expected_revision": current["revision"],
            "expected_attempt": current["attempt"],
            "expected_run_attempt": 1,
        }
        response = client.post(f"{API}/{oid}/cancel", json=command)
        assert response.status_code == 200 and response.json()["status"] == "cancelling"
        (root / "cancelled.json").write_text(json.dumps({"native": native, "operation": oid}))
        os.kill(os.getpid(), signal.SIGKILL)


def test_acknowledged_registration_cancel_survives_api_sigkill(tmp_path: Path) -> None:
    """D16/D20: restart reconciles cancellation without launching a new pixel attempt."""
    code = (
        "from pathlib import Path; import sys; "
        "from tests.test_dicom_registration_cancel import cancelled_registration_child; "
        "cancelled_registration_child(Path(sys.argv[1]))"
    )
    process = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert process.returncode == -signal.SIGKILL, process.stdout + process.stderr
    saved = json.loads((tmp_path / "cancelled.json").read_text())
    native, oid = saved["native"], saved["operation"]
    before = {
        p: (digest(p), p.stat().st_mtime_ns)
        for p in (tmp_path / "derived").rglob("*.nii.gz")
        if p.is_file()
    }
    assert len(before) == 1
    settings = Settings(
        workspace_root=tmp_path / "workspace",
        allowed_data_roots=str(tmp_path / "source"),
        allowed_derived_roots=str(tmp_path / "derived"),
        dicom_memory_mb=1024,
        _env_file=None,
    )  # type: ignore[call-arg]
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            stopped = client.get(f"{API}/{oid}").json()
            if stopped["status"] == "cancelled":
                break
            time.sleep(0.01)
        assert stopped["status"] == "cancelled" and stopped["error"] is None, stopped
        assert stopped["conversion_run"]["job_id"] == native["job_id"]
        command = {
            "expected_revision": stopped["revision"],
            "expected_attempt": stopped["attempt"],
            "expected_run_attempt": 1,
        }
        response = client.post(f"{API}/{oid}/resume", json=command)
        assert response.status_code == 202, response.text
        from tests.test_dicom_registration import wait_registration

        restored = wait_registration(client, stopped["project_id"], native["run_id"])
        assert restored["status"] == "completed" and restored["error"] is None, restored
        assert restored["attempts"] == 1 and restored["job_id"] == native["job_id"]
        assert before == {p: (digest(p), p.stat().st_mtime_ns) for p in before}
