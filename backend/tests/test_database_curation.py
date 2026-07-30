from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import time

import nibabel as nib
import numpy as np

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
from app.services.discovery import reset_discovery_index
from app.services.qc_validator import validate_database
from app.services.review_apply import apply_review_operations
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
    assert inventory[1].raw_phase == "CMP; unknown"
    assert inventory[1].phase_status == "ambiguous"
    assert inventory[0].scope_availability["complete"] is True

    readonly_before = _fingerprints(
        [
            dataset / "metadata.jsonl",
            dataset / "manifest.csv",
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
    assert response.results[0].manifest_updated is False
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
    assert response.results[0].metadata_updated is True
    assert not (dataset / "nifti" / "001_case_00001_0000.nii.gz").exists()
    assert (dataset / "deleted" / "nifti" / "001_case_00001_0000.nii.gz").is_file()
    metadata_rows = _read_jsonl(dataset / "metadata.jsonl")
    assert metadata_rows[1]["curated_keep"] == "no"
    assert metadata_rows[1]["relative_path"] == "deleted/nifti/001_case_00001_0000.nii.gz"
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
    assert restore_response.results[0].metadata_updated is True
    assert (dataset / "nifti" / "001_case_00001_0000.nii.gz").is_file()
    assert not (dataset / "deleted" / "nifti" / "001_case_00001_0000.nii.gz").exists()
    restored_metadata_rows = _read_jsonl(dataset / "metadata.jsonl")
    assert restored_metadata_rows[1]["curated_keep"] == ""
    assert restored_metadata_rows[1]["relative_path"] == "nifti/001_case_00001_0000.nii.gz"
    restored_inventory = list_case_inventory(dataset, "case_00001")
    assert restored_inventory[1].deleted is False


def _make_dataset(tmp_path: Path) -> Path:
    dataset = tmp_path / "DatasetTest"
    (dataset / "nifti").mkdir(parents=True)
    (dataset / "seg").mkdir()
    (dataset / "voi" / "images" / "G" / "case_00001" / "NP").mkdir(parents=True)
    (dataset / "voi" / "mask" / "G" / "case_00001" / "NP").mkdir(parents=True)
    (dataset / "voi" / "images" / "G" / "case_00001" / "CMP").mkdir(parents=True)
    (dataset / "voi" / "mask" / "G" / "case_00001" / "CMP").mkdir(parents=True)

    _write_nifti(dataset / "nifti" / "scan_0000.nii.gz", np.arange(64, dtype=np.float32).reshape(4, 4, 4))
    mask = np.zeros((4, 4, 4), dtype=np.uint8)
    mask[1, 1, 1] = 1
    mask[2, 2, 2] = 2
    _write_nifti(dataset / "seg" / "scan.nii.gz", mask)
    np.save(dataset / "voi" / "images" / "G" / "case_00001" / "NP" / "scan_L.npy", np.ones((2, 2, 2), dtype=np.float32))
    np.save(dataset / "voi" / "mask" / "G" / "case_00001" / "NP" / "scan_L.npy", np.ones((2, 2, 2), dtype=np.uint8))
    _write_nifti(dataset / "voi" / "images" / "G" / "case_00001" / "CMP" / "scan_R.nii.gz", np.ones((2, 2, 2), dtype=np.float32))
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
    (dataset / "manifest.csv").write_text(
        "filename,patient_id,case_id,group,phase,scan_idx\n"
        "000_case_00001_0000.nii.gz,ANONYM-A,case_00001,NG,undefined,000\n"
        "001_case_00001_0000.nii.gz,ANONYM-A,case_00001,NG,undefined,001\n",
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
