from __future__ import annotations

import json
import os
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.path_policy import (
    PathOutsideAllowedRootsError,
    PathPolicyError,
    dataset_key,
    resolve_dataset_path_input,
)
from app.services.path_resolver import resolve_database_path
from app.services import runtime_cache
from app.services import workspace as workspace_service
from app.services.workspace_inspector import inspect_workspace_dataset_path
from app.services import workspace_inspector
from app.services.workspace_store import WorkspaceStore


def _write_nifti(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(np.zeros((4, 5, 6), dtype=np.float32), np.eye(4)), path)
    return path


def _allow_root(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setenv("DATA_ROOT", str(root))
    monkeypatch.delenv("ALLOWED_DATA_ROOTS", raising=False)
    monkeypatch.delenv("ALLOW_UNRESTRICTED_DATA_PATHS", raising=False)
    monkeypatch.delenv("WEBUI_STATE_DIR", raising=False)


@pytest.mark.parametrize(
    ("kind", "builder"),
    [
        (
            "canonical",
            lambda dataset: (
                _write_nifti(dataset / "nifti" / "001_case_00001_0000.nii.gz"),
                (dataset / "database.csv").write_text(
                    "case_id,nifti_path\ncase_00001,nifti/001_case_00001_0000.nii.gz\n",
                    encoding="utf-8",
                ),
            ),
        ),
        (
            "converter_output",
            lambda dataset: (
                _write_nifti(dataset / "nifti" / "001_case_00002_0000.nii.gz"),
                (dataset / "metadata.jsonl").write_text(
                    json.dumps(
                        {
                            "case_id": "case_00002",
                            "relative_path": "nifti/001_case_00002_0000.nii.gz",
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                ),
            ),
        ),
        (
            "nifti_collection",
            lambda dataset: _write_nifti(dataset / "001_case_00004_0000.nii.gz"),
        ),
        (
            "voi_collection",
            lambda dataset: (
                (dataset / "voi" / "images" / "G" / "case_00005" / "NP").mkdir(
                    parents=True
                ),
                np.save(
                    dataset / "voi" / "images" / "G" / "case_00005" / "NP" / "voi_L.npy",
                    np.zeros((4, 5, 6), dtype=np.float32),
                ),
            ),
        ),
        (
            "incomplete",
            lambda dataset: _write_nifti(dataset / "seg" / "case_00006.nii.gz"),
        ),
        ("unsupported", lambda dataset: None),
    ],
)
def test_inspection_classifies_supported_and_invalid_datasets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    builder,
):
    _allow_root(monkeypatch, tmp_path)
    dataset = tmp_path / f"Dataset-{kind}"
    dataset.mkdir()
    builder(dataset)

    result = inspect_workspace_dataset_path(str(dataset))

    assert result.dataset_kind == kind
    assert result.valid is (kind not in {"incomplete", "unsupported"})
    assert result.dataset_key == dataset_key(dataset)
    assert not (dataset / ".webui").exists()


def test_inspection_reports_corrupt_volume_without_creating_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _allow_root(monkeypatch, tmp_path)
    dataset = tmp_path / "DatasetCorrupt"
    dataset.mkdir()
    (dataset / "broken.nii.gz").write_text("not a nifti", encoding="utf-8")

    result = inspect_workspace_dataset_path(str(dataset))

    assert result.dataset_kind == "incomplete"
    assert result.valid is False
    assert any(warning.code == "invalid_volume" for warning in result.warnings)
    assert not (dataset / ".webui").exists()


def test_inspection_counts_nifti_voi_and_masks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _allow_root(monkeypatch, tmp_path)
    dataset = tmp_path / "DatasetCounts"
    dataset.mkdir()
    first = _write_nifti(dataset / "nifti" / "001_case_00001_0000.nii.gz")
    _write_nifti(dataset / "nifti" / "002_case_00002_0000.nii.gz")
    _write_nifti(dataset / "seg" / "001_case_00001.nii.gz")
    voi_image = dataset / "voi" / "images" / "G" / "case_00003" / "NP" / "voi_L.npy"
    voi_image.parent.mkdir(parents=True)
    np.save(voi_image, np.zeros((2, 3, 4), dtype=np.float32))
    voi_mask = dataset / "voi" / "mask" / "G" / "case_00003" / "NP" / "voi_L.npy"
    voi_mask.parent.mkdir(parents=True)
    np.save(voi_mask, np.ones((2, 3, 4), dtype=np.uint8))
    (dataset / "database.csv").write_text(
        f"case_id,nifti_path\ncase_00001,{first.relative_to(dataset)}\n",
        encoding="utf-8",
    )

    result = inspect_workspace_dataset_path(str(dataset))

    assert result.dataset_kind == "canonical"
    assert result.summary.case_count == 3
    assert result.summary.volume_count == 3
    assert result.summary.nifti_count == 2
    assert result.summary.voi_image_count == 1
    assert result.summary.segmentation_count == 1
    assert result.summary.voi_mask_count == 1


def test_inspection_uses_flat_voi_catalog_without_folder_inference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _allow_root(monkeypatch, tmp_path)
    dataset = tmp_path / "DatasetFlatCatalog"
    image_dir = dataset / "voi" / "images" / "case_00001"
    mask_dir = dataset / "voi" / "mask" / "case_00001"
    image_dir.mkdir(parents=True)
    mask_dir.mkdir(parents=True)
    np.save(image_dir / "registered_L.npy", np.zeros((2, 3, 4), dtype=np.float32))
    np.save(image_dir / "not_registered_R.npy", np.zeros((2, 3, 4), dtype=np.float32))
    np.save(mask_dir / "registered_L.npy", np.ones((2, 3, 4), dtype=np.uint8))
    (dataset / "phase.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "phases": [
                    {"case_id": "case_00001", "scan_idx": "000", "phase": "NP"}
                ],
            }
        ),
        encoding="utf-8",
    )
    (dataset / "voi" / "voi_catalog.jsonl").write_text(
        json.dumps(
            {
                "case_id": "case_00001",
                "scan_idx": "000",
                "side": "L",
                "voi_image_path": "images/case_00001/registered_L.npy",
                "voi_mask_path": "mask/case_00001/registered_L.npy",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = inspect_workspace_dataset_path(str(dataset))

    assert result.dataset_kind == "voi_collection"
    assert result.markers.phase_json is True
    assert result.markers.voi_catalog_jsonl is True
    assert result.summary.case_count == 1
    assert result.summary.voi_image_count == 1
    assert result.summary.voi_mask_count == 1


def test_data_root_is_the_default_boundary_and_references_cannot_escape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    outside_volume = _write_nifti(outside / "case_00001.nii.gz")
    dataset = allowed / "DatasetBoundary"
    dataset.mkdir()
    (dataset / "database.csv").write_text(
        f"case_id,nifti_path\ncase_00001,{outside_volume}\n",
        encoding="utf-8",
    )
    _allow_root(monkeypatch, allowed)

    result = inspect_workspace_dataset_path(str(dataset))

    assert result.dataset_kind == "incomplete"
    assert any(warning.code == "forbidden_reference" for warning in result.warnings)
    with pytest.raises(PathOutsideAllowedRootsError):
        inspect_workspace_dataset_path(str(outside))

    assert resolve_database_path(dataset, "nifti/missing.nii.gz").status == "missing"
    assert resolve_database_path(dataset, str(outside_volume)).status == "forbidden"

    escaping = Path("..") / "outside" / outside_volume.name
    assert resolve_database_path(dataset, str(escaping)).status == "forbidden"


def test_multiple_roots_and_explicit_development_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    first = tmp_path / "first"
    second = tmp_path / "second"
    third = tmp_path / "third"
    for root in (first, second, third):
        root.mkdir()
    dataset = second / "DatasetAllowed"
    dataset.mkdir()
    _write_nifti(dataset / "case_00001.nii.gz")
    monkeypatch.setenv("DATA_ROOT", str(first))
    monkeypatch.setenv("ALLOWED_DATA_ROOTS", os.pathsep.join((str(first), str(second))))
    monkeypatch.delenv("ALLOW_UNRESTRICTED_DATA_PATHS", raising=False)

    assert inspect_workspace_dataset_path(str(dataset)).valid is True

    outside_dataset = third / "DatasetDev"
    outside_dataset.mkdir()
    _write_nifti(outside_dataset / "case_00002.nii.gz")
    with pytest.raises(PathOutsideAllowedRootsError):
        inspect_workspace_dataset_path(str(outside_dataset))

    monkeypatch.setenv("ALLOW_UNRESTRICTED_DATA_PATHS", "true")
    assert inspect_workspace_dataset_path(str(outside_dataset)).valid is True


def test_symlink_escape_is_rejected_when_supported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    target = outside / "DatasetOutside"
    target.mkdir()
    _write_nifti(target / "case_00001.nii.gz")
    link = allowed / "DatasetLink"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are not available in this test environment")
    _allow_root(monkeypatch, allowed)

    with pytest.raises(PathOutsideAllowedRootsError):
        inspect_workspace_dataset_path(str(link))


def test_referenced_symlink_escape_is_forbidden_when_supported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    outside_volume = _write_nifti(outside / "case_00001.nii.gz")
    dataset = allowed / "DatasetReferenceLink"
    (dataset / "nifti").mkdir(parents=True)
    link = dataset / "nifti" / "case_00001.nii.gz"
    try:
        link.symlink_to(outside_volume)
    except OSError:
        pytest.skip("File symlinks are not available in this test environment")
    (dataset / "database.csv").write_text(
        "case_id,nifti_path\ncase_00001,nifti/case_00001.nii.gz\n",
        encoding="utf-8",
    )
    _allow_root(monkeypatch, allowed)

    result = inspect_workspace_dataset_path(str(dataset))

    assert result.valid is False
    assert result.dataset_kind == "incomplete"
    assert any(warning.code == "forbidden_reference" for warning in result.warnings)


def test_dataset_path_syntax_and_directory_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _allow_root(monkeypatch, tmp_path)
    file_path = tmp_path / "not-a-directory"
    file_path.write_text("x", encoding="utf-8")

    with pytest.raises(PathPolicyError):
        resolve_dataset_path_input("bad\x00path")
    with pytest.raises(PathPolicyError):
        resolve_dataset_path_input("a" * 4097)
    with pytest.raises(PathPolicyError):
        resolve_dataset_path_input(str(file_path))
    with pytest.raises(FileNotFoundError):
        resolve_dataset_path_input(str(tmp_path / "missing"))


def test_workspace_store_migrates_legacy_payload_and_keeps_five_recent(tmp_path: Path):
    store_path = tmp_path / "workspace.json"
    legacy = tmp_path / "DatasetLegacy"
    legacy.mkdir()
    store_path.write_text(json.dumps({"dataset_path": str(legacy)}), encoding="utf-8")
    store = WorkspaceStore(store_path)

    migrated_view = store.get()

    assert migrated_view.configured is True
    assert migrated_view.dataset_key == dataset_key(legacy)
    assert [item.dataset_path for item in migrated_view.recent_datasets] == [str(legacy.resolve())]

    datasets = []
    for index in range(6):
        dataset = tmp_path / f"Dataset{index}"
        dataset.mkdir()
        datasets.append(dataset)
        store.set(dataset, "nifti_collection")

    status = store.get()
    assert len(status.recent_datasets) == 5
    assert status.recent_datasets[0].dataset_path == str(datasets[-1].resolve())
    assert str(legacy.resolve()) not in [item.dataset_path for item in status.recent_datasets]

    cleared = store.clear()
    assert cleared.configured is False
    assert len(cleared.recent_datasets) == 5

    removed_key = cleared.recent_datasets[0].dataset_key
    after_remove = store.remove_recent(removed_key)
    assert all(item.dataset_key != removed_key for item in after_remove.recent_datasets)

    active = store.set(datasets[0], "nifti_collection")
    without_active_recent = store.remove_recent(active.dataset_key or "")
    assert without_active_recent.configured is True
    assert without_active_recent.dataset_path == active.dataset_path
    assert all(
        item.dataset_key != active.dataset_key
        for item in without_active_recent.recent_datasets
    )


def test_workspace_store_deduplicates_keys_but_keeps_duplicate_folder_names(tmp_path: Path):
    store = WorkspaceStore(tmp_path / "workspace.json")
    first = tmp_path / "one" / "DatasetSame"
    second = tmp_path / "two" / "DatasetSame"
    first.mkdir(parents=True)
    second.mkdir(parents=True)

    store.set(first, "nifti_collection")
    store.set(second, "nifti_collection")
    status = store.set(first, "nifti_collection")

    assert len(status.recent_datasets) == 2
    assert {item.display_name for item in status.recent_datasets} == {"DatasetSame"}
    assert len({item.dataset_key for item in status.recent_datasets}) == 2


def test_references_reject_nulls_and_excessive_length(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _allow_root(monkeypatch, tmp_path)
    dataset = tmp_path / "DatasetInvalidReferences"
    dataset.mkdir()

    assert resolve_database_path(dataset, "bad\x00path.nii.gz").status == "unreadable"
    assert resolve_database_path(dataset, "a" * 4097).status == "unreadable"


def test_scan_entry_limit_is_blocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _allow_root(monkeypatch, tmp_path)
    monkeypatch.setattr(workspace_inspector, "MAX_INSPECTION_ENTRIES", 2)
    dataset = tmp_path / "DatasetLarge"
    dataset.mkdir()
    (dataset / "metadata.jsonl").write_text(
        "\n".join(
            json.dumps({"case_id": f"case_{index:05d}", "relative_path": f"missing-{index}.nii.gz"})
            for index in range(1, 4)
        )
        + "\n",
        encoding="utf-8",
    )

    result = inspect_workspace_dataset_path(str(dataset))

    assert result.valid is False
    assert any(
        warning.code == "inspection_limit_exceeded" and warning.severity == "error"
        for warning in result.warnings
    )


def test_warning_details_are_bounded_while_total_is_preserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _allow_root(monkeypatch, tmp_path)
    monkeypatch.setattr(workspace_inspector, "MAX_WARNING_DETAILS", 2)
    dataset = tmp_path / "DatasetWarnings"
    dataset.mkdir()
    (dataset / "metadata.jsonl").write_text(
        "\n".join(
            json.dumps({"case_id": f"case_{index:05d}", "relative_path": f"missing-{index}.nii.gz"})
            for index in range(1, 4)
        )
        + "\n",
        encoding="utf-8",
    )

    result = inspect_workspace_dataset_path(str(dataset))

    assert len(result.warnings) == 2
    assert result.summary.warning_count == 4
    assert result.summary.warnings_truncated is True


def test_scan_depth_limit_is_blocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _allow_root(monkeypatch, tmp_path)
    monkeypatch.setattr(workspace_inspector, "MAX_INSPECTION_DEPTH", 1)
    dataset = tmp_path / "DatasetDeep"
    deep = dataset / "voi" / "images" / "group" / "case_00001" / "NP"
    deep.mkdir(parents=True)
    np.save(deep / "voi_L.npy", np.zeros((2, 2, 2), dtype=np.float32))

    result = inspect_workspace_dataset_path(str(dataset))

    assert result.valid is False
    assert any(warning.code == "inspection_limit_exceeded" for warning in result.warnings)


def test_external_state_directory_is_reported_without_being_created(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _allow_root(monkeypatch, tmp_path)
    dataset = tmp_path / "DatasetExternalState"
    dataset.mkdir()
    _write_nifti(dataset / "case_00001.nii.gz")
    state_root = tmp_path / "state-root"
    monkeypatch.setenv("WEBUI_STATE_DIR", str(state_root))

    result = inspect_workspace_dataset_path(str(dataset))

    assert result.state.path == str((state_root / dataset.name).resolve())
    assert result.state.exists is False
    assert result.state.writable is True
    assert not state_root.exists()


def test_inspect_and_failed_activation_leave_workspace_and_caches_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _allow_root(monkeypatch, tmp_path)
    valid = tmp_path / "DatasetValid"
    valid.mkdir()
    _write_nifti(valid / "case_00001.nii.gz")
    incomplete = tmp_path / "DatasetIncomplete"
    (incomplete / "seg").mkdir(parents=True)
    _write_nifti(incomplete / "seg" / "case_00002.nii.gz")
    store = WorkspaceStore(tmp_path / "workspace.json")
    monkeypatch.setattr(workspace_service, "workspace_store", store)
    resets: list[str] = []
    monkeypatch.setattr(runtime_cache, "reset_runtime_caches", lambda: resets.append("reset"))

    activated = workspace_service.set_workspace_dataset_path(str(valid))
    stored_before = store.path.read_bytes()
    inspected = workspace_service.inspect_workspace(str(incomplete))

    assert activated.dataset_path == str(valid.resolve())
    assert inspected.valid is False
    assert store.path.read_bytes() == stored_before
    assert resets == ["reset"]

    workspace_service.set_workspace_dataset_path(str(valid))
    assert resets == ["reset"]
    stored_before = store.path.read_bytes()

    with pytest.raises(ValueError):
        workspace_service.set_workspace_dataset_path(str(incomplete))

    assert store.path.read_bytes() == stored_before
    assert resets == ["reset"]


def test_workspace_api_inspects_then_activates_and_manages_recent_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    _allow_root(monkeypatch, allowed)
    monkeypatch.delenv("RADIOLOGY_UI_TOKEN", raising=False)
    dataset = allowed / "DatasetApi"
    dataset.mkdir()
    _write_nifti(dataset / "case_00001.nii.gz")
    store = WorkspaceStore(tmp_path / "workspace.json")
    monkeypatch.setattr(workspace_service, "workspace_store", store)
    client = TestClient(app)

    inspection_response = client.post(
        "/api/workspace/inspect",
        json={"dataset_path": str(dataset)},
    )

    assert inspection_response.status_code == 200
    assert inspection_response.json()["dataset_kind"] == "nifti_collection"
    assert not store.path.exists()

    activation_response = client.put(
        "/api/workspace",
        json={"dataset_path": str(dataset)},
    )
    assert activation_response.status_code == 200
    activated = activation_response.json()
    assert activated["dataset_key"] == dataset_key(dataset)
    assert len(activated["recent_datasets"]) == 1

    clear_response = client.delete("/api/workspace")
    assert clear_response.status_code == 200
    assert clear_response.json()["configured"] is False
    assert len(clear_response.json()["recent_datasets"]) == 1

    remove_response = client.delete(
        "/api/workspace",
        params={"recent_key": dataset_key(dataset)},
    )
    assert remove_response.status_code == 200
    assert remove_response.json()["recent_datasets"] == []

    outside = tmp_path / "outside"
    outside.mkdir()
    forbidden_response = client.post(
        "/api/workspace/inspect",
        json={"dataset_path": str(outside)},
    )
    assert forbidden_response.status_code == 403
