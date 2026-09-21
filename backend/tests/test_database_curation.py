from __future__ import annotations

import csv
import hashlib
from io import BytesIO
import json
from pathlib import Path
import shutil
import time

import nibabel as nib
import numpy as np
from PIL import Image

from app.models.curation import CurationDecisionRequest
from app.models.review import ReviewOperation
from app.services.curation_store import (
    correction_queue_csv,
    list_correction_queue,
    save_curation_decision,
)
from app.services.database import (
    get_case_load_source,
    list_case_inventory,
    list_case_summaries,
    reset_database_index,
)
from app.services.discovery import discover_series, reset_discovery_index
from app.services.metadata_sync import apply_metadata_sync, preview_metadata_sync
from app.services.qc_validator import validate_database
from app.services.review_apply import (
    apply_review_operations,
    list_recent_delete_decisions,
    undo_delete_decision,
)
from app.services.slice_renderer import render_slice
from app.services.volume_cache import volume_cache


def test_database_loading_validation_projection_and_read_only_curation(tmp_path, monkeypatch):
    dataset = _make_dataset(tmp_path)
    state_dir = tmp_path / "state"
    monkeypatch.setenv("WEBUI_STATE_DIR", str(state_dir))
    reset_database_index()
    volume_cache.reset()

    validation = validate_database(dataset)
    assert validation.row_count == 4
    assert validation.case_count == 1
    assert all(column.present for column in validation.required_columns)
    assert validation.duplicate_row_identities
    assert validation.duplicate_scope_combinations
    assert validation.missing_seg
    assert validation.missing_voi_image
    assert validation.missing_voi_mask
    assert validation.ambiguous_phase
    assert validation.ambiguous_side

    summaries = list_case_summaries(dataset)
    assert len(summaries) == 1
    assert summaries[0].case_id == "case_00001"
    assert summaries[0].available_phases == ["NP", "CMP", "UNK"]
    assert summaries[0].warning_count > 0

    inventory = list_case_inventory(dataset, "case_00001")
    assert inventory[0].row_index == 0
    assert inventory[1].row_index == 1
    assert inventory[0].nifti_path.status == "exists"
    assert inventory[0].seg_path.status == "exists"
    assert inventory[0].voi_image_path.status == "exists"
    assert inventory[0].scope_availability["complete"] is True
    assert inventory[0].scope_availability["voi"] is True

    full_source = get_case_load_source(dataset, "case_00001", "dup-row", "complete")
    duplicate_row_source = get_case_load_source(
        dataset,
        "case_00001",
        "dup-row",
        "complete",
        row_index=1,
    )
    assert duplicate_row_source.row_index == 1
    full_info = volume_cache.load_case_source(
        dataset_id="DatasetTest",
        case_id="case_00001",
        series_id=full_source.series_id,
        image_path=full_source.image_path,
        mask_path=full_source.mask_path,
        source_type=full_source.source_type,
        cache_key_suffix="full",
    )
    assert full_info.shape == [4, 4, 4]
    assert full_info.labels == [1, 2]

    voi_nifti_source = get_case_load_source(dataset, "case_00001", "voi-nifti", "voi")
    voi_info = volume_cache.load_case_source(
        dataset_id="DatasetTest",
        case_id="case_00001",
        series_id=voi_nifti_source.series_id,
        image_path=voi_nifti_source.image_path,
        mask_path=voi_nifti_source.mask_path,
        source_type=voi_nifti_source.source_type,
        cache_key_suffix="voi-nifti",
    )
    assert voi_info.shape == [2, 2, 2]

    before = _fingerprints(
        [
            dataset / "database.csv",
            dataset / "nifti" / "scan_0000.nii.gz",
            dataset / "seg" / "scan.nii.gz",
            dataset / "voi" / "images" / "G" / "case_00001" / "scan_L.npy",
            dataset / "voi" / "mask" / "G" / "case_00001" / "scan_L.npy",
        ]
    )
    time.sleep(0.01)
    decision = save_curation_decision(
        dataset,
        "DatasetTest",
        CurationDecisionRequest(
            case_id="case_00001",
            row_id="dup-row",
            scope="complete",
            target="SEG",
            status="accepted",
            priority="medium",
            comment="Looks usable.",
            reviewer="doctor",
            add_to_queue=True,
        ),
    )
    after = _fingerprints(before.keys())
    assert before == after
    assert decision.review_id
    assert (state_dir / "DatasetTest" / "curation_review.csv").is_file()
    assert list_correction_queue(dataset, "DatasetTest").items[0].comment == "Looks usable."
    assert "Looks usable." in correction_queue_csv(dataset, "DatasetTest")



