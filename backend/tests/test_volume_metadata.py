from __future__ import annotations

from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from app.services.volume_cache import volume_cache
from app.services.volume_metadata import GEOMETRY_ALIGNMENT_TOLERANCE_MM


def test_volume_info_includes_canonical_geometry_and_stable_fingerprints(tmp_path: Path):
    volume_cache.reset()
    image_path = tmp_path / "ct.nii.gz"
    mask_path = tmp_path / "seg.nii.gz"
    affine = np.eye(4, dtype=np.float64)
    affine[0, 0] = 0.5
    affine[1, 1] = 0.75
    affine[2, 2] = 2.0
    affine[:3, 3] = [-10.0, 20.0, 30.0]
    ct = np.arange(3 * 4 * 5, dtype=np.float32).reshape((3, 4, 5))
    mask = np.zeros((3, 4, 5), dtype=np.uint8)
    mask[1, 2, 3] = 1
    mask[2, 3, 4] = 3
    _write_nifti(image_path, ct, affine)
    _write_nifti(mask_path, mask, affine)

    info = _load_case(image_path, mask_path, source_type="nifti")
    assert info.shape == [3, 4, 5]
    assert info.spacing == pytest.approx([0.5, 0.75, 2.0])
    assert info.has_mask is True
    assert info.labels == [1, 3]
    assert info.metadata is not None
    assert info.metadata.geometry.dimensions == [3, 4, 5]
    assert info.metadata.geometry.spacing == pytest.approx([0.5, 0.75, 2.0])
    assert info.metadata.geometry.origin == pytest.approx([-10.0, 20.0, 30.0])
    np.testing.assert_allclose(info.metadata.geometry.direction, np.eye(3))
    np.testing.assert_allclose(info.metadata.geometry.index_to_world, affine)
    assert info.metadata.geometry.dtype == "float32"
    assert info.metadata.geometry.byte_order == "little"
    assert info.metadata.geometry.scalar_range == pytest.approx([0.0, 59.0])
    assert info.metadata.segmentation is not None
    assert info.metadata.segmentation.geometry.dtype == "uint8"
    assert info.metadata.segmentation.labels == [1, 3]
    assert info.metadata.alignment.status == "aligned"
    assert info.metadata.alignment.cornerstone_compatible is True
    assert len(info.metadata.source_fingerprint) == 64
    assert len(info.metadata.geometry_fingerprint) == 64
    assert len(info.metadata.fingerprint) == 64

    second_info = _load_case(image_path, mask_path, source_type="nifti")
    assert second_info.load_handle != info.load_handle
    assert second_info.metadata is not None
    assert second_info.metadata.fingerprint == info.metadata.fingerprint
    assert second_info.metadata.geometry_fingerprint == info.metadata.geometry_fingerprint


def test_affine_mismatch_warns_and_keeps_png_segmentation_available(tmp_path: Path):
    volume_cache.reset()
    image_path = tmp_path / "ct.nii.gz"
    mask_path = tmp_path / "seg.nii.gz"
    ct_affine = np.eye(4, dtype=np.float64)
    mask_affine = np.eye(4, dtype=np.float64)
    mask_affine[0, 3] = GEOMETRY_ALIGNMENT_TOLERANCE_MM * 10
    ct = np.zeros((4, 4, 4), dtype=np.float32)
    mask = np.zeros((4, 4, 4), dtype=np.uint8)
    mask[1, 1, 1] = 2
    _write_nifti(image_path, ct, ct_affine)
    _write_nifti(mask_path, mask, mask_affine)

    info = _load_case(image_path, mask_path, source_type="nifti")

    assert info.has_mask is True
    assert info.labels == [2]
    assert info.metadata is not None
    assert info.metadata.alignment.status == "mismatch"
    assert info.metadata.alignment.shape_matches is True
    assert info.metadata.alignment.affine_matches is False
    assert info.metadata.alignment.cornerstone_compatible is False
    assert {warning.code for warning in info.warnings} == {"affine_mismatch"}
    assert "fallback to PNG" in info.warnings[0].message


def test_shape_mismatch_disables_segmentation_and_reports_warning(tmp_path: Path):
    volume_cache.reset()
    image_path = tmp_path / "ct.nii.gz"
    mask_path = tmp_path / "seg.nii.gz"
    affine = np.eye(4, dtype=np.float64)
    ct = np.zeros((4, 4, 4), dtype=np.float32)
    mask = np.zeros((4, 4, 3), dtype=np.uint8)
    mask[1, 1, 1] = 1
    _write_nifti(image_path, ct, affine)
    _write_nifti(mask_path, mask, affine)

    info = _load_case(image_path, mask_path, source_type="nifti")

    assert info.shape == [4, 4, 4]
    assert info.has_mask is False
    assert info.labels == []
    assert info.metadata is not None
    assert info.metadata.segmentation is not None
    assert info.metadata.segmentation.geometry.dimensions == [4, 4, 3]
    assert info.metadata.segmentation.labels == [1]
    assert info.metadata.alignment.status == "mismatch"
    assert info.metadata.alignment.shape_matches is False
    assert info.metadata.alignment.cornerstone_compatible is False
    assert {warning.code for warning in info.warnings} == {"shape_mismatch"}
    assert "segmentation overlays are disabled" in info.warnings[0].message


def test_numpy_voi_metadata_uses_identity_geometry_and_preserves_uint8_labelmap(tmp_path: Path):
    volume_cache.reset()
    image_path = tmp_path / "voi_image.npy"
    mask_path = tmp_path / "voi_mask.npy"
    np.save(image_path, np.arange(2 * 3 * 4, dtype=np.float32).reshape((2, 3, 4)))
    mask = np.zeros((2, 3, 4), dtype=np.uint8)
    mask[1, 2, 3] = 2
    np.save(mask_path, mask)

    info = _load_case(image_path, mask_path, source_type="voi_numpy")

    assert info.shape == [2, 3, 4]
    assert info.spacing == [1.0, 1.0, 1.0]
    assert info.has_mask is True
    assert info.labels == [2]
    assert info.metadata is not None
    assert info.metadata.source_format == "numpy"
    assert info.metadata.geometry.origin == [0.0, 0.0, 0.0]
    np.testing.assert_allclose(info.metadata.geometry.direction, np.eye(3))
    np.testing.assert_allclose(info.metadata.geometry.index_to_world, np.eye(4))
    assert info.metadata.geometry.dtype == "float32"
    assert info.metadata.segmentation is not None
    assert info.metadata.segmentation.geometry.dtype == "uint8"
    assert info.metadata.alignment.cornerstone_compatible is True


def _load_case(image_path: Path, mask_path: Path | None, *, source_type: str):
    return volume_cache.load_case_source(
        dataset_id="Dataset",
        case_id="case-1",
        series_id="series-1",
        image_path=str(image_path),
        mask_path=str(mask_path) if mask_path is not None else None,
        source_type=source_type,
        cache_key_suffix=f"{source_type}:{image_path.name}:{mask_path.name if mask_path else ''}",
    )


def _write_nifti(path: Path, data: np.ndarray, affine: np.ndarray) -> None:
    nib.save(nib.Nifti1Image(data, affine), str(path))
