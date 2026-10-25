"""D08/U08, SRC-19/API-69: import discovery keeps its draft context on the server."""

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.tasks.source_operations import SourceOperationStart
from tests.test_source_operations_api import wait_operation
from tests.test_sources import ct, nii

API = "/api/v1/source-operations"


def test_import_discovery_context_survives_api_restart(tmp_path: Path) -> None:
    source = tmp_path / "source"
    nii(source / "image.nii.gz", ct())
    settings = Settings(
        workspace_root=tmp_path / "workspace", allowed_data_roots=str(source), _env_file=None
    )  # type: ignore[call-arg]
    context = {
        "alias": "IMAGES",
        "adapter": "nifti-files",
        "add": True,
        "options": {"include": ["image.nii.gz"], "modality": "MR"},
    }
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        created = client.post(
            API,
            json={
                "path": str(source),
                "purpose": "discover",
                "idempotency_key": "import-context-123",
                "import_context": context,
            },
        )
        assert created.status_code == 202, created.text
        oid = created.json()["operation_id"]
        assert wait_operation(client, oid)["status"] == "completed"
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        restored = client.get(f"{API}/{oid}").json()
        assert {key: restored["import_context"][key] for key in context} == context
        assert restored["conversion_run_id"] is None
        refused = client.post(
            f"{API}/{oid}/estimate",
            json={
                "expected_revision": restored["revision"],
                "expected_attempt": restored["attempt"],
                "settings": {},
            },
        )
        assert refused.status_code == 409, refused.text
        assert "separate conversion" in refused.json()["detail"]
        assert client.get("/api/v1/projects").json() == []


@pytest.mark.parametrize(
    "purpose,prepare", [("open", False), ("convert", False), ("discover", True)]
)
def test_import_context_cannot_start_unrelated_work(
    tmp_path: Path, purpose: str, prepare: bool
) -> None:
    source = tmp_path / "source"
    nii(source / "image.nii.gz", ct())
    settings = Settings(
        workspace_root=tmp_path / "workspace", allowed_data_roots=str(source), _env_file=None
    )  # type: ignore[call-arg]
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        response = client.post(
            API,
            json={
                "path": str(source),
                "purpose": purpose,
                "prepare_plan": prepare,
                "idempotency_key": "invalid-context-123",
                "import_context": {"alias": "DATA"},
            },
        )
        assert response.status_code == 422, response.text
        assert not list(
            (settings.workspace_root / "plugins/dicom/operations").glob("*/operation.json")
        )