def test_converter_metadata_jsonl_drives_phase_curation_and_trash(tmp_path, monkeypatch):
    dataset = _make_converter_metadata_dataset(tmp_path)
    state_dir = tmp_path / "state"
    monkeypatch.setenv("ALLOW_DATA_MUTATIONS", "true")
    monkeypatch.setenv("WEBUI_STATE_DIR", str(state_dir))

    import app.services.review_apply as review_apply

    monkeypatch.setattr(review_apply, "validate_workspace_dataset_id", lambda dataset_id: dataset)
    monkeypatch.setattr(review_apply, "workspace_file", lambda filename, create=True: state_dir / filename)
    reset_database_index()
    reset_discovery_index()
    volume_cache.reset()

    validation = validate_database(dataset)
    assert validation.has_database is True
    assert validation.source_file == "metadata.jsonl"
    assert validation.row_count == 2
    assert validation.case_count == 1

    summaries = list_case_summaries(dataset)
    assert summaries[0].case_id == "case_00001"
    assert summaries[0].available_phases == ["NP", "CMP"]
    assert summaries[0].group == "NG"

    inventory = list_case_inventory(dataset, "case_00001")
    assert [row.canonical_phase for row in inventory] == ["NP", "CMP"]
    assert inventory[1].raw_phase == "CMP"
    assert inventory[1].phase_status == "normalized"
    assert inventory[0].scope_availability["complete"] is True

    readonly_before = _fingerprints(
        [
            dataset / "metadata.jsonl",
            dataset / "curation.csv",
        ]
    )
    response = apply_review_operations(
        "DatasetMeta",
        [
            ReviewOperation(
                patient_id="case_00001",
                series_id="nifti:000_case_00001_0000",
                action="reclassify",
                target_phase="CMP",
            )
        ],
    )
    assert response.summary.applied == 1
    assert response.results[0].metadata_updated is True
    assert response.results[0].message == "phase.json updated"
    assert readonly_before == _fingerprints(readonly_before.keys())
    phase_rows = _read_phase_json(dataset / "phase.json")
    assert phase_rows[0]["phase"] == "CMP"
    assert phase_rows[0]["updated_by"] == "webui"

    reset_database_index()
    reset_discovery_index()
    inventory = list_case_inventory(dataset, "case_00001")
    assert [row.canonical_phase for row in inventory] == ["CMP", "CMP"]
    assert inventory[0].raw_phase == "CMP"

    response = apply_review_operations(
        "DatasetMeta",
        [
            ReviewOperation(
                patient_id="case_00001",
                series_id="nifti:001_case_00001_0000",
                action="delete",
            )
        ],
    )
    assert response.summary.applied == 1
    assert response.results[0].metadata_updated is False
    assert not (dataset / "nifti" / "001_case_00001_0000.nii.gz").exists()
    assert (dataset / "deleted" / "nifti" / "001_case_00001_0000.nii.gz").is_file()
    metadata_rows = _read_jsonl(dataset / "metadata.jsonl")
    assert metadata_rows[1]["curated_keep"] == ""
    assert metadata_rows[1]["relative_path"] == "nifti/001_case_00001_0000.nii.gz"
    deleted_inventory = list_case_inventory(dataset, "case_00001")
    assert deleted_inventory[1].deleted is True

    restore_response = apply_review_operations(
        "DatasetMeta",
        [
            ReviewOperation(
                patient_id="case_00001",
                series_id="nifti:001_case_00001_0000",
                action="restore",
            )
        ],
    )
    assert restore_response.summary.applied == 1
    assert restore_response.results[0].metadata_updated is False
    assert (dataset / "nifti" / "001_case_00001_0000.nii.gz").is_file()
    assert not (dataset / "deleted" / "nifti" / "001_case_00001_0000.nii.gz").exists()
    restored_metadata_rows = _read_jsonl(dataset / "metadata.jsonl")
    assert restored_metadata_rows[1]["curated_keep"] == ""
    assert restored_metadata_rows[1]["relative_path"] == "nifti/001_case_00001_0000.nii.gz"
    restored_inventory = list_case_inventory(dataset, "case_00001")
    assert restored_inventory[1].deleted is False


def test_metadata_sync_consolidates_changes_and_preserves_phase_json(tmp_path, monkeypatch):
    dataset = _make_converter_metadata_dataset(tmp_path)
    phase_json_before = (dataset / "phase.json").read_bytes()
    state_dir = tmp_path / "state"
    monkeypatch.setenv("ALLOW_DATA_MUTATIONS", "true")
    monkeypatch.setenv("WEBUI_STATE_DIR", str(state_dir))

    import app.services.metadata_sync as metadata_sync

    monkeypatch.setattr(metadata_sync, "validate_workspace_dataset_id", lambda dataset_id: dataset)
    monkeypatch.setattr(metadata_sync, "workspace_file", lambda filename, create=True: state_dir / filename)

    deleted_nifti = dataset / "deleted" / "nifti"
    deleted_seg = dataset / "deleted" / "seg"
    deleted_nifti.mkdir(parents=True)
    deleted_seg.mkdir(parents=True)
    (dataset / "nifti" / "001_case_00001_0000.nii.gz").rename(
        deleted_nifti / "001_case_00001_0000.nii.gz"
    )
    (dataset / "seg" / "001_case_00001.nii.gz").rename(
        deleted_seg / "001_case_00001.nii.gz"
    )

    preview = preview_metadata_sync("DatasetMeta")
    assert preview.summary.phase_changes == 2
    assert preview.summary.delete_changes == 1
    assert preview.summary.conflicts == 0

    response = apply_metadata_sync("DatasetMeta")
    assert response.metadata_updated is True
    rows = _read_jsonl(dataset / "metadata.jsonl")
    assert rows[0]["phase"] == "NP"
    assert rows[0]["curated_phase"] == "NP"
    assert rows[1]["phase"] == "CMP"
    assert rows[1]["curated_phase"] == "CMP"
    assert rows[1]["curated_keep"] == "no"
    assert rows[1]["relative_path"] == "deleted/nifti/001_case_00001_0000.nii.gz"
    assert rows[1]["webui_metadata_batch_id"] == response.batch_id
    assert (dataset / "phase.json").read_bytes() == phase_json_before
    assert (state_dir / "metadata_update_log.json").is_file()

    reset_database_index()
    reset_discovery_index()
    inventory = list_case_inventory(dataset, "case_00001")
    assert inventory[1].deleted is True

    (deleted_nifti / "001_case_00001_0000.nii.gz").rename(
        dataset / "nifti" / "001_case_00001_0000.nii.gz"
    )
    (deleted_seg / "001_case_00001.nii.gz").rename(dataset / "seg" / "001_case_00001.nii.gz")
    restore_preview = preview_metadata_sync("DatasetMeta")
    assert restore_preview.summary.restore_changes == 1
    restore_response = apply_metadata_sync("DatasetMeta")
    assert restore_response.summary.restore_changes == 1
    restored_rows = _read_jsonl(dataset / "metadata.jsonl")
    assert restored_rows[1]["curated_keep"] == ""
    assert restored_rows[1]["relative_path"] == "nifti/001_case_00001_0000.nii.gz"


