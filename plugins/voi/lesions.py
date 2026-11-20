"""Lesions of a VOI crop, measured on the grid that was written (so voxel indices match the files).

A lesion is a 26-connected component of the lesion labels. The measures follow the research
pipeline's lesion catalog so a catalog written here can replace it: boxes count voxels inclusively,
millimetres are voxels times the voxel size, and contact is the share of the one-voxel shell around
a lesion that is organ.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy import ndimage  # type: ignore[import-untyped]

CONNECTIVITY = np.ones((3, 3, 3), dtype=bool)
HU_LO, HU_BINS = -1024, 4096  # 1 HU bins from -1024 to 3071; values outside land in the end bins


def _r(values: Any, nd: int = 3) -> list[float]:
    return [round(float(v), nd) for v in values]


def voxel_size(affine: NDArray[Any]) -> NDArray[np.float64]:
    return np.sqrt((np.asarray(affine, dtype=np.float64)[:3, :3] ** 2).sum(axis=0))


def measure(
    labels: NDArray[Any],
    image: NDArray[Any] | None,
    affine: NDArray[Any],
    lesion_values: Sequence[int],
    organ_values: Sequence[int],
    min_voxels: int,
) -> tuple[list[dict[str, Any]], int]:
    """The lesions, largest first (`lesion` 1, 2, …), and how many components were smaller than
    `min_voxels` and left out. `label_value` is the lesion's most frequent label in the file."""
    lesion = np.isin(labels, list(lesion_values))
    if not lesion.any():
        return [], 0
    organ = np.isin(labels, list(organ_values))
    zooms = voxel_size(affine)
    cc, n = ndimage.label(lesion, structure=CONNECTIVITY)
    sizes = np.bincount(cc.ravel(), minlength=n + 1)
    kept = sorted((k for k in range(1, n + 1) if sizes[k] >= min_voxels), key=lambda k: (-sizes[k], k))
    boxes = ndimage.find_objects(cc)
    out: list[dict[str, Any]] = []
    for rank, k in enumerate(kept, start=1):
        box = boxes[k - 1]
        lo = np.array([s.start for s in box])
        hi = np.array([s.stop for s in box])
        comp = cc[box] == k
        centroid = np.asarray(ndimage.center_of_mass(comp)) + lo
        # The shell is one voxel thick, so a window one voxel wider than the box holds it.
        wlo, whi = np.maximum(lo - 1, 0), np.minimum(hi + 1, labels.shape)
        window = tuple(slice(int(a), int(b)) for a, b in zip(wlo, whi, strict=True))
        inside = cc[window] == k
        shell = ndimage.binary_dilation(inside, structure=CONNECTIVITY) & ~inside
        n_shell = int(shell.sum())
        contact = int((shell & organ[window]).sum())
        values, counts = np.unique(labels[box][comp], return_counts=True)
        size = hi - lo
        row: dict[str, Any] = {
            "lesion": rank,
            "label_value": int(values[np.argmax(counts)]),
            "volume_vox": int(sizes[k]),
            "volume_mm3": round(float(sizes[k] * zooms.prod()), 3),
            "centroid_vox": _r(centroid),
            "centroid_mm": _r(centroid * zooms),
            "centroid_world": _r(np.asarray(affine)[:3, :3] @ centroid + np.asarray(affine)[:3, 3]),
            "bbox_min_vox": [int(v) for v in lo],
            "bbox_max_vox": [int(v) for v in hi],  # exclusive
            "bbox_size_vox": [int(v) for v in size],
            "bbox_size_mm": _r(size * zooms),
            "max_extent_vox": int(size.max()),
            "max_extent_mm": round(float((size * zooms).max()), 3),
            "organ_overlap_vox": int((comp & organ[box]).sum()),
            "organ_contact_vox": contact,
            "organ_contact_ratio": round(contact / n_shell, 6) if n_shell else 0.0,
        }
        if image is not None:
            hu = np.asarray(image[box][comp], dtype=np.float64)
            p5, p50, p95 = np.percentile(hu, [5, 50, 95])
            row["hu"] = {
                "mean": round(float(hu.mean()), 2),
                "std": round(float(hu.std()), 2),
                "p5": round(float(p5), 2),
                "p50": round(float(p50), 2),
                "p95": round(float(p95), 2),
            }
        out.append(row)
    return out, int(n - len(kept))


def hu_histogram(image: NDArray[Any], foreground: NDArray[np.bool_]) -> dict[str, Any]:
    """Foreground intensities as 1 HU counts from `lo` (trimmed to the occupied range) plus the
    exact count, sum, sum of squares, min and max, so dataset statistics pool over VOIs (and over
    a resumed run) without keeping the voxels."""
    v = np.asarray(image[foreground], dtype=np.float64)
    counts = np.bincount(np.clip(np.rint(v) - HU_LO, 0, HU_BINS - 1).astype(np.intp), minlength=HU_BINS)
    nz = np.flatnonzero(counts)
    start, stop = (int(nz[0]), int(nz[-1]) + 1) if nz.size else (0, 0)
    return {
        "lo": HU_LO + start,
        "counts": [int(c) for c in counts[start:stop]],
        "n": int(v.size),
        "sum": float(v.sum()),
        "sumsq": float((v * v).sum()),
        "min": float(v.min()) if v.size else None,
        "max": float(v.max()) if v.size else None,
    }
