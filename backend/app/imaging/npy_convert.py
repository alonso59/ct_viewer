"""Legacy `.npy` → NIfTI cache (IMP-10, BE-04, BE-12).

`convert` runs in a job worker: it reads the source `rb` (R1) and writes only under the
project `cache/` (PRJ-10), atomically. `ensure_nifti` (API process) dedupes concurrent
conversions of the same source fingerprint.
"""

from __future__ import annotations

import asyncio
import gzip
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

import nibabel as nib
import numpy as np

from app.core.errors import ValidationProblem
from app.core.paths import open_source

CACHE_DIR = "cache"


class WorkerRunner(Protocol):
    async def run_in_worker(self, fn: Any, *args: Any) -> Any: ...


def cache_path(project_dir: Path, source_fp: str) -> Path:
    return project_dir / CACHE_DIR / "npy" / f"{source_fp}.nii.gz"


def nifti_name(npy_name: str) -> str:
    """`01_case_00023_L.npy` → `01_case_00023_L.nii.gz` (NiiVue picks the reader by extension)."""
    stem = npy_name[:-4] if npy_name.lower().endswith(".npy") else npy_name
    return f"{stem}.nii.gz"


def _check_cache_target(dst: Path) -> None:
    if CACHE_DIR not in dst.parent.parts:
        raise ValueError("conversion output must live under cache/")


def atomic_write_cache(dst: Path, data: bytes) -> None:
    """Temp file in the same dir + `os.replace`; refuses targets outside `cache/`."""
    _check_cache_target(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{dst.name}.", suffix=".tmp", dir=dst.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, dst)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def convert(src: str, dst: str, spacing: Sequence[float]) -> str | None:
    """Worker: `.npy` → gzipped NIfTI with affine = diag(spacing). None on success, else error."""
    try:
        with open_source(Path(src)) as fh:
            arr: Any = np.load(fh, allow_pickle=False)
        if arr.ndim != 3:
            return f"expected a 3D array, got shape {tuple(arr.shape)}"
        if arr.dtype == np.bool_:
            arr = arr.astype(np.uint8)
        sp = [float(s) for s in spacing][:3]
        if len(sp) != 3 or not all(np.isfinite(s) and s > 0 for s in sp):
            sp = [1.0, 1.0, 1.0]
        affine = np.diag([*sp, 1.0])
        img = nib.Nifti1Image(np.ascontiguousarray(arr), affine)
        img.header.set_zooms(sp)
        img.header.set_sform(affine, code=1)
        img.header.set_qform(affine, code=1)
        data = gzip.compress(img.to_bytes(), compresslevel=6, mtime=0)
        atomic_write_cache(Path(dst), data)
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


_inflight: dict[str, asyncio.Future[str | None]] = {}


async def ensure_nifti(jobs: WorkerRunner, src: Path, dst: Path, spacing: Sequence[float]) -> Path:
    """Return the cached NIfTI for `src`, converting once in a worker if needed (IMP-10)."""
    if dst.is_file():
        return dst
    key = str(dst)
    loop = asyncio.get_running_loop()
    fut = _inflight.get(key)
    if fut is None or fut.get_loop() is not loop:
        fut = asyncio.ensure_future(
            jobs.run_in_worker(convert, str(src), str(dst), [float(s) for s in spacing])
        )
        _inflight[key] = fut

        def _done(_: object, k: str = key, f: asyncio.Future[str | None] = fut) -> None:
            if _inflight.get(k) is f:
                del _inflight[k]

        fut.add_done_callback(_done)
    error = await asyncio.shield(fut)
    if error is not None or not dst.is_file():
        raise ValidationProblem(f"Cannot convert .npy volume: {error or 'no output'}")
    return dst
