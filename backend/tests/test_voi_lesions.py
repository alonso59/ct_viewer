"""ADR-0061: lesions measured in a VOI crop (`plugins/voi/lesions.py`)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from plugins.voi import lesions

KIDNEY, TUMOR, CYST = 1, 2, 3


def volume() -> np.ndarray:
    labels = np.zeros((40, 40, 30), np.uint8)
    labels[5:35, 5:35, 3:27] = KIDNEY
    labels[10:20, 10:22, 8:16] = TUMOR  # inside the kidney
    labels[28:31, 28:31, 20:23] = TUMOR  # small, inside
    labels[2, 2, 2] = TUMOR  # two voxels joined only at a corner: one component, too small
    labels[3, 3, 3] = TUMOR
    labels[36:39, 2:5, 1:4] = TUMOR  # outside the kidney
    labels[33:37, 20:24, 12:15] = TUMOR  # across the kidney's edge
    return labels


# The research `_compute_lesion_entries` on `volume()` with min_lesion_voxels=5, in its order
# (volume_vox, bbox_min_vox, bbox_size_vox, centroid_vox, kidney_contact_vox, kidney_contact_ratio).
RESEARCH = [
    (960, [10, 10, 8], [10, 12, 8], [14.5, 15.5, 11.5], 720, 1.0),
    (27, [28, 28, 20], [3, 3, 3], [29.0, 29.0, 21.0], 98, 1.0),
    (48, [33, 20, 12], [4, 4, 3], [34.5, 21.5, 13.0], 66, 0.5),
    (27, [36, 2, 1], [3, 3, 3], [37.0, 3.0, 2.0], 0, 0.0),
]


def affine(zooms: tuple[float, float, float], origin: tuple[float, ...] = (0, 0, 0)) -> np.ndarray:
    a = np.diag([*zooms, 1.0])
    a[:3, 3] = origin
    return a


@pytest.mark.parametrize("zooms", [(1.0, 1.0, 1.0), (0.8, 0.8, 2.0)])
def test_lesions_match_the_research_catalog(zooms: tuple[float, float, float]) -> None:
    found, below = lesions.measure(volume(), None, affine(zooms), [TUMOR], [KIDNEY], 5)
    assert below == 1
    got = sorted(
        (
            r["volume_vox"],
            r["bbox_min_vox"],
            r["bbox_size_vox"],
            r["centroid_vox"],
            r["organ_contact_vox"],
            r["organ_contact_ratio"],
        )
        for r in found
    )
    assert got == sorted(RESEARCH)
    by_voxels = {r["volume_vox"]: r for r in found}
    big = by_voxels[960]
    assert big["volume_mm3"] == pytest.approx(960 * np.prod(zooms))
    assert big["bbox_size_mm"] == pytest.approx([10 * zooms[0], 12 * zooms[1], 8 * zooms[2]])
    assert big["max_extent_mm"] == pytest.approx(max(big["bbox_size_mm"]))
    assert big["centroid_mm"] == pytest.approx([14.5 * zooms[0], 15.5 * zooms[1], 11.5 * zooms[2]])
    assert all(r["organ_overlap_vox"] == 0 for r in found)


def test_lesions_are_numbered_largest_first_and_placed_in_the_patient() -> None:
    found, _ = lesions.measure(
        volume(), None, affine((0.8, 0.8, 2.0), (-10, 5, 100)), [TUMOR], [KIDNEY], 5
    )
    assert [r["lesion"] for r in found] == [1, 2, 3, 4]
    assert [r["volume_vox"] for r in found] == [960, 48, 27, 27]
    assert [r["bbox_min_vox"][0] for r in found[2:]] == [28, 36]  # ties keep the scan order
    assert found[0]["centroid_world"] == pytest.approx(
        [-10 + 14.5 * 0.8, 5 + 15.5 * 0.8, 100 + 23.0]
    )
    assert all(r["label_value"] == TUMOR for r in found)


def test_several_lesion_labels_and_the_dominant_label() -> None:
    labels = volume()
    labels[10:13, 10:22, 8:16] = CYST  # a cyst slab touching the big tumor joins it as one lesion
    found, _ = lesions.measure(labels, None, affine((1, 1, 1)), [TUMOR, CYST], [KIDNEY], 5)
    assert found[0]["volume_vox"] == 960 and found[0]["label_value"] == TUMOR
    only_tumor, _ = lesions.measure(labels, None, affine((1, 1, 1)), [TUMOR], [KIDNEY], 5)
    assert only_tumor[0]["volume_vox"] == 960 - 3 * 12 * 8


def test_minimum_size_and_no_lesion() -> None:
    labels = volume()
    found, below = lesions.measure(labels, None, affine((1, 1, 1)), [TUMOR], [KIDNEY], 30)
    assert [r["volume_vox"] for r in found] == [960, 48] and below == 3
    assert lesions.measure(labels, None, affine((1, 1, 1)), [CYST], [KIDNEY], 1) == ([], 0)


def test_intensity_of_each_lesion() -> None:
    labels = volume()
    image = np.where(labels == KIDNEY, 150.0, -50.0).astype(np.float32)
    image[labels == TUMOR] = 40.0
    image[10:15, 10:22, 8:16] = 60.0  # half of the big lesion is brighter
    found, _ = lesions.measure(labels, image, affine((1, 1, 1)), [TUMOR], [KIDNEY], 5)
    hu: dict[str, Any] = found[0]["hu"]
    assert hu["mean"] == pytest.approx(50.0) and hu["std"] == pytest.approx(10.0)
    assert (hu["p5"], hu["p95"]) == (40.0, 60.0)
    assert found[1]["hu"]["mean"] == 40.0
    assert "hu" not in lesions.measure(labels, None, affine((1, 1, 1)), [TUMOR], [KIDNEY], 5)[0][0]


def test_hu_histograms_pool_exactly() -> None:
    rng = np.random.default_rng(0)
    parts = [rng.normal(40, 30, (20, 20, 10)), rng.normal(150, 50, (10, 10, 10)) - 0.4]
    hists = [lesions.hu_histogram(p, np.ones(p.shape, bool)) for p in parts]
    pooled = np.concatenate([p.ravel() for p in parts])
    assert sum(h["n"] for h in hists) == pooled.size
    assert sum(h["sum"] for h in hists) == pytest.approx(pooled.sum())
    assert sum(h["sumsq"] for h in hists) == pytest.approx((pooled**2).sum())
    assert min(h["min"] for h in hists) == pooled.min()
    counts = np.zeros(lesions.HU_BINS, np.int64)
    for h in hists:
        start = h["lo"] - lesions.HU_LO
        counts[start : start + len(h["counts"])] += h["counts"]
    assert np.array_equal(
        counts, np.bincount(np.rint(pooled).astype(int) - lesions.HU_LO, minlength=lesions.HU_BINS)
    )
    clipped = lesions.hu_histogram(np.array([-3000.0, 5000.0, 0.0]), np.ones(3, bool))
    assert (
        clipped["lo"] == lesions.HU_LO and clipped["counts"][0] == 1 and clipped["counts"][-1] == 1
    )
    assert (clipped["min"], clipped["max"]) == (-3000.0, 5000.0)
    empty = lesions.hu_histogram(np.zeros(3), np.zeros(3, bool))
    assert empty["n"] == 0 and empty["counts"] == [] and empty["min"] is None
