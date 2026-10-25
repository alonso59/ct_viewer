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
        assert restored["import_context"] == context
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