def test_metadata_sync_blocks_conflicting_active_and_deleted_files(tmp_path, monkeypatch):
    dataset = _make_converter_metadata_dataset(tmp_path)
    state_dir = tmp_path / "state"
    monkeypatch.setenv("ALLOW_DATA_MUTATIONS", "true")
    monkeypatch.setenv("WEBUI_STATE_DIR", str(state_dir))

    import app.services.metadata_sync as metadata_sync

    monkeypatch.setattr(metadata_sync, "validate_workspace_dataset_id", lambda dataset_id: dataset)
    monkeypatch.setattr(metadata_sync, "workspace_file", lambda filename, create=True: state_dir / filename)

    deleted_nifti = dataset / "deleted" / "nifti"
    deleted_nifti.mkdir(parents=True)
    shutil.copy2(
        dataset / "nifti" / "000_case_00001_0000.nii.gz",
        deleted_nifti / "000_case_00001_0000.nii.gz",
    )
    before = _fingerprints([dataset / "metadata.jsonl"])

    preview = preview_metadata_sync("DatasetMeta")
    assert preview.summary.conflicts == 1
    try:
        apply_metadata_sync("DatasetMeta")
        raise AssertionError("metadata sync should fail with conflicts")
    except RuntimeError:
        pass
    assert before == _fingerprints(before.keys())


