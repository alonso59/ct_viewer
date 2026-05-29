from __future__ import annotations

import csv
import hashlib
from pathlib import Path
import time

import nibabel as nib
import numpy as np
import pytest

from app.models.curation import CurationDecisionRequest
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
from app.services.qc_validator import validate_database
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
    assert inventory[0].nifti_path.status == "exists"
    assert inventory[0].seg_path.status == "exists"
    assert inventory[0].voi_image_path.status == "exists"
    assert inventory[0].scope_availability["complete"] is True
    assert inventory[0].scope_availability["voi"] is True

    full_source = get_case_load_source(dataset, "case_00001", "dup-row", "complete")
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
    assert full_info.spacing == pytest.approx([0.7, 0.8, 5.0])
    assert full_info.labels == [1, 2]

    voi_numpy_source = get_case_load_source(dataset, "case_00001", "dup-row", "voi")
    voi_numpy_info = volume_cache.load_case_source(
        dataset_id="DatasetTest",
        case_id="case_00001",
        series_id=voi_numpy_source.series_id,
        image_path=voi_numpy_source.image_path,
        mask_path=voi_numpy_source.mask_path,
        source_type=voi_numpy_source.source_type,
        cache_key_suffix="voi-numpy",
        spacing_override=voi_numpy_source.spacing,
    )
    assert voi_numpy_info.shape == [2, 2, 2]
    assert voi_numpy_info.spacing == [1.0, 1.0, 1.0]
    _volume, _mask, voi_numpy_mesh_spacing = volume_cache.get_by_handle(voi_numpy_info.load_handle)
    assert voi_numpy_mesh_spacing == (1.0, 1.0, 1.0)

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
    assert voi_info.spacing == [1.0, 1.0, 1.0]
    _volume, _mask, voi_nifti_mesh_spacing = volume_cache.get_by_handle(voi_info.load_handle)
    assert voi_nifti_mesh_spacing == (1.0, 1.0, 1.0)

    before = _fingerprints(
        [
            dataset / "database.csv",
            dataset / "manifest.csv",
            dataset / "nifti" / "scan_0000.nii.gz",
            dataset / "seg" / "scan.nii.gz",
            dataset / "voi" / "images" / "G" / "case_00001" / "NP" / "scan_L.npy",
            dataset / "voi" / "mask" / "G" / "case_00001" / "NP" / "scan_L.npy",
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


def _make_dataset(tmp_path: Path) -> Path:
    dataset = tmp_path / "DatasetTest"
    (dataset / "nifti").mkdir(parents=True)
    (dataset / "seg").mkdir()
    (dataset / "voi" / "images" / "G" / "case_00001" / "NP").mkdir(parents=True)
    (dataset / "voi" / "mask" / "G" / "case_00001" / "NP").mkdir(parents=True)
    (dataset / "voi" / "images" / "G" / "case_00001" / "CMP").mkdir(parents=True)
    (dataset / "voi" / "mask" / "G" / "case_00001" / "CMP").mkdir(parents=True)

    _write_nifti(
        dataset / "nifti" / "scan_0000.nii.gz",
        np.arange(64, dtype=np.float32).reshape(4, 4, 4),
        spacing=(0.7, 0.8, 5.0),
    )
    mask = np.zeros((4, 4, 4), dtype=np.uint8)
    mask[1, 1, 1] = 1
    mask[2, 2, 2] = 2
    _write_nifti(dataset / "seg" / "scan.nii.gz", mask)
    np.save(dataset / "voi" / "images" / "G" / "case_00001" / "NP" / "scan_L.npy", np.ones((2, 2, 2), dtype=np.float32))
    np.save(dataset / "voi" / "mask" / "G" / "case_00001" / "NP" / "scan_L.npy", np.ones((2, 2, 2), dtype=np.uint8))
    _write_nifti(
        dataset / "voi" / "images" / "G" / "case_00001" / "CMP" / "scan_R.nii.gz",
        np.ones((2, 2, 2), dtype=np.float32),
        spacing=(0.8, 0.9, 4.0),
    )
    _write_nifti(dataset / "voi" / "mask" / "G" / "case_00001" / "CMP" / "scan_R.nii.gz", np.ones((2, 2, 2), dtype=np.uint8))
    (dataset / "manifest.csv").write_text("filename,phase\nscan_0000.nii.gz,ven\n", encoding="utf-8")

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
            "voi_image_path": "voi/images/G/case_00001/NP/scan_L.npy",
            "voi_mask_path": "voi/mask/G/case_00001/NP/scan_L.npy",
            "has_seg": "true",
            "has_voi_image": "true",
            "has_voi_mask": "true",
            "spacing_x": "0.8",
            "spacing_y": "0.9",
            "spacing_z": "4.0",
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
            "voi_image_path": "voi/images/G/case_00001/NP/scan_L.npy",
            "voi_mask_path": "voi/mask/G/case_00001/NP/scan_L.npy",
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
            "voi_image_path": "voi/images/G/case_00001/CMP/scan_R.nii.gz",
            "voi_mask_path": "voi/mask/G/case_00001/CMP/scan_R.nii.gz",
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
            "voi_image_path": "voi/images/G/case_00001/NP/missing.npy",
            "voi_mask_path": "voi/mask/G/case_00001/NP/missing.npy",
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


def _write_nifti(
    path: Path,
    data: np.ndarray,
    spacing: tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> None:
    affine = np.diag([spacing[0], spacing[1], spacing[2], 1.0])
    nib.save(nib.Nifti1Image(data, affine=affine), str(path))


def _fingerprints(paths) -> dict[Path, tuple[str, int]]:
    return {
        Path(path): (_sha256(Path(path)), Path(path).stat().st_mtime_ns)
        for path in paths
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()
