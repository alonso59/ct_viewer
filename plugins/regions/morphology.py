"""Derived tumor regions on a mask's own voxel grid, measured in millimetres.

Distances are Euclidean between voxel centres, scaled by the voxel sizes of the affine;
nothing is resampled. All lesions of the tumor label form one tumor.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.ndimage import distance_transform_edt  # type: ignore[import-untyped]

DEFINITION = "1"  # bump when a region's definition changes
VALUES = {"core": 1, "rim": 2, "peri": 3}  # values in the written label map
NAMES = {"core": "tumor_core", "rim": "tumor_rim", "peri": "peritumoral"}


def spacing_of(affine: NDArray[Any]) -> NDArray[np.float64]:
    """Voxel size per array axis; refuses degenerate or sheared axes (the distance needs both)."""
    axes = np.asarray(affine, dtype=np.float64)[:3, :3]
    spacing = np.sqrt((axes**2).sum(axis=0))
    if not np.all(np.isfinite(spacing)) or np.any(spacing <= 0):
        raise ValueError("the mask affine has a zero or invalid voxel size")
    unit = axes / spacing
    if not np.allclose(unit.T @ unit, np.eye(3), atol=1e-4):
        raise ValueError("the mask affine is sheared; voxel axes must be orthogonal")
    return spacing


def derive(
    labels: NDArray[Any],
    spacing: Sequence[float] | NDArray[np.float64],
    tumor: Sequence[int],
    organ: Sequence[int] | None,
    *,
    core_mm: float,
    peri_inner_mm: float,
    peri_outer_mm: float,
    regions: Sequence[str] = tuple(VALUES),
) -> NDArray[np.uint8]:
    """Label map of the requested regions (`VALUES`); the regions never overlap.

    core = tumor voxels farther than `core_mm` from the outside; rim = tumor minus core;
    peri = voxels outside the tumor at a distance in (`peri_inner_mm`, `peri_outer_mm`],
    limited to `organ` unless it is None.
    """
    is_tumor = np.isin(labels, list(tumor))
    out = np.zeros(labels.shape, dtype=np.uint8)
    sampling = [float(s) for s in spacing]
    core = is_tumor & (distance_transform_edt(is_tumor, sampling=sampling) > core_mm)
    if "core" in regions:
        out[core] = VALUES["core"]
    if "rim" in regions:
        out[is_tumor & ~core] = VALUES["rim"]
    if "peri" in regions:
        outside = distance_transform_edt(~is_tumor, sampling=sampling)
        band = (outside > peri_inner_mm) & (outside <= peri_outer_mm)
        if organ is not None:
            band &= np.isin(labels, list(organ))
        out[band] = VALUES["peri"]
    return out


def quality(
    regions_map: NDArray[np.uint8],
    n_tumor: int,
    spacing: Sequence[float] | NDArray[np.float64],
    regions: Sequence[str],
    *,
    min_voxels: int,
    core_mm: float,
    peri_width_mm: float,
) -> dict[str, Any]:
    """Voxel counts, volumes and flags of one item's regions."""
    voxel_ml = float(np.prod(spacing)) / 1000.0
    counts = np.bincount(regions_map.ravel(), minlength=len(VALUES) + 1)
    voxels = {"tumor": int(n_tumor)} | {r: int(counts[VALUES[r]]) for r in regions}
    flags = [f"empty_{r}" for r in regions if voxels[r] == 0]
    flags += [f"too_small_{r}" for r in regions if 0 < voxels[r] < min_voxels]
    # A distance shorter than a voxel only moves the region by whole voxels along that axis
    limits = [core_mm] if {"core", "rim"} & set(regions) else []
    limits += [peri_width_mm] if "peri" in regions else []
    if limits and max(spacing) > min(limits):
        flags.append("coarse_spacing")
    return {
        "spacing": [round(float(s), 6) for s in spacing],
        "voxels": voxels,
        "volume_ml": {k: round(v * voxel_ml, 4) for k, v in voxels.items()},
        "flags": flags,
    }