def test_voi_catalog_uses_scan_idx_phase_and_blocks_voi_reclassify(tmp_path, monkeypatch):
    dataset = _make_voi_catalog_dataset(tmp_path)
    state_dir = tmp_path / "state"
    monkeypatch.setenv("ALLOW_DATA_MUTATIONS", "true")
    monkeypatch.setenv("WEBUI_STATE_DIR", str(state_dir))

    import app.services.review_apply as review_apply

    monkeypatch.setattr(review_apply, "validate_workspace_dataset_id", lambda dataset_id: dataset)
    monkeypatch.setattr(review_apply, "workspace_file", lambda filename, create=True: state_dir / filename)
    reset_database_index()
    reset_discovery_index()
    volume_cache.reset()

    series = discover_series(dataset, "case_00001")
    voi_series = [entry for entry in series if entry.type == "voi"]
    assert len(voi_series) == 2
    assert {entry.voi_id for entry in voi_series} == {"case_00001/000/L", "case_00001/000/R"}
    assert {entry.phase for entry in voi_series} == {"NP"}
    assert {entry.scan_idx for entry in voi_series} == {"000"}
    assert all("/NP/" not in (entry.storage_path or "") for entry in voi_series)

    inventory = list_case_inventory(dataset, "case_00001")
    voi_rows = [row for row in inventory if row.scope_availability["voi"]]
    assert len(voi_rows) == 2
    assert {row.canonical_phase for row in voi_rows} == {"NP"}
    assert {row.scan_idx for row in voi_rows} == {"000"}

    load_source = get_case_load_source(
        dataset,
        "case_00001",
        voi_rows[0].row_id,
        "voi",
        row_index=voi_rows[0].row_index,
    )
    volume = np.load(load_source.image_path)
    mask = np.load(load_source.mask_path)
    png_bytes = render_slice(volume, mask, axis="axial", index=1, ww=2, wl=1, layers=[1])
    with Image.open(BytesIO(png_bytes)) as image:
        pixels = np.asarray(image)
    assert pixels.max() > 0
    assert np.unique(pixels.reshape(-1, pixels.shape[-1]), axis=0).shape[0] > 1

    response = apply_review_operations(
        "DatasetVOI",
        [
            ReviewOperation(
                patient_id="case_00001",
                series_id="voi:case_00001/000/L",
                action="reclassify",
                target_phase="CMP",
            )
        ],
    )
    assert response.summary.failed == 1
    assert response.results[0].metadata_updated is False
    assert "inherited from phase.json" in response.results[0].message
    assert (dataset / "voi" / "images" / "G" / "case_00001" / "scan_L.npy").is_file()
    assert not (dataset / "voi" / "images" / "G" / "case_00001" / "CMP").exists()

    delete_response = apply_review_operations(
        "DatasetVOI",
        [
            ReviewOperation(
                patient_id="case_00001",
                series_id="nifti:000_case_00001_0000",
                action="delete",
            )
        ],
    )
    assert delete_response.summary.applied == 1
    moved_destinations = {entry.destination for entry in delete_response.results[0].moved_files}
    assert "deleted/nifti/000_case_00001_0000.nii.gz" in moved_destinations
    assert "deleted/seg/000_case_00001.nii.gz" in moved_destinations
    assert "voi/deleted/images/G/case_00001/scan_L.npy" in moved_destinations
    assert "voi/deleted/mask/G/case_00001/scan_L.npy" in moved_destinations
    assert "voi/deleted/images/G/case_00001/scan_R.npy" in moved_destinations
    assert "voi/deleted/mask/G/case_00001/scan_R.npy" in moved_destinations
    assert "voi/deleted/images_nii/G/case_00001/scan_L.nii.gz" in moved_destinations
    assert "voi/deleted/masks_nii/G/case_00001/scan_L.nii.gz" in moved_destinations
    assert "voi/deleted/images_nii/G/case_00001/scan_R.nii.gz" in moved_destinations
    assert "voi/deleted/masks_nii/G/case_00001/scan_R.nii.gz" in moved_destinations
    assert not (dataset / "voi" / "images" / "G" / "case_00001" / "scan_L.npy").exists()
    assert (dataset / "voi" / "deleted" / "images" / "G" / "case_00001" / "scan_L.npy").is_file()

    reset_database_index()
    reset_discovery_index()
    deleted_inventory = list_case_inventory(dataset, "case_00001")
    assert any(row.deleted for row in deleted_inventory if row.series_id == "nifti:000_case_00001_0000")
    assert all(row.deleted for row in deleted_inventory if row.series_id and row.series_id.startswith("voi:case_00001/000/"))

    restore_response = apply_review_operations(
        "DatasetVOI",
        [
            ReviewOperation(
                patient_id="case_00001",
                series_id="nifti:000_case_00001_0000",
                action="restore",
            )
        ],
    )
    assert restore_response.summary.applied == 1
    restored_destinations = {entry.destination for entry in restore_response.results[0].moved_files}
    assert "nifti/000_case_00001_0000.nii.gz" in restored_destinations
    assert "seg/000_case_00001.nii.gz" in restored_destinations
    assert "voi/images/G/case_00001/scan_L.npy" in restored_destinations
    assert "voi/mask/G/case_00001/scan_L.npy" in restored_destinations
    assert "voi/images_nii/G/case_00001/scan_L.nii.gz" in restored_destinations
    assert "voi/masks_nii/G/case_00001/scan_L.nii.gz" in restored_destinations
    assert (dataset / "voi" / "images" / "G" / "case_00001" / "scan_L.npy").is_file()
    assert not (dataset / "voi" / "deleted" / "images" / "G" / "case_00001" / "scan_L.npy").exists()

    voi_delete = apply_review_operations(
        "DatasetVOI",
        [
            ReviewOperation(
                patient_id="case_00001",
                series_id="voi:case_00001/000/L",
                action="delete",
            )
        ],
    )
    assert voi_delete.summary.applied == 1
    assert {entry.destination for entry in voi_delete.results[0].moved_files} == {
        "voi/deleted/images/G/case_00001/scan_L.npy",
        "voi/deleted/mask/G/case_00001/scan_L.npy",
        "voi/deleted/images_nii/G/case_00001/scan_L.nii.gz",
        "voi/deleted/masks_nii/G/case_00001/scan_L.nii.gz",
    }
    assert (dataset / "voi" / "images" / "G" / "case_00001" / "scan_R.npy").is_file()
    assert (dataset / "voi" / "images_nii" / "G" / "case_00001" / "scan_R.nii.gz").is_file()

    voi_restore = apply_review_operations(
        "DatasetVOI",
        [
            ReviewOperation(
                patient_id="case_00001",
                series_id="voi:case_00001/000/L",
                action="restore",
            )
        ],
    )
    assert voi_restore.summary.applied == 1
    assert len(voi_restore.results[0].moved_files) == 4

    undo_target = apply_review_operations(
        "DatasetVOI",
        [
            ReviewOperation(
                patient_id="case_00001",
                series_id="voi:case_00001/000/R",
                action="delete",
            )
        ],
    )
    assert undo_target.summary.applied == 1
    decision = next(
        item
        for item in list_recent_delete_decisions("DatasetVOI")
        if item.series_id == "voi:case_00001/000/R"
    )
    undo_response = undo_delete_decision("DatasetVOI", decision.decision_id)
    assert undo_response.summary.applied == 1
    assert len(undo_response.results[0].moved_files) == 4
    assert (dataset / "voi" / "images_nii" / "G" / "case_00001" / "scan_R.nii.gz").is_file()

    phase_payload = json.loads((dataset / "phase.json").read_text(encoding="utf-8"))
    phase_payload["phases"][0]["phase"] = "CMP"
    (dataset / "phase.json").write_text(json.dumps(phase_payload), encoding="utf-8")
    reset_database_index()
    reset_discovery_index()

    updated_series = [entry for entry in discover_series(dataset, "case_00001") if entry.type == "voi"]
    assert {entry.phase for entry in updated_series} == {"CMP"}
    updated_inventory = [row for row in list_case_inventory(dataset, "case_00001") if row.scope_availability["voi"]]
    assert {row.canonical_phase for row in updated_inventory} == {"CMP"}


