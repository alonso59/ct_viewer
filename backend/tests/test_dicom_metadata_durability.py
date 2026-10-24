"""D35/API-69: failed directory synchronization cannot turn replay into a false acknowledgment."""

from __future__ import annotations

import asyncio
import errno
import hashlib
import os
import stat
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from app.core.fsio import atomic_write_json, read_json
from app.core.ids import is_ulid
from app.jobs.manager import JobManager
from tests.test_api_ingest import ctx_of, wait
from tests.test_dicom_resume import digest
from tests.test_source_operation_conversion import native_run, prepared_operation
from tests.test_source_operations_api import API, wait_operation


def fail_directory_sync(
    patch: pytest.MonkeyPatch, matches: Callable[[Path], bool], *, after: int = 1
) -> None:
    original = os.fsync
    calls = 0

    def sync(fd: int) -> None:
        nonlocal calls
        if stat.S_ISDIR(os.fstat(fd).st_mode) and matches(Path(os.readlink(f"/proc/self/fd/{fd}"))):
            calls += 1
            if calls >= after:
                raise OSError(errno.ENOSPC, "Synthetic directory synchronization failure")
        original(fd)

    patch.setattr(os, "fsync", sync)


@pytest.mark.parametrize("in_project", [False, True])
@pytest.mark.parametrize("barrier", ["receipt", "operation", "submission", "committed_receipt"])
def test_creation_replay_requires_durable_intent_and_dispatches_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, in_project: bool, barrier: str
) -> None:
    with prepared_operation(tmp_path, in_project) as prepared:
        client, _, source, derived, record, _ = prepared
        service = ctx_of(client).source_operations
        before = {r.operation_id for r in service.list()}
        inputs = {p: digest(p) for p in source.rglob("*") if p.is_file()}
        request = {
            "path": str(source),
            "project_id": record["project_id"],
            "idempotency_key": "durable-creation-replay-123",
        }

        def matches(directory: Path) -> bool:
            if barrier in {"receipt", "committed_receipt"}:
                return directory == service.root / "requests"
            return (
                directory.parent == service.root
                and is_ulid(directory.name)
                and directory.name not in before
            )

        with monkeypatch.context() as fault:
            fail_directory_sync(
                fault, matches, after=2 if barrier in {"submission", "committed_receipt"} else 1
            )
            for _ in range(2):
                with pytest.raises(OSError, match="directory synchronization failure"):
                    client.post(API, json=request)
        response = client.post(API, json=request)
        assert response.status_code == 202, response.text
        restored = wait_operation(client, response.json()["operation_id"])
        assert restored["status"] == "completed", restored
        assert restored["attempt"] == 1
        assert {r.operation_id for r in service.list()} - before == {restored["operation_id"]}
        jobs = client.get("/api/v1/jobs").json()
        assert len([j for j in jobs if j.get("key") == f"source:{restored['operation_id']}"]) == 1
        assert not list(derived.rglob("*.nii.gz"))
        assert inputs == {p: digest(p) for p in source.rglob("*") if p.is_file()}


