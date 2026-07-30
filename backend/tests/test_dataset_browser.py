from __future__ import annotations

import csv
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services import workspace as workspace_service
from app.services.workspace_store import WorkspaceStore


def test_dataset_browser_lists_only_configured_roots(tmp_path, monkeypatch):
    parent = tmp_path / "mounted-data"
    dataset = _make_lightweight_dataset(parent)
    monkeypatch.setenv("DATASET_DIR", str(parent))
    monkeypatch.delenv("DATASET_ROOTS", raising=False)

    client = TestClient(app)

    roots = client.get("/api/dataset-browser/roots").json()["roots"]
    assert any(root["path"] == str(parent.resolve()) for root in roots)

    listing = client.get("/api/dataset-browser/list", params={"path": str(parent)})
    assert listing.status_code == 200
    entries = listing.json()["entries"]
    assert any(
        entry["name"] == dataset.name and entry["maybe_has_dataset_structure"]
        for entry in entries
    )

    outside = client.get("/api/dataset-browser/list", params={"path": str(tmp_path)})
    assert outside.status_code == 403


def test_validate_selection_activates_valid_dataset_folder(tmp_path, monkeypatch):
    parent = tmp_path / "mounted-data"
    dataset = _make_lightweight_dataset(parent)
    monkeypatch.setenv("DATASET_DIR", str(parent))
    monkeypatch.setattr(
        workspace_service,
        "workspace_store",
        WorkspaceStore(tmp_path / "workspace.json"),
    )

    client = TestClient(app)
    response = client.post(
        "/api/workspace/validate-selection",
        json={"dataset_folder_path": str(dataset)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is True
    assert payload["activated"] is True
    assert payload["workspace"]["configured"] is True
    assert payload["summary"]["dataset_root"] == str(dataset.resolve())
    assert payload["summary"]["database_csv_path"] == str((dataset / "database.csv").resolve())
    assert payload["summary"]["row_count"] == 2
    assert payload["summary"]["case_count"] == 2
    assert payload["summary"]["sampled_referenced_files"] > 0
    assert payload["errors"] == []


def test_validate_selection_infers_dataset_root_from_database_paths(tmp_path, monkeypatch):
    parent = tmp_path / "mounted-data"
    dataset = _make_lightweight_dataset(parent)
    metadata = tmp_path / "metadata"
    metadata.mkdir()
    external_database = metadata / "database.csv"
    external_database.write_text((dataset / "database.csv").read_text(encoding="utf-8"), encoding="utf-8")
    (dataset / "database.csv").unlink()
    monkeypatch.setenv("DATASET_DIR", str(parent))
    monkeypatch.setattr(
        workspace_service,
        "workspace_store",
        WorkspaceStore(tmp_path / "workspace.json"),
    )

    client = TestClient(app)
    response = client.post(
        "/api/workspace/validate-selection",
        json={"database_csv_path": str(external_database)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is True
    assert payload["activated"] is True
    assert payload["summary"]["dataset_root"] == str(dataset.resolve())
    assert payload["summary"]["database_csv_path"] == str(external_database.resolve())
    assert payload["workspace"]["database_csv_path"] == str(external_database.resolve())

    validation = client.get("/api/datasets/DatasetLite/database/validation")
    assert validation.status_code == 200
    assert validation.json()["row_count"] == 2


def test_validate_selection_blocks_missing_database_csv(tmp_path, monkeypatch):
    dataset = tmp_path / "DatasetMissingDatabase"
    dataset.mkdir()
    monkeypatch.setattr(
        workspace_service,
        "workspace_store",
        WorkspaceStore(tmp_path / "workspace.json"),
    )

    client = TestClient(app)
    response = client.post(
        "/api/workspace/validate-selection",
        json={"dataset_folder_path": str(dataset)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is False
    assert payload["activated"] is False
    assert any(error["code"] == "missing_database" for error in payload["errors"])


def _make_lightweight_dataset(parent: Path) -> Path:
    dataset = parent / "DatasetLite"
    (dataset / "nifti").mkdir(parents=True)
    (dataset / "seg").mkdir()
    (dataset / "voi" / "images").mkdir(parents=True)
    (dataset / "voi" / "mask").mkdir(parents=True)
    (dataset / "nifti" / "case_00001_0000.nii.gz").write_bytes(b"placeholder")
    (dataset / "nifti" / "case_00002_0000.nii.gz").write_bytes(b"placeholder")
    (dataset / "seg" / "case_00001.nii.gz").write_bytes(b"placeholder")
    (dataset / "voi" / "images" / "case_00001_L.npy").write_bytes(b"placeholder")
    (dataset / "voi" / "mask" / "case_00001_L.npy").write_bytes(b"placeholder")

    rows = [
        {
            "row_id": "row-1",
            "case_id": "case_00001",
            "patient_id": "case_00001",
            "group": "G",
            "phase": "ven",
            "scan_idx": "0",
            "side": "L",
            "nifti_path": "nifti/case_00001_0000.nii.gz",
            "seg_path": "seg/case_00001.nii.gz",
            "voi_image_path": "voi/images/case_00001_L.npy",
            "voi_mask_path": "voi/mask/case_00001_L.npy",
            "has_seg": "true",
            "has_voi_image": "true",
            "has_voi_mask": "true",
        },
        {
            "row_id": "row-2",
            "case_id": "case_00002",
            "patient_id": "case_00002",
            "group": "G",
            "phase": "art",
            "scan_idx": "0",
            "side": "R",
            "nifti_path": "nifti/case_00002_0000.nii.gz",
            "seg_path": "",
            "voi_image_path": "",
            "voi_mask_path": "",
            "has_seg": "false",
            "has_voi_image": "false",
            "has_voi_mask": "false",
        },
    ]
    with (dataset / "database.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return dataset
