"""D01/D08/D12, API-19/69: durable detection reuses the completed header inventory."""

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.sources import formats
from tests.test_source_operations_api import wait_operation
from tests.test_sources import ct, nii
from tools.dicom_fixtures import write_series

API = "/api/v1/source-operations"


@pytest.mark.parametrize("target", ["mixed", "nifti", "npy", "dicom", "metadata"])
def test_durable_detection_matches_compatibility_and_survives_restart_without_rescanning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    source = tmp_path / "source"
    image = nii(source / "image.nii.gz", ct())
    np.save(source / "array.npy", np.zeros((3, 4, 5), dtype=np.int16))
    write_series(source / "deep/nested/series", shape=(3, 3, 3), marker=(1, 1, 2))
    (source / "notes.txt").write_text("synthetic non-image")
    (source / "source.json").write_text("{}")
    if target == "metadata":
        (source / "metadata.jsonl").write_text("")
    if target == "mixed":
        for index in range(120):
            nii(source / "nested" / f"image-{index:03}.nii.gz", ct())
    path = {
        "nifti": image,
        "npy": source / "array.npy",
        "dicom": next((source / "deep/nested/series").iterdir()),
    }.get(target, source)
    settings = Settings(
        workspace_root=tmp_path / "workspace", allowed_data_roots=str(source), _env_file=None
    )  # type: ignore[call-arg]
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        legacy = client.post("/api/v1/sources/detect", json={"path": str(path)})
        assert legacy.status_code == 200, legacy.text
        created = client.post(
            API, json={"path": str(path), "purpose": "discover", "idempotency_key": "detection-123"}
        )
        assert created.status_code == 202, created.text
        oid = created.json()["operation_id"]
        completed = wait_operation(client, oid)
        assert completed["status"] == "completed", completed

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("Detection rescanned source files after durable discovery")

    monkeypatch.setattr(formats, "scan", forbidden)
    monkeypatch.setattr(formats, "classify", forbidden)
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        response = client.get(f"{API}/{oid}/detection")
        assert response.status_code == 200, response.text
        assert response.json() == legacy.json()
        repeated = client.get(f"{API}/{oid}/detection")
        assert repeated.json() == response.json()
        assert client.get("/api/v1/projects").json() == []
        assert client.get("/api/v1/task-runs").json() == []


def test_durable_detection_refuses_missing_inventory_without_creating_a_replacement(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    nii(source / "image.nii.gz", ct())
    settings = Settings(
        workspace_root=tmp_path / "workspace", allowed_data_roots=str(source), _env_file=None
    )  # type: ignore[call-arg]
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        created = client.post(
            API,
            json={
                "path": str(source),
                "purpose": "discover",
                "idempotency_key": "missing-inventory",
            },
        )
        oid = created.json()["operation_id"]
        assert wait_operation(client, oid)["status"] == "completed"
        database = settings.workspace_root / "plugins/dicom/operations" / oid / "inventory.sqlite"
        database.unlink()
        response = client.get(f"{API}/{oid}/detection")
        assert response.status_code == 409, response.text
        assert response.json()["actions"] == ["choose_another_path", "home"]
        assert not database.exists()


def test_unfinished_and_cancelled_discovery_offer_no_complete_detection(tmp_path: Path) -> None:
    """D08/D13: never present a queued or cancelled inventory as ready for import."""
    import fcntl

    source = tmp_path / "source"
    nii(source / "image.nii.gz", ct())
    settings = Settings(
        workspace_root=tmp_path / "workspace", allowed_data_roots=str(source), _env_file=None
    )  # type: ignore[call-arg]
    lock = settings.workspace_root / "plugins/dicom/execution.lock"
    lock.parent.mkdir(parents=True)
    with lock.open("a+") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        with TestClient(create_app(settings, inline_jobs=True)) as client:
            created = client.post(
                API,
                json={
                    "path": str(source),
                    "purpose": "discover",
                    "idempotency_key": "queued-detection",
                },
            )
            assert created.status_code == 202, created.text
            oid = created.json()["operation_id"]
            response = client.get(f"{API}/{oid}/detection")
            assert response.status_code == 409, response.text
            assert response.json()["actions"] == ["choose_another_path", "home"]
            for _ in range(3):
                current = client.get(f"{API}/{oid}").json()
                cancelled = client.post(
                    f"{API}/{oid}/cancel",
                    json={
                        "expected_revision": current["revision"],
                        "expected_attempt": current["attempt"],
                    },
                )
                if cancelled.status_code != 409:
                    break
            assert cancelled.status_code == 200, cancelled.text
            assert wait_operation(client, oid)["status"] == "cancelled"
            assert client.get(f"{API}/{oid}/detection").status_code == 409


def test_durable_detection_refuses_an_incompatible_inventory_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D12/D38: old header facts cannot certify a different scanner implementation."""
    from app.tasks import source_inventory

    source = tmp_path / "source"
    nii(source / "image.nii.gz", ct())
    settings = Settings(
        workspace_root=tmp_path / "workspace", allowed_data_roots=str(source), _env_file=None
    )  # type: ignore[call-arg]
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        created = client.post(
            API,
            json={"path": str(source), "purpose": "discover", "idempotency_key": "changed-reader"},
        )
        oid = created.json()["operation_id"]
        assert wait_operation(client, oid)["status"] == "completed"
        monkeypatch.setattr(source_inventory, "scanner_identity", lambda: "different-reader")
        response = client.get(f"{API}/{oid}/detection")
        assert response.status_code == 409, response.text
        assert response.json()["actions"] == ["choose_another_path", "home"]