def test_cancel_receipt_replay_cannot_acknowledge_an_unsynced_control(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = JobManager._execute
    entered, release = threading.Event(), asyncio.Event()

    async def execute(manager: Any, job: Any) -> None:
        if job.info.kind == "index":
            entered.set()
            await release.wait()
        await original(manager, job)

    monkeypatch.setattr(JobManager, "_execute", execute)
    with prepared_operation(tmp_path, True) as prepared:
        client, _, _, derived, record, request = prepared
        service = ctx_of(client).source_operations
        oid = record["operation_id"]
        assert client.post(f"{API}/{oid}/convert", json=request).status_code == 202
        native = native_run(client, oid)
        try:
            assert entered.wait(10)
            current = client.get(f"{API}/{oid}").json()
            command = {
                "expected_revision": current["revision"],
                "expected_attempt": current["attempt"],
                "expected_run_attempt": native["attempts"],
            }
            before = {
                p: (digest(p), p.stat().st_mtime_ns)
                for p in derived.rglob("*.nii.gz")
                if p.is_file()
            }
            assert len(before) == 1
            with monkeypatch.context() as fault:
                fail_directory_sync(fault, lambda d: d == service._dir(oid), after=2)
                for _ in range(2):
                    with pytest.raises(OSError, match="directory synchronization failure"):
                        client.post(f"{API}/{oid}/cancel", json=command)
            response = client.post(f"{API}/{oid}/cancel", json=command)
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "cancelling"
        finally:
            client.portal.call(release.set)
        wait(client, native["job_id"])
        stopped = client.get(f"{API}/{oid}").json()
        assert stopped["status"] == "cancelled", stopped
        assert stopped["conversion_run"]["attempts"] == native["attempts"]
        assert before == {p: (digest(p), p.stat().st_mtime_ns) for p in before}


@pytest.mark.parametrize("evidence", ["launch.json", "process.json", "dispatch"])
def test_replay_refuses_unconfirmed_launch_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, evidence: str
) -> None:
    with prepared_operation(tmp_path, False) as prepared:
        client, _, _, _, record, _ = prepared
        service = ctx_of(client).source_operations
        oid = record["operation_id"]
        command = {
            "expected_revision": record["revision"],
            "expected_attempt": record["attempt"],
            "settings": {"phase_analyzer": False},
        }
        with monkeypatch.context() as fault:
            fail_directory_sync(fault, lambda d: d == service._dir(oid))
            with pytest.raises(OSError):
                client.post(f"{API}/{oid}/estimate", json=command)
        retained = service.get(oid)
        attempt = service._attempt_dir(retained)
        atomic_write_json(attempt / evidence, {"incomplete": True})
        response = client.post(f"{API}/{oid}/estimate", json=command)
        assert response.status_code == 409 and "execution evidence" in response.text
        assert read_json(attempt / evidence) == {"incomplete": True}
        assert service.get(oid).job_id == retained.job_id
        assert service.get(oid).status == "cleanup_pending"
        assert not service.get(oid).cleanup_verified


@pytest.mark.parametrize("lost_record", [False, True])
def test_committed_creation_accepts_legacy_receipts_but_refuses_lost_state(
    tmp_path: Path, lost_record: bool
) -> None:
    with prepared_operation(tmp_path, False) as prepared:
        client, _, source, _, _, _ = prepared
        service = ctx_of(client).source_operations
        request = {"path": str(source), "idempotency_key": "legacy-creation-receipt-123"}
        response = client.post(API, json=request)
        assert response.status_code == 202, response.text
        oid = response.json()["operation_id"]
        wait_operation(client, oid)
        key = hashlib.sha256(request["idempotency_key"].encode()).hexdigest()
        path = service.root / "requests" / f"{key}.json"
        legacy = read_json(path)
        legacy.pop("status")
        atomic_write_json(path, legacy)
        if lost_record:
            (service._dir(oid) / "operation.json").unlink()
        replay = client.post(API, json=request)
        if lost_record:
            assert replay.status_code == 409 and "record is missing" in replay.text
            assert not (service._dir(oid) / "operation.json").exists()
        else:
            assert replay.status_code == 202 and replay.json()["operation_id"] == oid


@pytest.mark.parametrize("in_project", [False, True])
def test_conversion_replay_recovers_only_its_unlaunched_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, in_project: bool
) -> None:
    with prepared_operation(tmp_path, in_project) as prepared:
        client, _, source, _, record, request = prepared
        service = ctx_of(client).source_operations
        oid = record["operation_id"]
        existing_jobs = client.get("/api/v1/jobs").json()
        before_jobs = len([j for j in existing_jobs if j.get("key") == f"source:{oid}"])
        inputs = {p: digest(p) for p in source.rglob("*") if p.is_file()}
        with monkeypatch.context() as fault:
            fail_directory_sync(fault, lambda d: d == service._dir(oid))
            for _ in range(2):
                with pytest.raises(OSError, match="directory synchronization failure"):
                    client.post(f"{API}/{oid}/convert", json=request)
        reserved = service.get(oid)
        response = client.post(f"{API}/{oid}/convert", json=request)
        assert response.status_code == 202, response.text
        admitted = service.get(oid)
        job = client.get(f"/api/v1/jobs/{admitted.job_id}")
        assert job.status_code == 200, "Replayed conversion left its handoff unsubmitted"
        completed = wait_operation(client, oid)
        assert completed["status"] == "completed", completed
        assert completed["conversion_run"]["run_id"] == reserved.conversion_run_id
        assert completed["attempt"] == reserved.attempt
        assert completed["conversion_run"]["attempts"] == 1
        jobs = client.get("/api/v1/jobs").json()
        assert len([j for j in jobs if j.get("key") == f"source:{oid}"]) == before_jobs + 1
        assert inputs == {p: digest(p) for p in source.rglob("*") if p.is_file()}


