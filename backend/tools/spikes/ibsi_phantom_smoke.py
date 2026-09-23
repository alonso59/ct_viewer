"""ADR-0006 spike: PyRadiomics on Python 3.12 vs the IBSI 1 digital phantom (smoke test).

Needs the `[radiomics]` extra. Phantom voxels are embedded (4x4x5, 2 mm, 74 ROI voxels) so the
script runs offline. Full TST-06 compliance (all families, CT phantom) is lane P5.

    backend/.venv/bin/python -m tools.spikes.ibsi_phantom_smoke
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import numpy as np

# SimpleITK array order (z, y, x); source: github.com/theibsi/data_sets ibsi_1_digital_phantom
IMAGE = [
    [[1, 4, 4, 1, 1], [1, 4, 6, 1, 1], [4, 1, 6, 4, 1], [4, 4, 6, 4, 1]],
    [[1, 4, 4, 1, 1], [1, 1, 6, 1, 1], [1, 1, 3, 1, 1], [4, 4, 6, 1, 1]],
    [[1, 4, 4, 1, 1], [1, 1, 1, 1, 1], [1, 1, 9, 1, 1], [1, 1, 6, 1, 1]],
    [[1, 4, 4, 1, 1], [1, 1, 1, 1, 1], [1, 1, 1, 1, 1], [1, 1, 6, 1, 1]],
]
MASK = [
    [[1, 1, 1, 1, 1], [1, 1, 1, 1, 1], [1, 1, 1, 1, 1], [1, 1, 1, 1, 1]],
    [[1, 1, 1, 1, 1], [1, 1, 1, 1, 1], [0, 1, 1, 1, 1], [1, 1, 1, 1, 1]],
    [[1, 1, 1, 0, 0], [1, 1, 1, 1, 1], [1, 1, 0, 1, 1], [1, 1, 1, 1, 1]],
    [[1, 1, 1, 0, 0], [1, 1, 1, 1, 1], [1, 1, 1, 1, 1], [1, 1, 1, 1, 1]],
]
# (PyRadiomics feature, IBSI reference, abs tolerance). Kurtosis: PyRadiomics is non-excess (+3).
REFERENCE: list[tuple[str, float, float]] = [
    ("original_firstorder_Mean", 2.15, 0.01),
    ("original_firstorder_Variance", 3.05, 0.02),
    ("original_firstorder_Skewness", 1.08, 0.01),
    ("original_firstorder_Kurtosis", -0.355 + 3, 0.002),
    ("original_firstorder_Median", 1, 0),
    ("original_firstorder_Minimum", 1, 0),
    ("original_firstorder_10Percentile", 1, 0),
    ("original_firstorder_90Percentile", 4, 0),
    ("original_firstorder_Maximum", 6, 0),
    ("original_firstorder_InterquartileRange", 3, 0),
    ("original_firstorder_Range", 5, 0),
    ("original_firstorder_MeanAbsoluteDeviation", 1.55, 0.01),
    ("original_firstorder_RobustMeanAbsoluteDeviation", 1.11, 0.01),
    ("original_firstorder_Energy", 567, 0.5),
    ("original_firstorder_RootMeanSquared", 2.77, 0.01),
    ("original_firstorder_Entropy", 1.27, 0.01),
    ("original_firstorder_Uniformity", 0.512, 0.001),
    ("original_shape_MeshVolume", 556, 1),
    ("original_shape_VoxelVolume", 592, 0),
    ("original_shape_SurfaceArea", 388, 1),
]


def run() -> int:
    import radiomics
    import SimpleITK as sitk
    from radiomics import featureextractor

    radiomics.logger.setLevel(logging.ERROR)
    images: list[Any] = []
    for arr in (IMAGE, MASK):
        im = sitk.GetImageFromArray(np.asarray(arr, dtype=np.int16))
        im.SetSpacing((2.0, 2.0, 2.0))
        images.append(im)
    ext = featureextractor.RadiomicsFeatureExtractor(binWidth=1, label=1)
    ext.disableAllFeatures()
    ext.enableFeatureClassByName("firstorder")
    ext.enableFeatureClassByName("shape")
    result = ext.execute(images[0], images[1])
    fails = 0
    for key, ref, tol in REFERENCE:
        got = float(result[key])
        ok = abs(got - ref) <= tol + 0.005 * abs(ref)
        fails += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {key:50s} {got:10.4f}  ibsi {ref}")
    print(f"pyradiomics {radiomics.__version__}  python {sys.version.split()[0]}  fails {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