def test_metadata_sync_updates_voi_catalog_delete_and_restore(tmp_path, monkeypatch):
    dataset = _make_voi_catalog_dataset(tmp_path)
    state_dir = tmp_path / "state"
    monkeypatch.setenv("ALLOW_DATA_MUTATIONS", "true")
    monkeypatch.setenv("WEBUI_STATE_DIR", str(state_dir))

    import app.services.metadata_sync as metadata_sync

    monkeypatch.setattr(metadata_sync, "validate_workspace_dataset_id", lambda dataset_id: dataset)
    monkeypatch.setattr(metadata_sync, "workspace_file", lambda filename, create=True: state_dir / filename)

    active_image = dataset / "voi" / "images" / "G" / "case_00001" / "scan_L.npy"
    active_mask = dataset / "voi" / "mask" / "G" / "case_00001" / "scan_L.npy"
    active_nii_image = dataset / "voi" / "images_nii" / "G" / "case_00001" / "scan_L.nii.gz"
    active_nii_mask = dataset / "voi" / "masks_nii" / "G" / "case_00001" / "scan_L.nii.gz"
    deleted_image = dataset / "voi" / "deleted" / "images" / "G" / "case_00001" / "scan_L.npy"
    deleted_mask = dataset / "voi" / "deleted" / "mask" / "G" / "case_00001" / "scan_L.npy"
    deleted_nii_image = dataset / "voi" / "deleted" / "images_nii" / "G" / "case_00001" / "scan_L.nii.gz"
    deleted_nii_mask = dataset / "voi" / "deleted" / "masks_nii" / "G" / "case_00001" / "scan_L.nii.gz"
    for source, destination in (
        (active_image, deleted_image),
        (active_mask, deleted_mask),
        (active_nii_image, deleted_nii_image),
        (active_nii_mask, deleted_nii_mask),
    ):
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)

    preview = preview_metadata_sync("DatasetVOI")
    assert preview.summary.voi_catalog_changes == 1
    assert preview.summary.delete_changes == 1
    response = apply_metadata_sync("DatasetVOI")
    assert response.metadata_updated is True
    catalog_rows = _read_jsonl(dataset / "voi" / "voi_catalog.jsonl")
    left_row = next(row for row in catalog_rows if row["side"] == "L")
    assert left_row["voi_image_path"] == "voi/deleted/images/G/case_00001/scan_L.npy"
    assert left_row["voi_mask_path"] == "voi/deleted/mask/G/case_00001/scan_L.npy"
    assert left_row["voi_image_nii_path"] == "voi/deleted/images_nii/G/case_00001/scan_L.nii.gz"
    assert left_row["voi_mask_nii_path"] == "voi/deleted/masks_nii/G/case_00001/scan_L.nii.gz"
    numpy_rows = _read_jsonl(dataset / "voi" / "voi_catalog_npy.jsonl")
    numpy_left_row = next(row for row in numpy_rows if row["voi_id"] == left_row["voi_id"])
    assert numpy_left_row == {
        "voi_id": left_row["voi_id"],
        "image_path": left_row["voi_image_path"],
        "mask_path": left_row["voi_mask_path"],
    }

    reset_database_index()
    reset_discovery_index()
    inventory = list_case_inventory(dataset, "case_00001")
    assert any(row.deleted for row in inventory if row.series_id == "voi:case_00001/000/L")
    assert any(row.scope_availability["voi"] for row in inventory)
    series = [entry for entry in discover_series(dataset, "case_00001") if entry.type == "voi"]
    assert next(entry for entry in series if entry.voi_id == "case_00001/000/L").deleted is True

    for source, destination in (
        (deleted_image, active_image),
        (deleted_mask, active_mask),
        (deleted_nii_image, active_nii_image),
        (deleted_nii_mask, active_nii_mask),
    ):
        source.rename(destination)
    reset_database_index()
    reset_discovery_index()
    restored_before_sync = [
        entry for entry in discover_series(dataset, "case_00001") if entry.type == "voi"
    ]
    assert next(
        entry for entry in restored_before_sync if entry.voi_id == "case_00001/000/L"
    ).deleted is False
    restore_preview = preview_metadata_sync("DatasetVOI")
    assert restore_preview.summary.restore_changes == 1
    apply_metadata_sync("DatasetVOI")
    restored_catalog_rows = _read_jsonl(dataset / "voi" / "voi_catalog.jsonl")
    restored_left_row = next(row for row in restored_catalog_rows if row["side"] == "L")
    assert restored_left_row["voi_image_path"] == "voi/images/G/case_00001/scan_L.npy"
    assert restored_left_row["voi_mask_path"] == "voi/mask/G/case_00001/scan_L.npy"
    assert restored_left_row["voi_image_nii_path"] == "voi/images_nii/G/case_00001/scan_L.nii.gz"
    assert restored_left_row["voi_mask_nii_path"] == "voi/masks_nii/G/case_00001/scan_L.nii.gz"
    restored_numpy_rows = _read_jsonl(dataset / "voi" / "voi_catalog_npy.jsonl")
    restored_numpy_left = next(
        row for row in restored_numpy_rows if row["voi_id"] == restored_left_row["voi_id"]
    )
    assert restored_numpy_left["image_path"] == restored_left_row["voi_image_path"]
    assert restored_numpy_left["mask_path"] == restored_left_row["voi_mask_path"]


