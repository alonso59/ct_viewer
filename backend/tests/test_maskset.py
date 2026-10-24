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
