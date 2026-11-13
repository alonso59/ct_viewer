"""Convert stage: the only stage that reads pixels.

Volumes are written by the ITK image writer from the ITK image the series reader returned, so
direction, origin and spacing are preserved (ITK writes the LPS → RAS affine), with the slice axis
taken from the slice positions. A NIfTI is never built from `GetArrayFromImage` without its geometry.
"""

from __future__ import annotations

import os
import resource
import shutil
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rw_dicom import files as source_files
from rw_dicom.scan import Series


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
        reader.MetaDataDictionaryArrayUpdateOn()
        return _slice_axis_along_positions(reader, reader.Execute())


def _slice_axis_along_positions(reader: Any, image: Any) -> Any:
    """GDCM signs the slice axis with SpacingBetweenSlices; older Philips CT writes it negative,
    which turns the axis against the stacking order and flips the volume head to feet. The
    positions of the first and last slice decide the direction instead."""
    last = image.GetSize()[2] - 1
    key = "0020|0032"
    if last < 1 or not (reader.HasMetaDataKey(0, key) and reader.HasMetaDataKey(last, key)):
        return image
    first, end = ([float(v) for v in reader.GetMetaData(i, key).split("\\")] for i in (0, last))
    d = list(image.GetDirection())
    along = sum((b - a) * c for a, b, c in zip(first, end, (d[2], d[5], d[8]), strict=True))
    if along < 0:
        d[2], d[5], d[8] = -d[2], -d[5], -d[8]
        image.SetDirection(d)
        image.SetOrigin(first)
    return image


def write_nifti(series: Series, out: Path, *, before_publish: Callable[[], None] | None = None) -> Converted:
    """Publish a fully written file atomically without replacement."""
    import SimpleITK as sitk
    from isal import igzip

    image = sitk.DICOMOrient(read_image(series), "RAS")
    out.parent.mkdir(parents=True, exist_ok=True)
    # unique per writer: two processes converting the same series never share a temp file
    tmp = out.with_name(f".{out.name}.{os.getpid()}.{os.urandom(4).hex()}.tmp.nii.gz")
    plain = tmp.with_suffix("")
    try:
        sitk.WriteImage(image, str(plain), False)
        with (
            plain.open("rb") as source,
            tmp.open("wb") as target,
            igzip.IGzipFile(filename="", fileobj=target, mode="wb", compresslevel=2, mtime=0) as compressed,
        ):
            shutil.copyfileobj(source, compressed, 1024 * 1024)
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
        plain.unlink(missing_ok=True)
    return Converted(
        tuple(int(v) for v in image.GetSize()),
        tuple(float(v) for v in image.GetSpacing()),
        tuple(float(v) for v in image.GetOrigin()),
        tuple(float(v) for v in image.GetDirection()),
        image.GetPixelIDTypeAsString(),
    )
