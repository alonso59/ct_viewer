from __future__ import annotations

import json

import pytest

from app.services.database import (
    get_case_load_source,
    get_database_index,
    list_case_inventory,
    list_case_summaries,
    reset_database_index,
)


def test_intentionally_skipped_row_is_a_non_loadable_inventory_record(tmp_path):
    dataset = tmp_path / "DatasetSkipped"
    dataset.mkdir()
    _write_metadata(
        dataset,
        [
            {
                "case_id": "case_skipped",
                "patient_id": "patient-skipped",
                "series_uid": "series-skipped",
                "phase": "EP",
                "status": "skipped",
                "skip_reason": "unsafe_geometry",
                "planned_conversion": False,
            }
        ],
    )
    reset_database_index()

    summary = list_case_summaries(dataset)[0]
    assert summary.case_id == "case_skipped"
    assert summary.scan_count == 0
    assert summary.skipped_count == 1
    assert summary.available_phases == []
    assert summary.warning_count == 0

    inventory = list_case_inventory(dataset, "case_skipped")
    assert len(inventory) == 1
    assert inventory[0].row_id == "metadata:series-skipped"
    assert inventory[0].series_id is None
    assert inventory[0].scope_availability == {"complete": False, "voi": False}
    assert inventory[0].nifti_path.status == "not_provided"
    assert inventory[0].seg_path.status == "not_provided"
    assert inventory[0].qc_warnings == []

    indexed_row = get_database_index(dataset).rows[0]
    assert indexed_row.raw["status"] == "skipped"
    assert indexed_row.raw["skip_reason"] == "unsafe_geometry"
    assert indexed_row.raw["planned_conversion"] == "False"
    assert indexed_row.raw["filename"] == ""

    with pytest.raises(FileNotFoundError, match="Complete scan is not available"):
        get_case_load_source(dataset, "case_skipped", inventory[0].row_id, "complete")


def test_only_real_scopes_contribute_available_phases(tmp_path):
    dataset = tmp_path / "DatasetMixed"
    (dataset / "nifti").mkdir(parents=True)
    converted_filename = "000_case_mixed_0000.nii.gz"
    (dataset / "nifti" / converted_filename).write_bytes(b"nifti-placeholder")
    _write_metadata(
        dataset,
        [
            {
                "case_id": "case_mixed",
                "scan_idx": "000",
                "phase": "NP",
                "status": "converted",
                "planned_conversion": True,
                "filename": converted_filename,
                "relative_path": f"nifti/{converted_filename}",
            },
            {
                "case_id": "case_mixed",
                "series_uid": "series-skipped",
                "phase": "CMP",
                "status": "skipped",
                "skip_reason": "unsafe_geometry",
                "planned_conversion": "false",
            },
        ],
    )
    reset_database_index()

    summary = list_case_summaries(dataset)[0]
    assert summary.available_phases == ["NP"]
    assert summary.scan_count == 1
    assert summary.skipped_count == 1
    assert len(list_case_inventory(dataset, "case_mixed")) == 2


def test_skipped_row_with_output_reference_is_not_treated_as_discarded(tmp_path):
    dataset = tmp_path / "DatasetInconsistent"
    dataset.mkdir()
    _write_metadata(
        dataset,
        [
            {
                "case_id": "case_inconsistent",
                "phase": "CMP",
                "status": "skipped",
                "skip_reason": "unsafe_geometry",
                "planned_conversion": False,
                "filename": "referenced_but_missing.nii.gz",
            }
        ],
    )
    reset_database_index()

    summary = list_case_summaries(dataset)[0]
    inventory = list_case_inventory(dataset, "case_inconsistent")[0]
    assert summary.skipped_count == 0
    assert summary.available_phases == []
    assert inventory.series_id == "nifti:referenced_but_missing"
    assert inventory.nifti_path.status == "missing"
    assert {warning.code for warning in inventory.qc_warnings} >= {
        "missing_path",
        "missing_seg",
    }


def test_legacy_row_without_conversion_fields_keeps_missing_output_behavior(tmp_path):
    dataset = tmp_path / "DatasetLegacy"
    dataset.mkdir()
    _write_metadata(dataset, [{"case_id": "case_legacy", "phase": "NP"}])
    reset_database_index()

    summary = list_case_summaries(dataset)[0]
    inventory = list_case_inventory(dataset, "case_legacy")[0]
    assert summary.skipped_count == 0
    assert inventory.row_id == "metadata:metadata_row_000000.nii.gz"
    assert inventory.series_id == "nifti:metadata_row_000000"
    assert inventory.nifti_path.status == "missing"
    assert any(warning.code == "missing_path" for warning in inventory.qc_warnings)


def _write_metadata(dataset, rows) -> None:
    (dataset / "metadata.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
