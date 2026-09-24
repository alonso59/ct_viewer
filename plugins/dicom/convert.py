"""Convert stage (DCM-02, DCM-10): the only stage that reads pixels.

Volumes are written by the ITK image writer from the ITK image the series reader returned, so
direction, origin and spacing are preserved (ITK writes the LPS → RAS affine). A NIfTI is never
built from `GetArrayFromImage` without its geometry.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from plugins.dicom.scan import Series


@dataclass(frozen=True)
class Converted:
    size: tuple[int, ...]
    spacing: tuple[float, ...]
    origin: tuple[float, ...]
    direction: tuple[float, ...]
    pixel_type: str


def read_image(series: Series) -> Any:
    """Series → one ITK image; one file: multi-frame → 3D, a classic slice → a 1-slice volume."""
    import SimpleITK as sitk

    if len(series.files) == 1:
        image = sitk.ReadImage(str(series.files[0]))
        if image.GetDimension() == 2:
            image = sitk.JoinSeries([image])
        return image
    reader = sitk.ImageSeriesReader()
    reader.SetFileNames([str(p) for p in series.files])
    return reader.Execute()


def write_nifti(series: Series, out: Path) -> Converted:
    """Write atomically (temp + rename); `out` must not exist (append-only dataset, ADR-0014)."""
    import SimpleITK as sitk

    image = sitk.DICOMOrient(read_image(series), "RAS")
    out.parent.mkdir(parents=True, exist_ok=True)
    # unique per writer: two processes converting the same series never share a temp file
    tmp = out.with_name(f".{out.name}.{os.getpid()}.{os.urandom(4).hex()}.tmp.nii.gz")
    sitk.WriteImage(image, str(tmp), True)
    if out.exists():
        tmp.unlink(missing_ok=True)
        raise FileExistsError(f"{out.name} already exists (never rewritten)")
    os.replace(tmp, out)
    return Converted(
        tuple(int(v) for v in image.GetSize()),
        tuple(float(v) for v in image.GetSpacing()),
        tuple(float(v) for v in image.GetOrigin()),
        tuple(float(v) for v in image.GetDirection()),
        image.GetPixelIDTypeAsString(),
    )