def test_metadata_sync_rejects_split_numpy_nifti_state(tmp_path, monkeypatch):
    dataset = _make_voi_catalog_dataset(tmp_path)
    state_dir = tmp_path / "state"
    monkeypatch.setenv("ALLOW_DATA_MUTATIONS", "true")
    monkeypatch.setenv("WEBUI_STATE_DIR", str(state_dir))

    import app.services.metadata_sync as metadata_sync

    monkeypatch.setattr(metadata_sync, "validate_workspace_dataset_id", lambda dataset_id: dataset)
    monkeypatch.setattr(metadata_sync, "workspace_file", lambda filename, create=True: state_dir / filename)

    active_image = dataset / "voi" / "images" / "G" / "case_00001" / "scan_L.npy"
    active_mask = dataset / "voi" / "mask" / "G" / "case_00001" / "scan_L.npy"
    deleted_image = dataset / "voi" / "deleted" / "images" / "G" / "case_00001" / "scan_L.npy"
    deleted_mask = dataset / "voi" / "deleted" / "mask" / "G" / "case_00001" / "scan_L.npy"
    deleted_image.parent.mkdir(parents=True)
    deleted_mask.parent.mkdir(parents=True)
    active_image.rename(deleted_image)
    active_mask.rename(deleted_mask)

    preview = preview_metadata_sync("DatasetVOI")
    assert preview.summary.conflicts == 1
    assert any("split between active and deleted" in change.message for change in preview.changes)
    try:
        apply_metadata_sync("DatasetVOI")
        raise AssertionError("metadata sync should reject mixed NumPy/NIfTI file states")
    except RuntimeError:
        pass


def test_legacy_numpy_only_voi_catalog_delete_restore(tmp_path, monkeypatch):
    dataset = _make_voi_catalog_dataset(tmp_path)
    state_dir = tmp_path / "state"
    monkeypatch.setenv("ALLOW_DATA_MUTATIONS", "true")
    monkeypatch.setenv("WEBUI_STATE_DIR", str(state_dir))

    catalog_path = dataset / "voi" / "voi_catalog.jsonl"
    legacy_rows = _read_jsonl(catalog_path)
    for row in legacy_rows:
        row.pop("voi_image_nii_path")
        row.pop("voi_mask_nii_path")
    catalog_path.write_text(
        "".join(json.dumps(row) + "\n" for row in legacy_rows),
        encoding="utf-8",
    )
    shutil.rmtree(dataset / "voi" / "images_nii")
    shutil.rmtree(dataset / "voi" / "masks_nii")
    (dataset / "voi" / "voi_catalog_npy.jsonl").unlink()

    import app.services.review_apply as review_apply

    monkeypatch.setattr(review_apply, "validate_workspace_dataset_id", lambda dataset_id: dataset)
    monkeypatch.setattr(review_apply, "workspace_file", lambda filename, create=True: state_dir / filename)
    reset_database_index()
    reset_discovery_index()

    delete_response = apply_review_operations(
        "DatasetVOI",
        [
            ReviewOperation(
                patient_id="case_00001",
                series_id="nifti:000_case_00001_0000",
                action="delete",
            )
        ],
    )
    assert delete_response.summary.applied == 1
    assert all("_nii" not in entry.destination for entry in delete_response.results[0].moved_files)

    restore_response = apply_review_operations(
        "DatasetVOI",
        [
            ReviewOperation(
                patient_id="case_00001",
                series_id="nifti:000_case_00001_0000",
                action="restore",
            )
        ],
    )
    assert restore_response.summary.applied == 1
    assert (dataset / "voi" / "images" / "G" / "case_00001" / "scan_L.npy").is_file()


