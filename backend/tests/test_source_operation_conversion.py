"""D10/D11/D13/D16/D21, API-69: source operations delegate to one existing conversion run."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.tasks import dicom_execution, driver, workspace_runs
from tests.test_api_ingest import ctx_of, wait
from tests.test_source_operations_api import API, control, wait_operation
from tools.dicom_fixtures import write_series


@contextmanager
def prepared_operation(
    tmp_path: Path, in_project: bool
) -> Iterator[tuple[TestClient, Settings, Path, Path, dict[str, Any], dict[str, Any]]]:
    source, derived = tmp_path / "source", tmp_path / "derived"
    write_series(source)
    derived.mkdir()
    settings = Settings(
        workspace_root=tmp_path / "workspace",
        allowed_data_roots=str(source),
        allowed_derived_roots=str(derived),
        dicom_memory_mb=1024,
        _env_file=None,
    )  # type: ignore[call-arg]
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        project = None
        if in_project:
            project = client.post("/api/v1/projects", json={"name": "Source", "packs": []}).json()[
                "project_id"
            ]
            assert (
                client.put(
                    f"/api/v1/projects/{project}/roots/DERIVED",
                    json={"path": str(derived), "role": "derived"},
                ).status_code
                == 200
            )
        record = client.post(
            API,
            json={
                "path": str(source),
                "project_id": project,
                "idempotency_key": "durable-conversion-123",
            },
        ).json()
        operation = record["operation_id"]
        wait_operation(client, operation)
        assert control(client, operation, "estimate").status_code == 202
        record = wait_operation(client, operation)
        request = {
            "expected_revision": record["revision"],
            "expected_attempt": record["attempt"],
            "inventory_generation": record["summary"]["generation"],
            "plan_attempt": record["plan_attempt"],
            "name": "original-allocation",
        }
        yield client, settings, source, derived, record, request


@pytest.fixture
def planned(tmp_path: Path, in_project: bool) -> Iterator[Any]:
    with prepared_operation(tmp_path, in_project) as operation:
        yield operation


def native_run(client: TestClient, operation: str) -> dict[str, Any]:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        record = client.get(f"{API}/{operation}").json()
        if record.get("conversion_run"):
            return dict(record["conversion_run"])
        if record["status"] == "failed":
            raise AssertionError(record)
        time.sleep(0.02)
    raise AssertionError("Conversion run was not linked")


@pytest.mark.parametrize("in_project", [False, True])
def test_settings_only_estimate_keeps_inventory_and_invalidates_the_old_plan(planned: Any) -> None:
    client, _, _, derived, record, old_convert = planned
    operation = record["operation_id"]
    request = {
        "expected_revision": record["revision"],
        "expected_attempt": record["attempt"],
        "settings": {"phase_analyzer": False, "anonymize": "basic"},
        "name": "revised-output",
    }
    response = client.post(f"{API}/{operation}/estimate", json=request)
    assert response.status_code == 202, response.text
    ready = wait_operation(client, operation)
    assert ready["stage"] == "ready" and ready["operation_id"] == operation
    assert ready["summary"]["generation"] == record["summary"]["generation"]
    assert ready["plan_attempt"] > record["plan_attempt"]
    assert ready["dataset_name"] == "revised-output"
    assert ready["settings"]["anonymize"] == "basic" and not ready["settings"]["phase_analyzer"]
    assert ready["project_id"] == record["project_id"]
    again = client.post(f"{API}/{operation}/estimate", json=request)
    assert again.status_code == 202 and again.json()["attempt"] == ready["attempt"]
    assert client.post(f"{API}/{operation}/convert", json=old_convert).status_code == 409
    assert not list(derived.iterdir())


@pytest.mark.parametrize("in_project", [False, True])
def test_changed_source_is_rejected_before_allocating_a_conversion(planned: Any) -> None:
    client, _, source, derived, record, request = planned
    write_series(source / "added", patient_id="new")
    operation = record["operation_id"]
    assert client.post(f"{API}/{operation}/convert", json=request).status_code == 202
    failed = wait_operation(client, operation)
    assert failed["status"] == "failed" and "new dry run" in failed["error"]
    assert failed["conversion_run"] is None and not list(derived.iterdir())


@pytest.mark.parametrize("in_project", [False, True])
def test_native_worker_revalidates_the_plan_after_queue_wait(
    planned: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, source, derived, record, request = planned
    changed = False

    async def change_before_worker(job: Path, **kwargs: Any) -> dict[str, Any]:
        nonlocal changed
        spec = json.loads((job / "job.json").read_text())
        if not changed and spec.get("source_inventory"):
            changed = True
            write_series(source / "arrived-while-queued", patient_id="new")
        return await dicom_execution.run_dicom_job(job, **kwargs)

    monkeypatch.setattr(driver, "run_dicom_job", change_before_worker)
    monkeypatch.setattr(workspace_runs, "run_dicom_job", change_before_worker)
    operation = record["operation_id"]
    assert client.post(f"{API}/{operation}/convert", json=request).status_code == 202
    native = native_run(client, operation)
    wait(client, native["job_id"])
    final = client.get(f"{API}/{operation}").json()
    assert changed and final["status"] == "failed" and "plan conflict" in final["error"].lower()
    assert not [p for p in derived.rglob("*.nii.gz") if p.is_file()]
    assert not list(derived.rglob("dataset.json"))


@pytest.mark.parametrize("in_project", [False, True])
def test_operation_cancel_resume_and_duplicate_control_keep_original_allocation(
    planned: Any,
) -> None:
    client, settings, _, derived, record, request = planned
    operation = record["operation_id"]
    settings.dicom_memory_mb = 512
    assert client.post(f"{API}/{operation}/convert", json=request).status_code == 202
    native = native_run(client, operation)
    waiting = wait_operation(client, operation)
    assert waiting["status"] == "waiting_for_resources", waiting
    assert control(client, operation, "cancel").status_code == 200
    wait(client, native["job_id"])
    cancelled = wait_operation(client, operation)
    assert cancelled["status"] == "cancelled" and cancelled["cleanup_verified"]
    settings.dicom_memory_mb = 1024
    command = {"expected_revision": cancelled["revision"], "expected_attempt": cancelled["attempt"]}
    response = client.post(f"{API}/{operation}/resume", json=command)
    assert response.status_code == 202, response.text
    again = client.post(f"{API}/{operation}/resume", json=command)
    assert again.status_code == 202, again.text
    resumed = response.json()["conversion_run"]
    assert resumed["run_id"] == native["run_id"] and resumed["job_id"] != native["job_id"]
    assert again.json()["conversion_run"]["job_id"] == resumed["job_id"]
    wait(client, resumed["job_id"])
    final = client.get(f"{API}/{operation}").json()["conversion_run"]
    assert final["status"] == "completed" and final["attempts"] == 2
    assert final.get("dataset_dir", final.get("output_dir")) == native.get(
        "dataset_dir", native.get("output_dir")
    )
    assert not (derived / "_datasets" / "original-allocation-1").exists()


@pytest.mark.parametrize("in_project", [False, True])
def test_lost_handoff_acknowledgement_does_not_allocate_another_run(
    planned: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, _, derived, record, request = planned
    operations = ctx_of(client).source_operations
    service = operations.tasks if record["project_id"] else operations.workspace_tasks
    original = service.start

    async def lose_response(*args: Any, **kwargs: Any) -> Any:
        await original(*args, **kwargs)
        raise OSError("synthetic lost handoff acknowledgement")

    monkeypatch.setattr(service, "start", lose_response)
    operation = record["operation_id"]
    assert client.post(f"{API}/{operation}/convert", json=request).status_code == 202
    native = native_run(client, operation)
    wait(client, native["job_id"])
    again = client.post(f"{API}/{operation}/convert", json=request)
    assert again.status_code == 202 and again.json()["conversion_run"]["run_id"] == native["run_id"]
    assert len([p for p in derived.rglob("*.nii.gz") if p.is_file()]) == 1
    assert not (derived / "_datasets" / "original-allocation-1").exists()


@pytest.mark.parametrize("in_project", [False, True])
def test_cancel_acknowledgement_fences_the_handoff_before_a_native_attempt(
    planned: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    import threading

    from app.core.errors import JobConflict
    from app.tasks.source_operations import SourceOperationControl

    client, settings, _, derived, record, request = planned
    settings.dicom_memory_mb = 512
    operations = ctx_of(client).source_operations
    service = operations.tasks if record["project_id"] else operations.workspace_tasks
    original = service.start
    entered, requested = threading.Event(), threading.Event()
    release = asyncio.Event()
    order = []

    async def delayed_start(*args: Any, **kwargs: Any) -> Any:
        entered.set()
        await release.wait()
        result = await original(*args, **kwargs)
        order.append("allocated")
        return result

    monkeypatch.setattr(service, "start", delayed_start)
    operation = record["operation_id"]
    assert client.post(f"{API}/{operation}/convert", json=request).status_code == 202
    assert entered.wait(10)
    current = client.get(f"{API}/{operation}").json()

    async def cancel() -> None:
        requested.set()
        try:
            await operations.cancel(
                operation,
                SourceOperationControl(
                    expected_revision=current["revision"], expected_attempt=current["attempt"]
                ),
            )
        except JobConflict:
            # A handoff revision can reject a stale command; rejection is not an ack.
            fresh = await operations.view(operation)
            await operations.cancel(
                operation,
                SourceOperationControl(
                    expected_revision=fresh.revision, expected_attempt=fresh.attempt
                ),
            )
        order.append("acknowledged")

    future = client.portal.start_task_soon(cancel)
    try:
        assert requested.wait(5)
        client.portal.call(release.set)
        future.result(timeout=10)
        native = native_run(client, operation)
        wait(client, native["job_id"])
        assert order == ["allocated", "acknowledged"]
        assert client.get(f"{API}/{operation}").json()["status"] == "cancelled"
        assert not [path for path in derived.rglob("*.nii.gz") if path.is_file()]
    finally:
        client.portal.call(release.set)


@pytest.mark.parametrize("in_project", [False, True])
@pytest.mark.parametrize("action", ["cancel", "resume"])
@pytest.mark.parametrize("with_run_fence", [False, True])
def test_old_operation_control_cannot_target_a_new_native_attempt(
    planned: Any, action: str, with_run_fence: bool
) -> None:
    client, settings, _, _, record, request = planned
    operation = record["operation_id"]
    settings.dicom_memory_mb = 512
    assert client.post(f"{API}/{operation}/convert", json=request).status_code == 202
    native = native_run(client, operation)
    assert wait_operation(client, operation)["status"] == "waiting_for_resources"
    assert control(client, operation, "cancel").status_code == 200
    wait(client, native["job_id"])
    stopped = wait_operation(client, operation)
    stale = {
        "expected_revision": stopped["revision"],
        "expected_attempt": stopped["attempt"],
    }
    if with_run_fence:
        stale["expected_run_attempt"] = stopped["conversion_run"]["attempts"]
    run_api = (
        f"/api/v1/projects/{record['project_id']}/task-runs/{native['run_id']}"
        if record["project_id"]
        else f"/api/v1/task-runs/{native['run_id']}"
    )
    resumed = client.post(f"{run_api}/resume")
    assert resumed.status_code == 202, resumed.text
    if action == "resume":
        assert client.post(f"{run_api}/cancel").status_code == 200
        wait(client, resumed.json()["job_id"])
    response = client.post(f"{API}/{operation}/{action}", json=stale)
    assert response.status_code == 409, response.text
    current = client.get(f"{API}/{operation}").json()["conversion_run"]
    assert current["attempts"] == 2
    assert current["job_id"] == resumed.json()["job_id"]
    if action == "cancel":
        assert current["status"] != "cancelling"
        assert client.post(f"{run_api}/cancel").status_code == 200
        wait(client, current["job_id"])


@pytest.mark.parametrize("in_project", [False, True])
@pytest.mark.parametrize("failure_point", ["before_dispatch", "after_dispatch"])
def test_resume_retries_a_lost_acknowledgement_without_creating_another_attempt(
    planned: Any, monkeypatch: pytest.MonkeyPatch, failure_point: str
) -> None:
    client, settings, _, _, record, request = planned
    operations = ctx_of(client).source_operations
    operation = record["operation_id"]
    settings.dicom_memory_mb = 512
    assert client.post(f"{API}/{operation}/convert", json=request).status_code == 202
    native = native_run(client, operation)
    assert wait_operation(client, operation)["status"] == "waiting_for_resources"
    assert control(client, operation, "cancel").status_code == 200
    wait(client, native["job_id"])
    stopped = wait_operation(client, operation)
    command = {
        "expected_revision": stopped["revision"],
        "expected_attempt": stopped["attempt"],
        "expected_run_attempt": native["attempts"],
    }
    service = operations.tasks if record["project_id"] else operations.workspace_tasks
    original = service.resume
    dispatched: list[Any] = []

    async def lose_response(*args: Any, **kwargs: Any) -> Any:
        if failure_point == "before_dispatch":
            raise OSError("synthetic lost resume acknowledgement")
        result = await original(*args, **kwargs)
        dispatched.append(result)
        raise OSError("synthetic lost resume acknowledgement")

    monkeypatch.setattr(service, "resume", lose_response)
    with pytest.raises(OSError, match="lost resume acknowledgement"):
        client.post(f"{API}/{operation}/resume", json=command)
    monkeypatch.setattr(service, "resume", original)
    response = client.post(f"{API}/{operation}/resume", json=command)
    assert response.status_code == 202, response.text
    retried = response.json()["conversion_run"]
    assert retried["attempts"] == 2
    if dispatched:
        assert retried["job_id"] == dispatched[0].job_id
    assert retried["run_id"] == native["run_id"]
    assert control(client, operation, "cancel").status_code == 200
    wait(client, retried["job_id"])


@pytest.mark.parametrize("in_project", [False, True])
def test_pending_resume_is_reconciled_after_backend_restart(
    tmp_path: Path, in_project: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    with prepared_operation(tmp_path, in_project) as planned:
        client, settings, _, derived, record, request = planned
        operation = record["operation_id"]
        settings.dicom_memory_mb = 512
        assert client.post(f"{API}/{operation}/convert", json=request).status_code == 202
        native = native_run(client, operation)
        assert wait_operation(client, operation)["status"] == "waiting_for_resources"
        assert control(client, operation, "cancel").status_code == 200
        wait(client, native["job_id"])
        stopped = wait_operation(client, operation)
        command = {
            "expected_revision": stopped["revision"],
            "expected_attempt": stopped["attempt"],
            "expected_run_attempt": native["attempts"],
        }
        operations = ctx_of(client).source_operations
        service = operations.tasks if in_project else operations.workspace_tasks
        original = service.resume

        async def lose_response(*args: Any, **kwargs: Any) -> Any:
            await original(*args, **kwargs)
            raise OSError("lost resume response before restart")

        monkeypatch.setattr(service, "resume", lose_response)
        with pytest.raises(OSError, match="before restart"):
            client.post(f"{API}/{operation}/resume", json=command)
        assert operations.get(operation).pending_control is not None
        monkeypatch.setattr(service, "resume", original)
    with TestClient(create_app(settings, inline_jobs=True)) as restarted:
        restored = restarted.get(f"{API}/{operation}").json()
        assert restored["pending_control"] is None
        assert restored["status"] == "interrupted" and restored["cleanup_verified"]
        assert restored["conversion_run"]["attempts"] == 2
        assert restored["conversion_run"]["run_id"] == native["run_id"]
        replay = restarted.post(f"{API}/{operation}/resume", json=command)
        assert replay.status_code == 202 and replay.json()["conversion_run"]["attempts"] == 2
        settings.dicom_memory_mb = 1024
        resumed = control(restarted, operation, "resume")
        assert resumed.status_code == 202, resumed.text
        wait(restarted, resumed.json()["conversion_run"]["job_id"])
        completed = restarted.get(f"{API}/{operation}").json()["conversion_run"]
        assert completed["status"] == "completed" and completed["attempts"] == 3
        assert completed.get("dataset_dir", completed.get("output_dir")) == native.get(
            "dataset_dir", native.get("output_dir")
        )
        assert len([path for path in derived.rglob("*.nii.gz") if path.is_file()]) == 1


@pytest.mark.parametrize("in_project", [True])
def test_native_cancel_serializes_with_a_source_operation_resume(
    planned: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    import threading

    from app.tasks.source_operations import SourceOperationControl

    client, settings, _, _, record, request = planned
    operation = record["operation_id"]
    operations = ctx_of(client).source_operations
    settings.dicom_memory_mb = 512
    assert client.post(f"{API}/{operation}/convert", json=request).status_code == 202
    native = native_run(client, operation)
    assert wait_operation(client, operation)["status"] == "waiting_for_resources"
    assert control(client, operation, "cancel").status_code == 200
    wait(client, native["job_id"])
    stopped = wait_operation(client, operation)
    original = operations.tasks._submit
    entered, requested = threading.Event(), threading.Event()
    release = asyncio.Event()
    order: list[str] = []

    async def delayed_submit(*args: Any, **kwargs: Any) -> Any:
        entered.set()
        await release.wait()
        result = await original(*args, **kwargs)
        order.append("allocated")
        return result

    monkeypatch.setattr(operations.tasks, "_submit", delayed_submit)
    command = SourceOperationControl(
        expected_revision=stopped["revision"],
        expected_attempt=stopped["attempt"],
        expected_run_attempt=native["attempts"],
    )
    resumed = client.portal.start_task_soon(operations.resume, operation, command)
    assert entered.wait(10)

    async def cancel() -> None:
        requested.set()
        await operations.tasks.cancel(record["project_id"], native["run_id"])
        order.append("acknowledged")

    cancelled = client.portal.start_task_soon(cancel)
    try:
        assert requested.wait(5)
        client.portal.call(release.set)
        resumed.result(timeout=10)
        cancelled.result(timeout=10)
        assert order == ["allocated", "acknowledged"]
        current = client.get(f"{API}/{operation}").json()["conversion_run"]
        wait(client, current["job_id"])
        assert client.get(f"{API}/{operation}").json()["status"] == "cancelled"
    finally:
        client.portal.call(release.set)
