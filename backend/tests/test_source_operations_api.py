"""D08/D13/D14/D16 / API-69, TSK-16: real durable discovery jobs, no pixel launch."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.tasks import source_operations
from tools.dicom_fixtures import write_series

API = "/api/v1/source-operations"


def test_background_open_prepares_a_durable_complete_session_without_conversion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D08/D10, SRC-18: the Open purpose must do more than discover DICOM counts."""
    import hashlib
    import json

    from tests.test_sources import ct, lab, nii

    source = tmp_path / "source"
    nii(source / "a.nii.gz", ct())
    write_series(source / "nested" / "dicom", shape=(3, 3, 3), marker=(1, 1, 2))
    before = {
        p: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob("*") if p.is_file()
    }
    settings = Settings(
        workspace_root=tmp_path / "workspace", allowed_data_roots=str(source), _env_file=None
    )  # type: ignore[call-arg]
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        response = client.post(
            API,
            json={"path": str(source), "purpose": "open", "idempotency_key": "durable-open-123"},
        )
        assert response.status_code == 202, response.text
        oid = response.json()["operation_id"]
        completed = wait_operation(client, oid)
        assert completed["status"] == "completed" and completed["stage"] == "opened"
        assert completed["cleanup_verified"] and completed["conversion_run_id"] is None
        attempt = (
            settings.workspace_root
            / "plugins/dicom/operations"
            / oid
            / "attempts"
            / str(completed["attempt"])
        )
        artifact = attempt / "open-session.json"
        session = json.loads(artifact.read_text())
        assert session["sid"] == oid
        assert [item["format"] for item in session["items"]] == ["nifti", "dicom"]
        assert len(session["items"][1]["files"]) == 3
        artifact_bytes = artifact.read_bytes()
        opened = client.post(f"{API}/{oid}/open")
        assert opened.status_code == 201, opened.text
        assert opened.json()["sid"] == oid
        mask = nii(source / "masks" / "label.nii.gz", lab())
        attached = client.post(f"/api/v1/open/{oid}/items/0/attach", json={"path": str(mask)})
        assert attached.status_code == 200, attached.text
        expected_items = client.get(f"/api/v1/open/{oid}").json()["items"]
        before[mask] = hashlib.sha256(mask.read_bytes()).hexdigest()
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        restored = client.get(f"{API}/{oid}").json()
        assert restored["stage"] == "opened" and restored["attempt"] == completed["attempt"]
        assert artifact.read_bytes() == artifact_bytes
        # Native/stat restoration must not run on the async API event loop.
        import asyncio

        ctx = client.app.state.ctx
        original_restore = ctx.source_operations.open_session
        restored_calls = []

        def checked_restore(*args: Any, **kwargs: Any) -> Any:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                pass
            else:
                raise AssertionError("Open hydration blocked the API event loop")
            restored_calls.append(True)
            return original_restore(*args, **kwargs)

        monkeypatch.setattr(ctx.source_operations, "open_session", checked_restore)
        # Opening by the opaque session URL restores after restart, including byte routes.
        restored_open = client.get(f"/api/v1/open/{oid}")
        assert restored_open.status_code == 200, restored_open.text
        assert restored_open.json()["items"] == expected_items
        ctx.open_sessions.drop(oid)
        assert (
            client.get(f"/api/v1/open/{oid}/items/0/image").content
            == (source / "a.nii.gz").read_bytes()
        )
        assert len(restored_calls) == 2
        assert client.delete(f"/api/v1/open/{oid}").status_code == 204
        assert client.get(f"/api/v1/open/{oid}").status_code == 404
        assert client.post(f"{API}/{oid}/open").status_code == 201
        artifact.write_bytes(b"{}")
        changed = client.post(f"{API}/{oid}/open")
        assert changed.status_code == 409, changed.text
        assert changed.json()["actions"] == ["choose_another_path", "home"]
        artifact.write_bytes(artifact_bytes)
    assert before == {
        p: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob("*") if p.is_file()
    }


