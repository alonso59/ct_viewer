"""D07/D32: aggregate inventory admission and retention preserve recoverable work."""

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.test_api_ingest import ctx_of
from tests.test_source_operations_api import wait_operation
from tests.test_sources import ct, nii

API = "/api/v1/source-operations"


def start(client: TestClient, source: Path, key: str, **extra: object) -> dict:
    response = client.post(
        API,
        json={
            "path": str(source),
            "purpose": "discover",
            "idempotency_key": key,
            **extra,
        },
    )
    assert response.status_code == 202, response.text
    return wait_operation(client, response.json()["operation_id"])


def test_aggregate_budget_refuses_growth_and_resumes_after_budget_increase(tmp_path: Path) -> None:
    source = tmp_path / "source"
    nii(source / "image.nii.gz", ct())
    settings = Settings(
        workspace_root=tmp_path / "workspace",
        allowed_data_roots=str(source),
        dicom_inventory_total_mb=1,
        _env_file=None,
    )  # type: ignore[call-arg]
    root = settings.workspace_root / "plugins/dicom/operations"
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        first = start(client, source, "aggregate-first")
        assert first["status"] == "completed", first
        database = root / first["operation_id"] / "inventory.sqlite"
        digest = hashlib.sha256(database.read_bytes()).hexdigest()
        refused = start(client, source, "aggregate-second")
        assert refused["status"] == "failed", refused
        assert "DICOM_INVENTORY_TOTAL_MB" in refused["error"]
        assert not (root / refused["operation_id"] / "inventory.sqlite").exists()
        assert hashlib.sha256(database.read_bytes()).hexdigest() == digest
    settings = settings.model_copy(update={"dicom_inventory_total_mb": 2})
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        current = client.get(f"{API}/{refused['operation_id']}").json()
        response = client.post(
            f"{API}/{current['operation_id']}/resume",
            json={
                "expected_revision": current["revision"],
                "expected_attempt": current["attempt"],
            },
        )
        assert response.status_code == 202, response.text
        resumed = wait_operation(client, current["operation_id"])
        assert resumed["status"] == "completed", resumed
        assert resumed["operation_id"] == refused["operation_id"]
        assert hashlib.sha256(database.read_bytes()).hexdigest() == digest


def test_retention_protects_open_sessions_import_drafts_and_interrupted_work(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    nii(source / "image.nii.gz", ct())
    settings = Settings(
        workspace_root=tmp_path / "workspace", allowed_data_roots=str(source), _env_file=None
    )  # type: ignore[call-arg]
    root = settings.workspace_root / "plugins/dicom/operations"
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        finished = start(client, source, "retention-finished")
        opened = start(client, source, "retention-open", purpose="open")
        draft = start(client, source, "retention-draft", import_context={"alias": "IMAGES"})
        recoverable = start(client, source, "retention-interrupted")
        for record in (finished, opened, draft, recoverable):
            path = root / record["operation_id"] / "operation.json"
            data = json.loads(path.read_text())
            data["updated_at"] = "2000-01-01T00:00:00Z"
            if record is recoverable:
                data["status"] = "interrupted"
            path.write_text(json.dumps(data))
        service = ctx_of(client).source_operations
        assert client.portal is not None
        assert client.portal.call(service.prune_inventories) == 1
        assert not (root / finished["operation_id"] / "inventory.sqlite").exists()
        assert client.get(f"{API}/{finished['operation_id']}/series").status_code == 409
        assert client.get(f"{API}/{finished['operation_id']}").json()["summary"][
            "inventory_expired"
        ]
        for record in (opened, draft, recoverable):
            assert (root / record["operation_id"] / "inventory.sqlite").is_file()
        assert client.portal.call(service.prune_inventories) == 0
        response = client.post(f"{API}/{opened['operation_id']}/open")
        assert response.status_code == 201, response.text
        assert client.delete(f"/api/v1/open/{opened['operation_id']}").status_code == 204
        assert client.portal.call(service.prune_inventories) == 1
        assert (root / draft["operation_id"] / "inventory.sqlite").is_file()
        assert (root / recoverable["operation_id"] / "inventory.sqlite").is_file()


@pytest.mark.parametrize("damage", ["torn_json", "old_version", "future_version", "missing_source"])
def test_corrupt_history_does_not_prevent_startup_or_other_operations(
    tmp_path: Path, damage: str
) -> None:
    source = tmp_path / "source"
    nii(source / "image.nii.gz", ct())
    settings = Settings(
        workspace_root=tmp_path / "workspace", allowed_data_roots=str(source), _env_file=None
    )  # type: ignore[call-arg]
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        original = start(client, source, "damaged-history")
    record = (
        settings.workspace_root
        / "plugins/dicom/operations"
        / original["operation_id"]
        / "operation.json"
    )
    saved = json.loads(record.read_text())
    if damage == "torn_json":
        damaged = b'{"version": '
    else:
        if damage == "missing_source":
            del saved["source"]
        else:
            saved["version"] = 0 if damage == "old_version" else 2
        damaged = json.dumps(saved).encode()
    record.write_bytes(damaged)
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        response = client.get(f"{API}/{original['operation_id']}")
        assert response.status_code == 409
        assert "damaged" in response.json()["detail"]
        assert client.get(API).status_code == 200
        fresh = start(client, source, "after-damaged-history")
        assert fresh["status"] == "completed", fresh
        assert record.read_bytes() == damaged