def _make_dataset(tmp_path: Path) -> Path:
    dataset = tmp_path / "DatasetTest"
    (dataset / "nifti").mkdir(parents=True)
    (dataset / "seg").mkdir()
    (dataset / "voi" / "images" / "G" / "case_00001").mkdir(parents=True)
    (dataset / "voi" / "mask" / "G" / "case_00001").mkdir(parents=True)

    _write_nifti(dataset / "nifti" / "scan_0000.nii.gz", np.arange(64, dtype=np.float32).reshape(4, 4, 4))
    mask = np.zeros((4, 4, 4), dtype=np.uint8)
    mask[1, 1, 1] = 1
    mask[2, 2, 2] = 2
    _write_nifti(dataset / "seg" / "scan.nii.gz", mask)
    np.save(dataset / "voi" / "images" / "G" / "case_00001" / "scan_L.npy", np.ones((2, 2, 2), dtype=np.float32))
    np.save(dataset / "voi" / "mask" / "G" / "case_00001" / "scan_L.npy", np.ones((2, 2, 2), dtype=np.uint8))
    _write_nifti(dataset / "voi" / "images" / "G" / "case_00001" / "scan_R.nii.gz", np.ones((2, 2, 2), dtype=np.float32))
    _write_nifti(dataset / "voi" / "mask" / "G" / "case_00001" / "scan_R.nii.gz", np.ones((2, 2, 2), dtype=np.uint8))

    rows = [
        {
            "row_id": "dup-row",
            "dataset_id": "DatasetTest",
            "case_id": "case_00001",
            "patient_id": "patient-a",
            "group": "G",
            "scan_idx": "0",
            "filename": "scan_0000.nii.gz",
            "phase": "ven",
            "side": "L",
            "nifti_path": "missing_root_relative.nii.gz",
            "nifti_original_volume_path": "nifti/scan_0000.nii.gz",
            "seg_path": "seg/scan.nii.gz",
            "voi_image_path": "voi/images/G/case_00001/scan_L.npy",
            "voi_mask_path": "voi/mask/G/case_00001/scan_L.npy",
            "has_seg": "true",
            "has_voi_image": "true",
            "has_voi_mask": "true",
        },
        {
            "row_id": "dup-row",
            "dataset_id": "DatasetTest",
            "case_id": "case_00001",
            "patient_id": "patient-a",
            "group": "G",
            "scan_idx": "0",
            "filename": "scan_0000.nii.gz",
            "phase": "ven",
            "side": "L",
            "nifti_path": "nifti/scan_0000.nii.gz",
            "nifti_original_volume_path": "",
            "seg_path": "seg/scan.nii.gz",
            "voi_image_path": "voi/images/G/case_00001/scan_L.npy",
            "voi_mask_path": "voi/mask/G/case_00001/scan_L.npy",
            "has_seg": "true",
            "has_voi_image": "true",
            "has_voi_mask": "true",
        },
        {
            "row_id": "voi-nifti",
            "dataset_id": "DatasetTest",
            "case_id": "case_00001",
            "patient_id": "patient-a",
            "group": "G",
            "scan_idx": "0",
            "filename": "scan_0000.nii.gz",
            "phase": "art",
            "side": "R",
            "nifti_path": "nifti/scan_0000.nii.gz",
            "nifti_original_volume_path": "",
            "seg_path": "seg/missing.nii.gz",
            "voi_image_path": "voi/images/G/case_00001/scan_R.nii.gz",
            "voi_mask_path": "voi/mask/G/case_00001/scan_R.nii.gz",
            "has_seg": "true",
            "has_voi_image": "true",
            "has_voi_mask": "true",
        },
        {
            "row_id": "missing-row",
            "dataset_id": "DatasetTest",
            "case_id": "case_00001",
            "patient_id": "patient-a",
            "group": "G",
            "scan_idx": "1",
            "filename": "scan_0000.nii.gz",
            "phase": "undefined",
            "side": "",
            "nifti_path": "nifti/scan_0000.nii.gz",
            "nifti_original_volume_path": "",
            "seg_path": "",
            "voi_image_path": "voi/images/G/case_00001/missing.npy",
            "voi_mask_path": "voi/mask/G/case_00001/missing.npy",
            "has_seg": "false",
            "has_voi_image": "true",
            "has_voi_mask": "true",
        },
    ]
    with (dataset / "database.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return dataset


def _make_voi_catalog_dataset(tmp_path: Path) -> Path:
    dataset = tmp_path / "DatasetVOI"
    (dataset / "nifti").mkdir(parents=True)
    (dataset / "seg").mkdir()
    (dataset / "voi" / "images" / "G" / "case_00001").mkdir(parents=True)
    (dataset / "voi" / "mask" / "G" / "case_00001").mkdir(parents=True)
    (dataset / "voi" / "images_nii" / "G" / "case_00001").mkdir(parents=True)
    (dataset / "voi" / "masks_nii" / "G" / "case_00001").mkdir(parents=True)

    _write_nifti(dataset / "nifti" / "000_case_00001_0000.nii.gz", np.ones((4, 4, 4), dtype=np.float32))
    _write_nifti(dataset / "seg" / "000_case_00001.nii.gz", np.ones((4, 4, 4), dtype=np.uint8))
    np.save(dataset / "voi" / "images" / "G" / "case_00001" / "scan_L.npy", np.ones((3, 3, 3), dtype=np.float32))
    np.save(dataset / "voi" / "mask" / "G" / "case_00001" / "scan_L.npy", np.ones((3, 3, 3), dtype=np.uint8))
    np.save(dataset / "voi" / "images" / "G" / "case_00001" / "scan_R.npy", np.ones((3, 3, 3), dtype=np.float32))
    np.save(dataset / "voi" / "mask" / "G" / "case_00001" / "scan_R.npy", np.ones((3, 3, 3), dtype=np.uint8))
    for side in ("L", "R"):
        _write_nifti(
            dataset / "voi" / "images_nii" / "G" / "case_00001" / f"scan_{side}.nii.gz",
            np.ones((3, 3, 3), dtype=np.float32),
        )
        _write_nifti(
            dataset / "voi" / "masks_nii" / "G" / "case_00001" / f"scan_{side}.nii.gz",
            np.ones((3, 3, 3), dtype=np.uint8),
        )

    metadata_row = {
        "case_id": "case_00001",
        "case_index": "1",
        "scan_idx": "000",
        "filename": "000_case_00001_0000.nii.gz",
        "relative_path": "nifti/000_case_00001_0000.nii.gz",
        "nifti_file": str((dataset / "nifti" / "000_case_00001_0000.nii.gz").resolve()),
        "patient_id": "ANONYM-A",
        "group": "G",
        "series_uid": "series-a",
        "phase_guess": "DELAY",
    }
    (dataset / "metadata.jsonl").write_text(json.dumps(metadata_row) + "\n", encoding="utf-8")
    (dataset / "phase.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "phases": [
                    {
                        "filename": "000_case_00001_0000.nii.gz",
                        "case_id": "case_00001",
                        "patient_id": "ANONYM-A",
                        "scan_idx": "000",
                        "phase": "NP",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    catalog_rows = [
        {
            "case_id": "case_00001",
            "scan_idx": "000",
            "voi_id": f"case_00001/000/{side}",
            "side": side,
            "group": "G",
            "phase": "NC",
            "phase_source": "phase.json",
            "filename": "000_case_00001_0000.nii.gz",
            "series_uid": "series-a",
            "patient_folder": "patient-folder",
            "patient_id": "ANONYM-A",
            "nifti_path": "nifti/000_case_00001_0000.nii.gz",
            "seg_path": "seg/000_case_00001.nii.gz",
            "voi_image_path": f"images/G/case_00001/scan_{side}.npy",
            "voi_mask_path": f"mask/G/case_00001/scan_{side}.npy",
            "voi_image_nii_path": f"images_nii/G/case_00001/scan_{side}.nii.gz",
            "voi_mask_nii_path": f"masks_nii/G/case_00001/scan_{side}.nii.gz",
            "crop_provenance": {},
            "resample_provenance": {},
            "tumor_metrics": {},
        }
        for side in ("L", "R")
    ]
    (dataset / "voi" / "voi_catalog.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in catalog_rows),
        encoding="utf-8",
    )
    numpy_catalog_rows = [
        {
            "voi_id": row["voi_id"],
            "image_path": row["voi_image_path"],
            "mask_path": row["voi_mask_path"],
        }
        for row in catalog_rows
    ]
    (dataset / "voi" / "voi_catalog_npy.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in numpy_catalog_rows),
        encoding="utf-8",
    )
    return dataset


def _write_nifti(path: Path, data: np.ndarray) -> None:
    nib.save(nib.Nifti1Image(data, affine=np.eye(4)), str(path))


def _fingerprints(paths) -> dict[Path, tuple[str, int]]:
    return {
        Path(path): (_sha256(Path(path)), Path(path).stat().st_mtime_ns)
        for path in paths
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _make_converter_metadata_dataset(tmp_path: Path) -> Path:
    dataset = tmp_path / "DatasetMeta"
    (dataset / "nifti").mkdir(parents=True)
    (dataset / "seg").mkdir()
    for stem in ("000_case_00001", "001_case_00001"):
        _write_nifti(dataset / "nifti" / f"{stem}_0000.nii.gz", np.ones((4, 4, 4), dtype=np.float32))
        _write_nifti(dataset / "seg" / f"{stem}.nii.gz", np.ones((4, 4, 4), dtype=np.uint8))

    rows = [
        {
            "case_id": "case_00001",
            "case_index": "1",
            "scan_idx": "000",
            "filename": "000_case_00001_0000.nii.gz",
            "relative_path": "nifti/000_case_00001_0000.nii.gz",
            "nifti_file": str((dataset / "nifti" / "000_case_00001_0000.nii.gz").resolve()),
            "patient_id": "ANONYM-A",
            "series_uid": "series-a",
            "modality": "CT",
            "scan_date": "2026-07-21",
            "phase_guess": "NP",
            "phase_guess_confidence": "medium",
            "phase_guess_evidence": "contrast delay 90s from acquisition_time",
            "curated_phase": "",
            "curated_keep": "",
            "curated_quality": "",
            "notes": "",
        },
        {
            "case_id": "case_00001",
            "case_index": "1",
            "scan_idx": "001",
            "filename": "001_case_00001_0000.nii.gz",
            "relative_path": "nifti/001_case_00001_0000.nii.gz",
            "nifti_file": str((dataset / "nifti" / "001_case_00001_0000.nii.gz").resolve()),
            "patient_id": "ANONYM-A",
            "series_uid": "series-b",
            "modality": "CT",
            "scan_date": "2026-07-21",
            "phase_guess": "CMP; unknown",
            "phase_guess_confidence": "low",
            "phase_guess_evidence": "contrast delay 55s from acquisition_time",
            "curated_phase": "",
            "curated_keep": "",
            "curated_quality": "",
            "notes": "",
        },
    ]
    (dataset / "metadata.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    (dataset / "phase.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "phases": [
                    {
                        "filename": "000_case_00001_0000.nii.gz",
                        "case_id": "case_00001",
                        "patient_id": "ANONYM-A",
                        "scan_idx": "000",
                        "phase": "NP",
                    },
                    {
                        "filename": "001_case_00001_0000.nii.gz",
                        "case_id": "case_00001",
                        "patient_id": "ANONYM-A",
                        "scan_idx": "001",
                        "phase": "CMP",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    with (dataset / "curation.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["case_id", "patient_id", "nifti_file", "phase_guess", "curated_phase", "curated_keep", "notes"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "case_id": row["case_id"],
                    "patient_id": row["patient_id"],
                    "nifti_file": row["nifti_file"],
                    "phase_guess": row["phase_guess"],
                    "curated_phase": "",
                    "curated_keep": "",
                    "notes": "",
                }
            )
    return dataset


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _read_phase_json(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload["phases"]