@pytest.mark.parametrize("in_project", [False, True])
@pytest.mark.parametrize("retained_evidence", [False, True])
def test_cancel_handles_a_missing_source_job_after_failed_submission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, in_project: bool, retained_evidence: bool
) -> None:
    with prepared_operation(tmp_path, in_project) as prepared:
        client, _, _, derived, record, request = prepared
        service = ctx_of(client).source_operations
        oid = record["operation_id"]
        with monkeypatch.context() as fault:
            fail_directory_sync(fault, lambda d: d == service._dir(oid))
            with pytest.raises(OSError, match="directory synchronization failure"):
                client.post(f"{API}/{oid}/convert", json=request)
        queued = service.get(oid)
        if retained_evidence:
            atomic_write_json(service._attempt_dir(queued) / "dispatch", {"incomplete": True})
        command = {
            "expected_revision": queued.revision,
            "expected_attempt": queued.attempt,
        }
        response = client.post(f"{API}/{oid}/cancel", json=command)
        assert response.status_code == 200, response.text
        stopped = response.json()
        assert stopped["status"] == ("cleanup_pending" if retained_evidence else "cancelled")
        assert stopped["cleanup_verified"] is not retained_evidence
        assert stopped.get("conversion_run") is None
        assert not list(derived.rglob("*.nii.gz"))


@pytest.mark.parametrize("in_project", [False, True])
@pytest.mark.parametrize("retained_evidence", [False, True])
def test_failed_state_publication_is_reconciled_before_offering_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, in_project: bool, retained_evidence: bool
) -> None:
    with prepared_operation(tmp_path, in_project) as prepared:
        client, _, source, derived, record, _ = prepared
        service = ctx_of(client).source_operations
        before = {r.operation_id for r in service.list()}
        request = {
            "path": str(source),
            "project_id": record["project_id"],
            "idempotency_key": "failed-running-publication-123",
        }
        with monkeypatch.context() as fault:
            fail_directory_sync(
                fault,
                lambda d: d.parent == service.root and is_ulid(d.name) and d.name not in before,
                after=3,
            )
            response = client.post(API, json=request)
            assert response.status_code == 202, response.text
            oid, job_id = response.json()["operation_id"], response.json()["job_id"]
            assert wait(client, job_id).status == "failed"
        stopped = service.get(oid)
        if retained_evidence:
            atomic_write_json(service._attempt_dir(stopped) / "dispatch", {"incomplete": True})
        response = client.get(f"{API}/{oid}")
        assert response.status_code == 200, response.text
        restored = response.json()
        assert restored["status"] == ("cleanup_pending" if retained_evidence else "failed"), (
            restored
        )
        assert restored["cleanup_verified"] is not retained_evidence
        command = {
            "expected_revision": restored["revision"],
            "expected_attempt": restored["attempt"],
        }
        resume = client.post(f"{API}/{oid}/resume", json=command)
        if retained_evidence:
            assert resume.status_code == 409, resume.text
        else:
            assert resume.status_code == 202, resume.text
            completed = wait_operation(client, oid)
            assert completed["status"] == "completed" and completed["attempt"] == 2, completed
        assert not list(derived.rglob("*.nii.gz"))


@pytest.mark.parametrize("in_project", [False, True])
def test_estimate_replay_reconfirms_metadata_and_recovers_unlaunched_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, in_project: bool
) -> None:
    with prepared_operation(tmp_path, in_project) as prepared:
        client, _, _, derived, record, _ = prepared
        service = ctx_of(client).source_operations
        oid = record["operation_id"]
        request = {
            "expected_revision": record["revision"],
            "expected_attempt": record["attempt"],
            "settings": {"phase_analyzer": False},
        }
        with monkeypatch.context() as fault:
            fail_directory_sync(fault, lambda directory: directory == service._dir(oid))
            for _ in range(2):
                with pytest.raises(OSError, match="directory synchronization failure"):
                    client.post(f"{API}/{oid}/estimate", json=request)
        response = client.post(f"{API}/{oid}/estimate", json=request)
        assert response.status_code == 202, response.text
        restored = wait_operation(client, oid)
        assert restored["status"] == "completed" and restored["estimate"] is not None, restored
        assert restored["attempt"] == record["attempt"] + 1
        assert not list(derived.rglob("*.nii.gz"))
