"""Header reader for NIfTI and legacy `.npy` volumes (no voxel decode; BE-04/BE-12).

Used by indexing workers (IMP-05) and validation (IMP-08: unreadable_file, missing_affine,
shape_mismatch, affine_mismatch).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import nibabel as nib
import numpy as np

from app.core.paths import open_source

VolumeFormat = Literal["nifti", "npy"]
AFFINE_ATOL_MM = 1e-3


class HeaderError(Exception):
    """File exists but cannot be opened or has an invalid header (`unreadable_file`)."""


@dataclass(frozen=True)
class HeaderInfo:
    format: VolumeFormat
    shape: tuple[int, ...]
    spacing: tuple[float, ...]
    dtype: str
    orientation: str | None  # axis codes, e.g. "RAS"; None without a usable affine
    affine: list[list[float]] | None  # 4x4; None without a usable affine (`missing_affine`)

    def geometry(self) -> dict[str, Any]:
        """DATA_MODEL.md §Item `geometry`."""
        return {
            "shape": list(self.shape),
            "spacing": [round(s, 6) for s in self.spacing],
            "dtype": self.dtype,
            "orientation": self.orientation,
        }


def volume_format(path: Path | str) -> VolumeFormat:
    return "npy" if str(path).lower().endswith(".npy") else "nifti"


def read_header(path: Path, *, spacing: tuple[float, ...] | None = None) -> HeaderInfo:
    """Read geometry without decoding voxels. `spacing` is used for `.npy` (catalog spacing)."""
    if volume_format(path) == "npy":
        return _read_npy(path, spacing)
    try:
        img: Any = nib.load(path)
        hdr = img.header
        shape = tuple(int(s) for s in img.shape)
        zooms = tuple(float(z) for z in hdr.get_zooms()[: len(shape)])
        dtype = str(np.dtype(hdr.get_data_dtype()))
        sform_code = int(hdr["sform_code"]) if "sform_code" in hdr else 0
        qform_code = int(hdr["qform_code"]) if "qform_code" in hdr else 0
    except Exception as exc:
        raise HeaderError(f"{type(exc).__name__}: {exc}") from None
    if len(shape) < 3:
        raise HeaderError(f"expected a 3D volume, got shape {shape}")
    affine: list[list[float]] | None = None
    orientation: str | None = None
    if sform_code > 0 or qform_code > 0:
        aff = np.asarray(img.affine, dtype=float)
        if np.all(np.isfinite(aff)) and abs(np.linalg.det(aff[:3, :3])) > 1e-12:
            affine = aff.round(6).tolist()
            orientation = "".join(str(c) for c in nib.aff2axcodes(aff))
    return HeaderInfo("nifti", shape[:3], zooms[:3], dtype, orientation, affine)


def _read_npy(path: Path, spacing: tuple[float, ...] | None) -> HeaderInfo:
    try:
        with open_source(path) as fh:
            fmt = np.lib.format
            version = fmt.read_magic(fh)
            reader = fmt.read_array_header_1_0 if version == (1, 0) else fmt.read_array_header_2_0
            shape, _fortran, dtype = reader(fh)
    except Exception as exc:
        raise HeaderError(f"{type(exc).__name__}: {exc}") from None
    if len(shape) != 3:
        raise HeaderError(f"expected a 3D array, got shape {shape}")
    sp = tuple(float(s) for s in (spacing or (1.0, 1.0, 1.0)))
    return HeaderInfo("npy", tuple(int(s) for s in shape), sp, str(np.dtype(dtype)), None, None)


def compare_geometry(image: HeaderInfo, mask: HeaderInfo) -> list[Literal["shape", "affine"]]:
    """Mismatches between an image and its mask (IMP-08 shape_mismatch / affine_mismatch)."""
    issues: list[Literal["shape", "affine"]] = []
    if image.shape != mask.shape:
        issues.append("shape")
    if image.affine is not None and mask.affine is not None:
        a, b = np.asarray(image.affine), np.asarray(mask.affine)
        if not np.allclose(a, b, atol=AFFINE_ATOL_MM):
            issues.append("affine")
    return issues
