"""D04/D06: unusable object identity cannot silently change a converted volume."""

import hashlib
from pathlib import Path

import pydicom
import pytest
from plugins.dicom import convert, scan

from app.tasks.dicom_stage import probe_series
from app.tasks.source_inventory import SourceInventory
from tests.test_dicom_resume import run_conversion
from tools.dicom_fixtures import write_series


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("missing", "MISSING_SOP_INSTANCE_UID"),
        ("duplicate", "DUPLICATE_SOP_INSTANCE_UID"),
    ],
)
def test_invalid_instance_identity_is_diagnosed_without_hiding_valid_neighbor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str, code: str
) -> None:
    source = tmp_path / "source"
    write_series(source / "bad", shape=(3, 3, 3), marker=(1, 1, 2))
    write_series(source / "good", shape=(3, 3, 3), marker=(1, 1, 2), patient_id="GOOD")
    members = sorted((source / "bad").glob("*.dcm"))
    dataset = pydicom.dcmread(members[1])
    if mutation == "missing":
        del dataset.SOPInstanceUID
    else:
        dataset.SOPInstanceUID = pydicom.dcmread(members[0]).SOPInstanceUID
    dataset.save_as(members[1], enforce_file_format=True)
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob("*.dcm")}
    with SourceInventory(tmp_path / "state/inventory.sqlite", source) as inventory:
        assert inventory.scan()["complete"]
        series = inventory.discover(source)
        diagnostics: list[scan.Diagnostic] = []
        bad = next(s for s in series if s.dicom_dir.name == "bad")
        inspected = scan.inspect(bad, scan.first_header(bad), diagnostics)
        assert code in inspected.identity_codes
        assert any(d.code == code and d.stage == "dicom_identity" for d in diagnostics)
    rows = probe_series(str(source), [p.relative_to(source).as_posix() for p in before])
    assert len(rows) == 2
    assert code in next(row["error"] for row in rows if row.get("error"))
    assert next(row["geometry"]["shape"] for row in rows if not row.get("error")) == [3, 3, 3]
    original = convert.read_image
    read: list[str] = []

    def checked(series: scan.Series):
        read.append(series.dicom_dir.name)
        assert series.dicom_dir.name == "good"
        return original(series)

    monkeypatch.setattr(convert, "read_image", checked)
    result = run_conversion(source, tmp_path / "output")
    assert result.counts["converted"] == 1 and result.counts["skipped"] == 1
    assert read == ["good"]
    with pytest.raises(ValueError, match="usable instance identities"):
        run_conversion(source / "bad", tmp_path / "rejected")
    assert not (tmp_path / "rejected" / "nifti").exists()
    assert any(code in row["reason"] and row["action"] == "skip" for row in result.plan)
    assert before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before}


def test_missing_series_uid_quarantines_the_folder_and_reuses_rejected_facts(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    write_series(source / "bad", shape=(3, 3, 3), marker=(1, 1, 2))
    write_series(source / "good", shape=(3, 3, 3), marker=(1, 1, 2), patient_id="GOOD")
    path = sorted((source / "bad").glob("*.dcm"))[1]
    dataset = pydicom.dcmread(path)
    uid = dataset.SeriesInstanceUID
    del dataset.SeriesInstanceUID
    dataset.save_as(path, enforce_file_format=True)
    with SourceInventory(tmp_path / "state/inventory.sqlite", source) as inventory:
        summary = inventory.scan()
        assert summary["complete"] and summary["rejected"] == 3 and summary["dicom"] == 3
        assert summary["rejections"] == {
            "MISSING_SERIES_INSTANCE_UID": 1,
            "AMBIGUOUS_SERIES_MEMBERSHIP": 2,
        }
        assert inventory.scan()["generation"] == summary["generation"]
        assert [s.dicom_dir.name for s in inventory.discover(source)] == ["good"]
        diagnostics: list[scan.Diagnostic] = []
        assert [s.dicom_dir.name for s in scan.discover(source, diagnostics)] == ["good"]
        assert any(d.code == "MISSING_SERIES_INSTANCE_UID" for d in diagnostics)
        dataset.SeriesInstanceUID = uid
        dataset.save_as(path, enforce_file_format=True)
        repaired = inventory.scan()
        assert repaired["complete"] and repaired["rejected"] == 0 and repaired["dicom"] == 6
        assert repaired["generation"] != summary["generation"]
