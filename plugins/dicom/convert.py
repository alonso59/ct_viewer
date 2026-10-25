"""Convert stage: the only stage that reads pixels.

Volumes are written by the ITK image writer from the ITK image the series reader returned, so
direction, origin and spacing are preserved (ITK writes the LPS → RAS affine). A NIfTI is never
built from `GetArrayFromImage` without its geometry.
"""

from __future__ import annotations

import os
import resource
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from plugins.dicom import files as source_files
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

    soft_limit, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft_limit != resource.RLIM_INFINITY and len(series.files) + 64 > soft_limit:
        raise ValueError(
            "Series exceeds the available file-descriptor budget; raise the user limit or use a multiframe export"
        )
    # Linux OCI: native readers use descriptors opened through the guarded directory chain.
    # Discovery already ordered these members by physical slice position, as GDCM does.
    with ExitStack() as stack:
        pinned = [stack.enter_context(source_files.open_file(p, series.source_root)) for p in series.files]
        names = [f"/proc/self/fd/{stream.fileno()}" for stream in pinned]
        if len(names) == 1:
            image = sitk.ReadImage(names[0], imageIO="GDCMImageIO")
            return sitk.JoinSeries([image]) if image.GetDimension() == 2 else image
        reader = sitk.ImageSeriesReader()
        reader.SetImageIO("GDCMImageIO")
        reader.SetFileNames(names)
        return reader.Execute()


def write_nifti(series: Series, out: Path, *, before_publish: Callable[[], None] | None = None) -> Converted:
    """Publish a fully written file atomically without replacement."""
    import SimpleITK as sitk

    image = sitk.DICOMOrient(read_image(series), "RAS")
    out.parent.mkdir(parents=True, exist_ok=True)
    # unique per writer: two processes converting the same series never share a temp file
    tmp = out.with_name(f".{out.name}.{os.getpid()}.{os.urandom(4).hex()}.tmp.nii.gz")
    try:
        sitk.WriteImage(image, str(tmp), True)
        with tmp.open("rb") as fh:
            os.fsync(fh.fileno())
        if before_publish is not None:
            before_publish()
        os.link(tmp, out)  # atomic no-clobber on the same filesystem; never check-then-replace
        directory = os.open(out.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        tmp.unlink(missing_ok=True)
    return Converted(
        tuple(int(v) for v in image.GetSize()),
        tuple(float(v) for v in image.GetSpacing()),
        tuple(float(v) for v in image.GetOrigin()),
        tuple(float(v) for v in image.GetDirection()),
        image.GetPixelIDTypeAsString(),
    )