@pytest.mark.parametrize(
    "change",
    [
        "nifti",
        "dicom",
        "npy_sidecar",
        "npy_reference",
        "missing",
        "symlink",
        "new_sidecar",
        "missing_inventory",
        "missing_header_pin",
        "missing_file_pin",
        "mask",
    ],
)
def test_restored_open_refuses_changed_prepared_inputs(tmp_path: Path, change: str) -> None:
    """D10/D12, SRC-19: persisted geometry cannot outlive its pinned inputs."""
    import json

    import numpy as np

    from tests.test_sources import ct, nii

    source = tmp_path / "source"
    image = nii(source / "image.nii.gz", ct())
    if change == "dicom":
        write_series(source / "series", shape=(3, 3, 3), marker=(1, 1, 2))
    if change.startswith("npy") or change == "new_sidecar":
        np.save(source / "array.npy", np.zeros((3, 4, 5), dtype=np.int16))
        if change != "new_sidecar":
            (source / "array.npy.json").write_text(
                json.dumps({"axis_order": "xyz", "reference_ref": "image.nii.gz"})
            )
    settings = Settings(
        workspace_root=tmp_path / "workspace", allowed_data_roots=str(source), _env_file=None
    )  # type: ignore[call-arg]
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        created = client.post(
            API,
            json={
                "path": str(source / "array.npy" if change == "npy_reference" else source),
                "purpose": "open",
                "idempotency_key": "source-pins-123",
            },
        )
        assert created.status_code == 202, created.text
        oid = created.json()["operation_id"]
        assert wait_operation(client, oid)["stage"] == "opened"
        assert client.post(f"{API}/{oid}/open").status_code == 201
        if change == "mask":
            from tests.test_sources import lab

            mask = nii(source / "mask.nii.gz", lab())
            attached = client.post(f"/api/v1/open/{oid}/items/0/attach", json={"path": str(mask)})
            assert attached.status_code == 200, attached.text
    if change == "dicom":
        member = next((source / "series").iterdir())
        member.write_bytes(member.read_bytes() + b"changed")
    elif change == "mask":
        nii(mask, ct()[:2, :3, :4])
    elif change == "missing_inventory":
        (settings.workspace_root / "plugins/dicom/operations" / oid / "inventory.sqlite").unlink()
    elif change in {"missing_header_pin", "missing_file_pin"}:
        import sqlite3

        with sqlite3.connect(
            settings.workspace_root / "plugins/dicom/operations" / oid / "inventory.sqlite"
        ) as database:
            database.execute(
                "DELETE FROM open_headers"
                if change == "missing_header_pin"
                else "DELETE FROM files"
            )
    elif change == "new_sidecar":
        (source / "array.npy.json").write_text(json.dumps({"axis_order": "xyz"}))
    elif change == "npy_sidecar":
        (source / "array.npy.json").write_text(json.dumps({"axis_order": "zyx"}))
    elif change == "missing":
        image.unlink()
    elif change == "symlink":
        copy = source / "replacement.nii.gz"
        image.rename(copy)
        image.symlink_to(copy)
    else:
        nii(image, ct()[:2, :3, :4])
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        for path in (f"/api/v1/open/{oid}", f"/api/v1/open/{oid}/items/0/image"):
            refused = client.get(path)
            assert refused.status_code == 409, refused.text
            assert refused.json()["actions"] == ["choose_another_path", "home"]
        refused = client.post(f"{API}/{oid}/open")
        assert refused.status_code == 409, refused.text


def test_background_plan_without_dicom_preserves_the_refusal_and_next_actions(
    tmp_path: Path,
) -> None:
    import nibabel as nib
    import numpy as np

    source = tmp_path / "nifti"
    source.mkdir()
    nib.save(nib.Nifti1Image(np.zeros((3, 3, 3)), np.eye(4)), source / "image.nii.gz")
    settings = Settings(
        workspace_root=tmp_path / "workspace", allowed_data_roots=str(source), _env_file=None
    )  # type: ignore[call-arg]
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        response = client.post(
            API,
            json={"path": str(source), "prepare_plan": True, "idempotency_key": "no-dicom-123"},
        )
        assert response.status_code == 202, response.text
        failed = wait_operation(client, response.json()["operation_id"])
        assert failed["status"] == "failed" and failed["cleanup_verified"]
        assert failed["summary"]["nifti"] == 1 and failed["summary"]["dicom"] == 0
        problem = failed["problem"]
        assert problem["status"] == 415 and problem["type"].endswith("unsupported-format")
        assert problem["detail"] == "No DICOM files in nifti; 1 NIfTI files found"
        assert problem["actions"] == ["open", "import_as:nifti-files", "choose_another_path"]
        assert failed["conversion_run_id"] is None and failed["estimate"] is None


