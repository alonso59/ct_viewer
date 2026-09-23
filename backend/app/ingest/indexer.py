"""Index job worker units (IMP-05, BE-06/12). Module-level, picklable, read-only (BE-03).

Units get plain absolute paths that were already guarded by the API process (BE-02).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np

from app.core.paths import open_source
from app.imaging.fingerprint import quick_fingerprint
from app.imaging.header import HeaderError, HeaderInfo, read_header, volume_format

BATCH_SIZE = 16


@dataclass(frozen=True)
class FileProbe:
    path: str
    spacing: tuple[float, ...] | None = None
    labels: bool = False  # decode voxels for `labels_present` (masks)


@dataclass(frozen=True)
class ItemProbe:
    item_id: str
    image: FileProbe | None = None
    mask: FileProbe | None = None


@dataclass(frozen=True)
class FileResult:
    exists: bool
    fp: str | None = None
    header: HeaderInfo | None = None
    error: str | None = None  # set → `unreadable_file`
    labels: tuple[int, ...] = ()


@dataclass(frozen=True)
class ItemProbeResult:
    item_id: str
    image: FileResult | None = None
    mask: FileResult | None = None


def _voxels(path: Path) -> Any:
    if volume_format(path) == "npy":
        with open_source(path) as fh:
            return np.load(fh, allow_pickle=False)
    img: Any = nib.load(path)
    return np.asanyarray(img.dataobj)


def labels_present(path: Path) -> tuple[int, ...]:
    """Distinct positive integer labels in a mask."""
    values = np.unique(_voxels(path))
    return tuple(int(v) for v in values if v > 0 and float(v).is_integer())


def probe_file(probe: FileProbe) -> FileResult:
    path = Path(probe.path)
    if not path.exists():
        return FileResult(exists=False)
    try:
        fp = quick_fingerprint(path)
    except OSError as exc:
        return FileResult(exists=True, error=f"{type(exc).__name__}: {exc}")
    try:
        header = read_header(path, spacing=probe.spacing)
    except HeaderError as exc:
        return FileResult(exists=True, fp=fp, error=str(exc))
    labels: tuple[int, ...] = ()
    if probe.labels:
        try:
            labels = labels_present(path)
        except Exception as exc:
            return FileResult(exists=True, fp=fp, header=header, error=f"voxels: {exc}")
    return FileResult(exists=True, fp=fp, header=header, labels=labels)


def probe_batch(probes: Sequence[ItemProbe]) -> list[ItemProbeResult]:
    """Worker unit: fingerprint + header (+ mask labels) for a batch of items."""
    return [
        ItemProbeResult(
            p.item_id,
            probe_file(p.image) if p.image else None,
            probe_file(p.mask) if p.mask else None,
        )
        for p in probes
    ]


def batches(probes: Sequence[ItemProbe], size: int = BATCH_SIZE) -> list[list[ItemProbe]]:
    return [list(probes[i : i + size]) for i in range(0, len(probes), size)]