def test_legacy_discovery_receipt_keeps_its_hash_when_no_context_is_requested(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    nii(source / "image.nii.gz", ct())
    settings = Settings(
        workspace_root=tmp_path / "workspace", allowed_data_roots=str(source), _env_file=None
    )  # type: ignore[call-arg]
    body = {"path": str(source), "purpose": "discover", "idempotency_key": "legacy-context-123"}
    payload = SourceOperationStart.model_validate(body).model_dump(mode="json")
    payload.pop("import_context", None)
    legacy_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        first = client.post(API, json=body)
        assert first.status_code == 202, first.text
        assert first.json()["request_hash"] == legacy_hash
        assert client.post(API, json=body).json()["operation_id"] == first.json()["operation_id"]


def import_source(client: TestClient, source: Path) -> tuple[str, str]:
    pid = client.post("/api/v1/projects", json={"name": "Durable import"}).json()["project_id"]
    response = client.post(
        API,
        json={
            "path": str(source),
            "purpose": "discover",
            "project_id": pid,
            "idempotency_key": "durable-import-source",
            "import_context": {"alias": "DATA"},
        },
    )
    assert response.status_code == 202, response.text
    oid = response.json()["operation_id"]
    current = wait_operation(client, oid)
    response = client.post(
        f"{API}/{oid}/import-draft",
        json={
            "expected_revision": current["revision"],
            "expected_attempt": current["attempt"],
            "project_id": pid,
            "alias": "IMAGES",
            "adapter": "nifti-files",
            "options": {"include": ["image.nii.gz"], "case_id_from": "stem", "modality": "MR"},
        },
    )
    assert response.status_code == 200, response.text
    return pid, oid


def import_command(client: TestClient, oid: str, action: str) -> dict:
    current = client.get(f"{API}/{oid}").json()
    response = client.post(
        f"{API}/{oid}/{action}",
        json={
            "expected_revision": current["revision"],
            "expected_attempt": current["attempt"],
        },
    )
    assert response.status_code in {200, 202}, response.text
    return response.json()


def test_preview_and_committed_import_restore_without_duplicate_snapshots(tmp_path: Path) -> None:
    """U02/U06: both later stages outlive the window and the API process."""
    source = tmp_path / "source"
    image = nii(source / "image.nii.gz", ct())
    before = hashlib.sha256(image.read_bytes()).hexdigest()
    settings = Settings(
        workspace_root=tmp_path / "workspace", allowed_data_roots=str(source), _env_file=None
    )  # type: ignore[call-arg]
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        pid, oid = import_source(client, source)
        import_command(client, oid, "import-preview")
        prepared = wait_operation(client, oid)
        assert prepared["status"] == "completed", prepared
        assert prepared["import_context"]["step"] == "preview"
        assert prepared["import_preview"]["counts"]["cases"] == 1
        preview_id = prepared["import_preview"]["preview_id"]
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        restored = client.get(f"{API}/{oid}").json()
        assert restored["import_preview"]["preview_id"] == preview_id
        assert restored["import_context"]["alias"] == "IMAGES"
        import_command(client, oid, "import-commit")
        committed = wait_operation(client, oid)
        assert committed["status"] == "completed", committed
        import_id = committed["import_context"]["import_id"]
        assert client.get(f"/api/v1/projects/{pid}/imports").json()["total"] == 1
        snapshot = (
            client.app.state.ctx.workspace.project_dir(pid)
            / "sources"
            / import_id
            / "metadata.jsonl"
        )
        digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        restored = client.get(f"{API}/{oid}").json()
        assert restored["status"] == "completed", restored
        assert import_command(client, oid, "resume")["status"] == "completed"
        assert import_command(client, oid, "import-commit")["status"] == "completed"
        history = client.get(f"/api/v1/projects/{pid}/imports").json()
        assert history["total"] == 1 and history["items"][0]["import_id"] == import_id
        assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == digest
    assert hashlib.sha256(image.read_bytes()).hexdigest() == before


def test_import_preview_cancel_drains_then_resumes_its_saved_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """U07: generic import cancellation never terminates the shared worker pool."""
    import asyncio
    import threading

    from tests.test_api_ingest import ctx_of

    source = tmp_path / "source"
    nii(source / "image.nii.gz", ct())
    settings = Settings(
        workspace_root=tmp_path / "workspace", allowed_data_roots=str(source), _env_file=None
    )  # type: ignore[call-arg]
    entered, release = threading.Event(), threading.Event()
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        _, oid = import_source(client, source)
        service = ctx_of(client).source_operations.ingest
        original = service.preview

        async def blocked(*args, **kwargs):
            entered.set()
            if not await asyncio.to_thread(release.wait, 10):
                raise TimeoutError("test preview barrier was not released")
            return await original(*args, **kwargs)

        monkeypatch.setattr(service, "preview", blocked)
        try:
            import_command(client, oid, "import-preview")
            assert entered.wait(5)
            cancelling = import_command(client, oid, "cancel")
            assert cancelling["status"] == "cancelling" and not cancelling["cleanup_verified"]
        finally:
            release.set()
        stopped = wait_operation(client, oid)
        assert stopped["status"] == "cancelled" and stopped["cleanup_verified"]
        assert stopped["import_context"]["preview_id"] is None
        import_command(client, oid, "resume")
        restored = wait_operation(client, oid)
        assert restored["status"] == "completed", restored
        assert restored["import_context"]["alias"] == "IMAGES"
        assert restored["import_preview"]["counts"]["cases"] == 1
