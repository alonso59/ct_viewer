from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.converter_metadata import is_intentionally_skipped_metadata_row
from app.services.metadata_sync import apply_metadata_sync, preview_metadata_sync


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{json.dumps(row)}\n" for row in rows),
        encoding="utf-8",
    )


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _configure_sync(monkeypatch, dataset: Path, state_dir: Path) -> None:
    import app.services.metadata_sync as metadata_sync

    monkeypatch.setenv("ALLOW_DATA_MUTATIONS", "true")
    monkeypatch.setattr(metadata_sync, "validate_workspace_dataset_id", lambda _dataset_id: dataset)
    monkeypatch.setattr(
        metadata_sync,
        "workspace_file",
        lambda filename, create=True: state_dir / filename,
    )


@pytest.mark.parametrize("planned_conversion", [False, 0, "false", "FALSE", "no", "off"])
def test_intentionally_skipped_row_requires_explicit_false_value(planned_conversion):
    row = {
        "status": " SKIPPED ",
        "planned_conversion": planned_conversion,
        "filename": "",
        "relative_path": None,
        "nifti_file": "   ",
    }

    assert is_intentionally_skipped_metadata_row(row) is True


def test_phase_apply_ignores_and_does_not_stamp_intentionally_skipped_row(
    tmp_path,
    monkeypatch,
):
    dataset = tmp_path / "DatasetMeta"
    state_dir = tmp_path / "state"
    filename = "000_case_00001_0000.nii.gz"
    (dataset / "nifti").mkdir(parents=True)
    (dataset / "nifti" / filename).touch()
    converted_row = {
        "case_id": "case_00001",
        "scan_idx": "000",
        "filename": filename,
        "relative_path": f"nifti/{filename}",
        "phase": "EP",
        "status": "converted",
        "planned_conversion": True,
    }
    skipped_row = {
        "case_id": "case_00002",
        "status": "skipped",
        "planned_conversion": False,
        "skip_reason": "unsafe_geometry",
    }
    _write_jsonl(dataset / "metadata.jsonl", [converted_row, skipped_row])
    (dataset / "phase.json").write_text(
        json.dumps(
            {
                "phases": [
                    {
                        "case_id": "case_00001",
                        "scan_idx": "000",
                        "filename": filename,
                        "phase": "NP",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    _configure_sync(monkeypatch, dataset, state_dir)

    preview = preview_metadata_sync("DatasetMeta")

    assert preview.summary.total_rows == 2
    assert preview.summary.phase_changes == 1
    assert preview.summary.noop == 1
    assert preview.summary.conflicts == 0
    assert [change.kind for change in preview.changes] == ["phase_changes", "noop"]

    response = apply_metadata_sync("DatasetMeta")
    rows = _read_jsonl(dataset / "metadata.jsonl")

    assert response.metadata_updated is True
    assert rows[0]["phase"] == "NP"
    assert rows[0]["curated_phase"] == "NP"
    assert rows[1] == skipped_row
    assert not any(key.startswith("webui_") for key in rows[1])


def test_converted_row_without_output_reference_remains_a_conflict(tmp_path, monkeypatch):
    dataset = tmp_path / "DatasetMeta"
    _write_jsonl(
        dataset / "metadata.jsonl",
        [{"status": "converted", "planned_conversion": True}],
    )
    _configure_sync(monkeypatch, dataset, tmp_path / "state")

    preview = preview_metadata_sync("DatasetMeta")

    assert preview.summary.conflicts == 1
    assert preview.summary.noop == 0
    assert preview.changes[0].kind == "conflicts"
    assert "no filename" in preview.changes[0].message


@pytest.mark.parametrize("reference_field", ["filename", "relative_path", "nifti_file"])
def test_skipped_row_with_output_reference_uses_normal_conflict_checks(
    tmp_path,
    monkeypatch,
    reference_field,
):
    dataset = tmp_path / "DatasetMeta"
    row = {
        "status": "skipped",
        "planned_conversion": False,
        reference_field: "nifti/missing.nii.gz" if reference_field != "filename" else "missing.nii.gz",
    }
    _write_jsonl(dataset / "metadata.jsonl", [row])
    _configure_sync(monkeypatch, dataset, tmp_path / "state")

    preview = preview_metadata_sync("DatasetMeta")

    assert is_intentionally_skipped_metadata_row(row) is False
    assert preview.summary.conflicts == 1
    assert preview.summary.noop == 0
    assert preview.changes[0].kind == "conflicts"
    assert "Neither active nor deleted" in preview.changes[0].message


def test_legacy_rows_without_conversion_fields_keep_existing_behavior(tmp_path, monkeypatch):
    dataset = tmp_path / "DatasetMeta"
    filename = "000_case_00001_0000.nii.gz"
    (dataset / "nifti").mkdir(parents=True)
    (dataset / "nifti" / filename).touch()
    _write_jsonl(
        dataset / "metadata.jsonl",
        [
            {"filename": filename, "phase": "NP"},
            {"case_id": "case_legacy_missing"},
        ],
    )
    _configure_sync(monkeypatch, dataset, tmp_path / "state")

    preview = preview_metadata_sync("DatasetMeta")

    assert preview.summary.already_consolidated == 1
    assert preview.summary.conflicts == 1
    assert preview.summary.noop == 0
    assert [change.kind for change in preview.changes] == ["already_consolidated", "conflicts"]
