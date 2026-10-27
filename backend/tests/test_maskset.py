"""SRC-04/BE-02: mask sets preserve geometry and source containment on worker reads."""

from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from app.imaging import maskset


def test_composition_refuses_different_member_affines(tmp_path: Path) -> None:
    folder = tmp_path / "masks"
    folder.mkdir()
    for name, x in (("a", 0), ("b", 10)):
        affine = np.eye(4)
        affine[0, 3] = x
        nib.save(
            nib.Nifti1Image(np.ones((2, 3, 4), dtype=np.uint8), affine), folder / f"{name}.nii.gz"
        )
    dst = tmp_path / "cache" / "composed.nii.gz"
    error = maskset.compose(str(folder), {"a": 1, "b": 2}, str(dst))
    assert error is not None and "affine" in error
    assert not dst.exists()


def test_members_refuse_symbolic_links(tmp_path: Path) -> None:
    folder = tmp_path / "masks"
    folder.mkdir()
    external = tmp_path / "private.nii.gz"
    external.write_bytes(b"must not be read as a mask")
    (folder / "organ.nii.gz").symlink_to(external)
    with pytest.raises(ValueError, match="symbolic link"):
        maskset.members(folder)
    dst = tmp_path / "cache" / "composed.nii.gz"
    error = maskset.compose(str(folder), {"organ": 1}, str(dst))
    assert error is not None and "symbolic link" in error
    assert not dst.exists()


def test_removing_one_binary_label_reveals_overlap_and_keeps_sources(tmp_path: Path) -> None:
    """SRC-20: label removal excludes a member before composition, never edits it."""
    folder = tmp_path / "masks"
    folder.mkdir()
    affine = np.diag([2.0, 3.0, 4.0, 1.0])
    for name in ("organ", "lesion"):
        nib.save(
            nib.Nifti1Image(np.ones((2, 3, 4), dtype=np.uint8), affine), folder / f"{name}.nii.gz"
        )
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    labels = {"organ": 1, "lesion": 2}
    for removed, expected in (([], 2), ([2], 1), ([1, 2], 0)):
        dst = maskset.cache_path(tmp_path, maskset.fingerprint(folder), labels, removed)
        assert maskset.compose(str(folder), labels, str(dst), removed) is None
        img = nib.load(dst)
        assert np.all(img.get_fdata() == expected)
        np.testing.assert_array_equal(img.affine, affine)
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before


def test_filtering_combined_labels_preserves_other_voxels_and_geometry(tmp_path: Path) -> None:
    """SRC-20 / R1: a filtered cache is disposable; its source stays byte-identical."""
    src = tmp_path / "mask.nii.gz"
    values = np.array([0, 1, 2, 2, 3, 1], dtype=np.uint16).reshape((1, 2, 3))
    affine = np.diag([1.5, 2.5, 3.5, 1.0])
    affine[:3, 3] = [17, 29, 43]
    img = nib.Nifti1Image(values, affine)
    img.set_qform(affine, 2)
    img.set_sform(affine, 4)
    nib.save(img, src)
    before = src.read_bytes()
    dst = tmp_path / "cache" / "filtered.nii.gz"
    assert maskset.filter_labels(str(src), [2], str(dst)) is None
    filtered = nib.load(dst)
    np.testing.assert_array_equal(filtered.get_fdata(), np.where(values == 2, 0, values))
    np.testing.assert_array_equal(filtered.affine, affine)
    assert filtered.header.get_data_dtype() == np.uint16
    assert int(filtered.header["qform_code"]) == 2
    assert int(filtered.header["sform_code"]) == 4
    assert src.read_bytes() == before