def test_api_schema_imports_before_builtin_plugin_path_setup() -> None:
    """API-69 / BE-10: pytest's parent path must not hide OCI/API schema startup failures."""
    backend = Path(__file__).resolve().parents[1]
    process = subprocess.run(
        [sys.executable, "-c", "from app.main import create_app; create_app().openapi()"],
        cwd=backend,
        env={**os.environ, "PYTHONPATH": str(backend)},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert process.returncode == 0, process.stderr


def test_prepare_plan_intent_chains_discovery_to_estimate_without_a_browser(tmp_path: Path) -> None:
    source = tmp_path / "source"
    write_series(source)
    settings = Settings(
        workspace_root=tmp_path / "workspace", allowed_data_roots=str(source), _env_file=None
    )  # type: ignore[call-arg]
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        response = client.post(
            API,
            json={
                "path": str(source),
                "prepare_plan": True,
                "idempotency_key": "prepare-plan-123",
                "settings": {"anonymize": "basic"},
            },
        )
        assert response.status_code == 202, response.text
        ready = wait_operation(client, response.json()["operation_id"])
        assert ready["stage"] == "ready" and ready["work_kind"] == "estimate", ready
        assert ready["estimate"]["n_units"] == 1 and ready["settings"]["anonymize"] == "basic"
        assert ready["attempt"] == 2 and not list(settings.workspace_root.rglob("*.nii.gz"))


def wait_operation(client: TestClient, operation: str) -> dict[str, Any]:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        record = client.get(f"{API}/{operation}").json()
        if record["status"] not in {"queued", "running", "cancelling", "reconciling"}:
            return dict(record)
        time.sleep(0.02)
    raise AssertionError("Source operation did not finish")


def control(client: TestClient, operation: str, action: str) -> Any:
    for _ in range(5):
        current = client.get(f"{API}/{operation}").json()
        response = client.post(
            f"{API}/{operation}/{action}",
            json={
                "expected_revision": current["revision"],
                "expected_attempt": current["attempt"],
                "expected_run_attempt": (current.get("conversion_run") or {}).get("attempts"),
            },
        )
        if response.status_code != 409:
            return response
    raise AssertionError(f"Could not fence {action} against current operation")


def test_background_discovery_persists_across_app_restart_and_is_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "source"
    write_series(source / "patient" / "study" / "series", shape=(3, 3, 3), marker=(1, 1, 2))
    settings = Settings(
        workspace_root=tmp_path / "workspace",
        allowed_data_roots=str(source),
        _env_file=None,  # type: ignore[call-arg]
    )
    body = {"path": str(source), "idempotency_key": "discovery-123"}
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        started = client.post(API, json=body)
        assert started.status_code == 202, started.text
        operation = started.json()["operation_id"]
        again = client.post(API, json=body)
        assert again.status_code == 202 and again.json()["operation_id"] == operation
        record = wait_operation(client, operation)
        assert record["status"] == "completed" and record["stage"] == "discovered"
        assert record["summary"]["dicom"] == 3
        assert record["cleanup_verified"]
        page = client.get(f"{API}/{operation}/series").json()
        assert page["total"] == 1 and page["items"][0]["n_files"] == 3
        assert not list(settings.workspace_root.rglob("*.nii.gz"))
        assert client.post(API, json={**body, "purpose": "open"}).status_code == 409
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        recovered = client.get(f"{API}/{operation}").json()
        assert recovered["operation_id"] == operation and recovered["status"] == "completed"
        assert client.get(API).json()["items"][0]["operation_id"] == operation


def test_cancel_before_dispatch_and_resume_reuses_operation(tmp_path: Path) -> None:
    source = tmp_path / "source"
    write_series(source / "series", shape=(3, 3, 70), marker=(1, 1, 69))
    settings = Settings(
        workspace_root=tmp_path / "workspace",
        allowed_data_roots=str(source),
        _env_file=None,  # type: ignore[call-arg]
    )
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        record = client.post(
            API, json={"path": str(source), "idempotency_key": "cancel-123"}
        ).json()
        operation = record["operation_id"]
        response = control(client, operation, "cancel")
        assert response.status_code == 200, response.text
        ended = wait_operation(client, operation)
        assert ended["status"] == "cancelled" and ended["cleanup_verified"]
        resumed = control(client, operation, "resume")
        assert resumed.status_code == 202, resumed.text
        assert resumed.json()["operation_id"] == operation
        assert resumed.json()["attempt"] == ended["attempt"] + 1
        complete = wait_operation(client, operation)
        assert complete["status"] == "completed" and complete["summary"]["dicom"] == 70
        stale = client.post(
            f"{API}/{operation}/cancel",
            json={
                "expected_revision": 0,
                "expected_attempt": complete["attempt"],
            },
        )
        assert stale.status_code == 409


def test_inventory_quota_is_enforced_by_worker_and_resumes_after_reconfiguration(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    write_series(source / "series", shape=(3, 3, 600), marker=(1, 1, 599))
    settings = Settings(
        workspace_root=tmp_path / "workspace",
        allowed_data_roots=str(source),
        dicom_inventory_mb=1,
        dicom_batch_size=7,
        _env_file=None,
    )  # type: ignore[call-arg]
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        started = client.post(
            API, json={"path": str(source), "idempotency_key": "inventory-quota-123"}
        )
        assert started.status_code == 202, started.text
        operation = started.json()["operation_id"]
        partial = wait_operation(client, operation)
        assert partial["status"] == "completed_with_errors" and partial["cleanup_verified"]
        assert (
            partial["summary"]["limited"]
            and partial["summary"]["limit_reason"] == "inventory_bytes"
        )
        assert 0 < partial["summary"]["files"] < 600
        assert client.get(f"{API}/{operation}/series").json()["items"] == []
    settings.dicom_inventory_mb = 8
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        resumed = control(client, operation, "resume")
        assert resumed.status_code == 202, resumed.text
        assert resumed.json()["attempt"] == partial["attempt"] + 1
        complete = wait_operation(client, operation)
        assert complete["status"] == "completed" and complete["summary"]["complete"]
        page = client.get(f"{API}/{operation}/series").json()
        assert page["total"] == 1 and page["items"][0]["n_files"] == 600


@pytest.mark.parametrize("in_project", [False, True])
def test_operation_converts_through_existing_run_authority_and_repeated_command_is_idempotent(
    tmp_path: Path, in_project: bool
) -> None:
    from tests.test_api_ingest import wait

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
            project = client.post("/api/v1/projects", json={"name": "Convert", "packs": []}).json()[
                "project_id"
            ]
            assert (
                client.put(
                    f"/api/v1/projects/{project}/roots/DERIVED",
                    json={"path": str(derived), "role": "derived"},
                ).status_code
                == 200
            )
        started = client.post(
            API,
            json={
                "path": str(source),
                "project_id": project,
                "idempotency_key": "convert-operation-123",
            },
        )
        assert started.status_code == 202, started.text
        operation = started.json()["operation_id"]
        assert wait_operation(client, operation)["status"] == "completed"
        assert control(client, operation, "estimate").status_code == 202
        planned = wait_operation(client, operation)
        request = {
            "expected_revision": planned["revision"],
            "expected_attempt": planned["attempt"],
            "inventory_generation": planned["summary"]["generation"],
            "plan_attempt": planned["plan_attempt"],
            "name": "same-dataset",
        }
        converted = client.post(f"{API}/{operation}/convert", json=request)
        assert converted.status_code == 202, converted.text
        again = client.post(f"{API}/{operation}/convert", json=request)
        assert again.status_code == 202, again.text
        native = None
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            current = client.get(f"{API}/{operation}").json()
            if current.get("conversion_run"):
                native = current["conversion_run"]
                break
            time.sleep(0.02)
        assert native is not None, current
        wait(client, native["job_id"])
        final = client.get(f"{API}/{operation}").json()
        assert final["conversion_run"]["status"] == "completed", final
        prefix = f"/api/v1/projects/{project}" if project else "/api/v1"
        runs = client.get(prefix + "/task-runs").json()
        if isinstance(runs, dict):
            runs = runs["items"]
        conversion = final["conversion_run"]
        assert {(r["task"]["id"], r["run_id"]) for r in runs} == {
            ("dicom.convert", native["run_id"]),
            ("analyzer.phase", conversion["phase_run_id"]),
        }
        assert len([path for path in derived.rglob("*.nii.gz") if path.is_file()]) == 1
        if not in_project:
            assert not (derived / "_datasets" / "same-dataset-1").exists()


def test_worker_crash_is_a_failed_job_and_can_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "source"
    write_series(root, shape=(3, 3, 3), marker=(1, 1, 2))
    settings = Settings(
        workspace_root=tmp_path / "workspace",
        allowed_data_roots=str(root),
        _env_file=None,  # type: ignore[call-arg]
    )
    original = source_operations.run_dicom_worker
    first = True

    async def crash_once(job: Path, **kwargs: Any) -> dict[str, Any]:
        nonlocal first
        if first:
            first = False
            kwargs["on_started"] = lambda pid: os.kill(pid, signal.SIGKILL)
        return await original(job, **kwargs)

    monkeypatch.setattr(source_operations, "run_dicom_worker", crash_once)
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        started = client.post(API, json={"path": str(root), "idempotency_key": "crash-123"}).json()
        operation = started["operation_id"]
        failed = wait_operation(client, operation)
        assert failed["status"] == "failed" and failed["cleanup_verified"]
        job = client.get(f"/api/v1/jobs/{failed['job_id']}").json()
        assert job["status"] == "failed" and job["finished_at"]
        assert control(client, operation, "resume").status_code == 202
        resumed = wait_operation(client, operation)
        assert resumed["status"] == "completed" and resumed["summary"]["dicom"] == 3


@pytest.mark.parametrize("in_project", [False, True])
def test_estimate_is_a_persistent_paged_dry_run_without_outputs(
    tmp_path: Path, in_project: bool
) -> None:
    root = tmp_path / "source"
    for index in range(2):
        write_series(root / f"patient-{index}" / "study" / "series", patient_id=f"P00{index}")
    settings = Settings(
        workspace_root=tmp_path / "workspace",
        allowed_data_roots=str(root),
        _env_file=None,  # type: ignore[call-arg]
    )
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        pid = None
        if in_project:
            pid = client.post("/api/v1/projects", json={"name": "Plan", "packs": []}).json()[
                "project_id"
            ]
        operation = client.post(
            API,
            json={
                "path": str(root),
                "project_id": pid,
                "idempotency_key": "estimate-123",
            },
        ).json()["operation_id"]
        ready = wait_operation(client, operation)
        estimated = client.post(
            f"{API}/{operation}/estimate",
            json={
                "expected_revision": ready["revision"],
                "expected_attempt": ready["attempt"],
                "settings": {"anonymize": "basic", "phase_analyzer": False},
            },
        )
        assert estimated.status_code == 202, estimated.text
        result = wait_operation(client, operation)
        assert result["stage"] == "ready" and result["status"] == "completed", result
        assert result["estimate"]["n_units"] == 2 and result["plan_total"] == 2
        assert result["estimate"]["estimated_total_s"] is None
        first = client.get(f"{API}/{operation}/plan", params={"limit": 1}).json()
        assert first["total"] == 2 and len(first["items"]) == 1
        assert first["items"][0]["patient"] == ""
        assert first["items"][0]["n_files"] == 14 and first["items"][0]["action"] == "convert"
        next_page = client.get(
            f"{API}/{operation}/plan",
            params={
                "limit": 1,
                "cursor": first["next_cursor"],
            },
        ).json()
        assert len(next_page["items"]) == 1 and next_page["next_cursor"] is None
        assert first["items"][0]["case_id"] != next_page["items"][0]["case_id"]
        assert not list(settings.workspace_root.rglob("*.nii.gz"))
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        restored = client.get(f"{API}/{operation}").json()
        assert restored["stage"] == "ready" and restored["estimate"]["n_units"] == 2
        assert client.get(f"{API}/{operation}/plan").json()["total"] == 2


def test_empty_dicom_plan_is_failed_with_confirmed_cleanup(tmp_path: Path) -> None:
    root = tmp_path / "source"
    root.mkdir()
    (root / "notes.txt").write_text("not DICOM")
    settings = Settings(
        workspace_root=tmp_path / "workspace",
        allowed_data_roots=str(root),
        _env_file=None,  # type: ignore[call-arg]
    )
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        operation = client.post(
            API, json={"path": str(root), "idempotency_key": "empty-123"}
        ).json()["operation_id"]
        discovered = wait_operation(client, operation)
        response = client.post(
            f"{API}/{operation}/estimate",
            json={
                "expected_revision": discovered["revision"],
                "expected_attempt": discovered["attempt"],
            },
        )
        assert response.status_code == 202, response.text
        failed = wait_operation(client, operation)
        assert failed["status"] == "failed" and failed["cleanup_verified"]
        assert failed["error"] and failed["plan_attempt"] is None


@pytest.mark.parametrize("stage", ["inventory", "estimate"])
def test_sigkill_backend_then_resume_the_same_durable_operation(tmp_path: Path, stage: str) -> None:
    """D16/D20/D22: real backend process death, cleanup reconciliation and fenced resume."""
    import json

    from app.tasks.dicom_process import group_running, process_identity, signal_owned

    source = tmp_path / "source"
    write_series(source / "P0" / "study" / "series")
    settings = Settings(
        workspace_root=tmp_path / "workspace",
        allowed_data_roots=str(source),
        _env_file=None,  # type: ignore[call-arg]
    )
    marker = tmp_path / "barrier.json"
    script = tmp_path / "backend_process.py"
    script.write_text(
        "import os, signal, sys, time\n"
        "from pathlib import Path\n"
        "from fastapi.testclient import TestClient\n"
        "from app.config import Settings\n"
        "from app.main import create_app\n"
        "from app.core.fsio import atomic_write_json, read_json\n"
        "from app.tasks import source_operations\n"
        "root, source, marker, stage = map(str, sys.argv[1:])\n"
        "original = source_operations.run_dicom_worker\n"
        "async def at_barrier(job, **kwargs):\n"
        "    if read_json(job / 'job.json')['operation'] == stage:\n"
        "        def stop(pid):\n"
        "            os.kill(pid, signal.SIGSTOP)\n"
        "            info = {'pid': pid, 'operation': job.parent.parent.name}\n"
        "            atomic_write_json(Path(marker), info)\n"
        "        kwargs['on_started'] = stop\n"
        "    return await original(job, **kwargs)\n"
        "source_operations.run_dicom_worker = at_barrier\n"
        "settings = Settings(workspace_root=Path(root),\n"
        "                    allowed_data_roots=source, _env_file=None)\n"
        "with TestClient(create_app(settings, inline_jobs=True)) as client:\n"
        "    api = '/api/v1/source-operations'\n"
        "    body = {'path': source, 'idempotency_key': 'restart-123'}\n"
        "    record = client.post(api, json=body).json()\n"
        "    operation = record['operation_id']\n"
        "    if stage == 'estimate':\n"
        "        while record['status'] in {'queued', 'running'}:\n"
        "            time.sleep(.02)\n"
        "            record = client.get(api + '/' + operation).json()\n"
        "        response = client.post(api + '/' + operation + '/estimate', json={\n"
        "            'expected_revision': record['revision'],\n"
        "            'expected_attempt': record['attempt']})\n"
        "        assert response.status_code == 202, response.text\n"
        "    while True: time.sleep(.1)\n"
    )
    backend = Path(__file__).resolve().parents[1]
    with (tmp_path / "backend.log").open("wb") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                str(script),
                str(settings.workspace_root),
                str(source),
                str(marker),
                stage,
            ],
            env={**os.environ, "PYTHONPATH": os.pathsep.join([str(backend), str(backend.parent)])},
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
        owner = None
        try:
            deadline = time.monotonic() + 15
            while not marker.exists() and time.monotonic() < deadline:
                assert process.poll() is None, (tmp_path / "backend.log").read_text()
                time.sleep(0.02)
            stopped = json.loads(marker.read_text())
            owner = process_identity(stopped["pid"])
            process.kill()
            process.wait(timeout=5)
            deadline = time.monotonic() + 3
            while group_running(owner["group"]) and time.monotonic() < deadline:
                time.sleep(0.02)
            assert not group_running(owner["group"])
            with TestClient(create_app(settings, inline_jobs=True)) as client:
                operation = stopped["operation"]
                interrupted = client.get(f"{API}/{operation}").json()
                assert interrupted["status"] == "interrupted" and interrupted["cleanup_verified"]
                resumed = control(client, operation, "resume")
                assert resumed.status_code == 202, resumed.text
                assert resumed.json()["attempt"] == interrupted["attempt"] + 1
                stale = client.post(
                    f"{API}/{operation}/resume",
                    json={
                        "expected_revision": interrupted["revision"],
                        "expected_attempt": interrupted["attempt"],
                    },
                )
                assert (
                    stale.status_code == 202
                    and stale.json()["attempt"] == resumed.json()["attempt"]
                )
                finished = wait_operation(client, operation)
                assert finished["status"] == "completed" and finished["summary"]["dicom"] == 14
                assert finished["stage"] == ("ready" if stage == "estimate" else "discovered")
                if stage == "estimate":
                    assert client.get(f"{API}/{operation}/plan").json()["total"] == 1
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            if owner is not None:
                signal_owned(owner, signal.SIGKILL)
