"""D11/D28 / DCM-02/07/17: pinned series membership and no-clobber image publication."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from plugins.dicom import convert, scan

from tools.dicom_fixtures import write_series


def test_reader_does_not_add_files_appearing_after_the_plan(tmp_path: Path) -> None:
    root = tmp_path / "source"
    write_series(root, shape=(3, 3, 3), marker=(1, 1, 2), seed="pinned")
    planned = scan.discover(root, [])[0]
    extra = tmp_path / "new_acquisition"
    write_series(extra, shape=(3, 3, 4), marker=(1, 1, 2), seed="pinned")
    (root / "IM0003.dcm").write_bytes((extra / "IM0003.dcm").read_bytes())
    assert len(planned.files) == 3
    assert convert.read_image(planned).GetSize() == (3, 3, 3)


def test_atomic_publication_never_overwrites_a_racing_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "source"
    write_series(root, shape=(3, 3, 3), marker=(1, 1, 2))
    series = scan.discover(root, [])[0]
    out = tmp_path / "derived" / "volume.nii.gz"
    original_replace, original_link = os.replace, os.link

    def race_replace(src: Any, dst: Any, **kwargs: Any) -> None:
        if Path(dst) == out:
            out.write_bytes(b"other committed writer")
        original_replace(src, dst, **kwargs)

    def race_link(src: Any, dst: Any, **kwargs: Any) -> None:
        if Path(dst) == out:
            out.write_bytes(b"other committed writer")
        original_link(src, dst, **kwargs)

    monkeypatch.setattr(os, "replace", race_replace)
    monkeypatch.setattr(os, "link", race_link)
    with pytest.raises(FileExistsError):
        convert.write_nifti(series, out)
    assert out.read_bytes() == b"other committed writer"
    assert list(out.parent.iterdir()) == [out]


def test_native_reader_uses_a_pinned_file_when_the_source_path_is_swapped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D04/D28: native GDCM receives the guarded file, not a later symlink target."""
    import SimpleITK as sitk

    root = tmp_path / "source"
    outside = tmp_path / "outside"
    write_series(root, shape=(3, 3, 1), marker=(1, 1, 0))
    write_series(outside, shape=(5, 5, 1), marker=(1, 1, 0), seed="outside")
    series = scan.discover(root, [])[0]
    original = sitk.ReadImage

    def swap_path(filename: Any, *args: Any, **kwargs: Any) -> Any:
        series.files[0].unlink()
        series.files[0].symlink_to(outside / "IM0000.dcm")
        return original(filename, *args, **kwargs)

    monkeypatch.setattr(sitk, "ReadImage", swap_path)
    assert convert.read_image(series).GetSize() == (3, 3, 1)


def test_image_validation_returns_the_full_compressed_digest(tmp_path: Path) -> None:
    import hashlib
    import json
    from dataclasses import asdict

    from plugins.dicom import commits

    source = tmp_path / "source"
    write_series(source, shape=(3, 3, 3), marker=(1, 1, 2), seed="compressed-validation")
    image = tmp_path / "derived/image.nii.gz"
    converted = convert.write_nifti(scan.discover(source, [])[0], image)
    geometry = json.loads(json.dumps(asdict(converted)))
    expected = {
        "size": image.stat().st_size,
        "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
    }
    assert commits._image_digest(image, geometry) == expected


def test_corrupt_native_gzip_is_refused_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_dicom_resume import run_conversion

    source = tmp_path / "source"
    write_series(source, shape=(3, 3, 3), marker=(1, 1, 2), seed="bad-crc")
    output = tmp_path / "derived"
    original = convert.write_nifti

    def corrupt(*args: Any, **kwargs: Any) -> Any:
        geometry = original(*args, **kwargs)
        image = args[1]
        data = bytearray(image.read_bytes())
        data[-8] ^= 1
        image.write_bytes(data)
        return geometry

    monkeypatch.setattr(convert, "write_nifti", corrupt)
    result = run_conversion(source, output)
    assert result.counts["failed"] == 1 and not result.counts["converted"]
    assert not list((output / "nifti").glob("*.nii.gz"))


def test_staged_artifact_changed_after_validation_is_not_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from plugins.dicom import commits

    from tests.test_dicom_resume import run_conversion

    source = tmp_path / "source"
    write_series(source, shape=(3, 3, 3), marker=(1, 1, 2), seed="changed-before-publish")
    output = tmp_path / "derived"
    original = commits._write

    def change_prepared(path: Path, record: dict[str, Any]) -> None:
        original(path, record)
        if record.get("status") == "prepared":
            image = path.parent / "staged/image.nii.gz"
            data = bytearray(image.read_bytes())
            data[-8] ^= 1
            image.write_bytes(data)

    monkeypatch.setattr(commits, "_write", change_prepared)
    result = run_conversion(source, output)
    assert result.counts["failed"] == 1 and not result.counts["converted"]
    assert not list((output / "nifti").glob("*.nii.gz"))
