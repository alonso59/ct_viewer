"""`.npy` → NIfTI (IMP-10, SRC-12, BE-04, BE-12).

`convert` runs in a job worker: it reads the source `rb` (R1) and writes only under a
disposable `cache/` (project cache or `.scratch/open`, PRJ-10), atomically. `ensure_nifti`
(API process) dedupes concurrent conversions of the same source fingerprint.

Axis order (SOURCES.md §NumPy): `xyz` = `arr[i,j,k]` with i → x (nibabel); `zyx` = SimpleITK's
`GetArrayFromImage` order, transposed `(2,1,0)` before writing. Spacing is always x, y, z.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal, Protocol

import nibabel as nib
import numpy as np

from app.core.cache_budget import touch
from app.core.errors import ValidationProblem
from app.core.paths import open_source

CACHE_DIR = "cache"
AxisOrder = Literal["xyz", "zyx"]
AXIS_ORDERS: tuple[AxisOrder, ...] = ("xyz", "zyx")


class WorkerRunner(Protocol):
    async def run_in_worker(self, fn: Any, *args: Any) -> Any: ...


def cache_path(project_dir: Path, source_fp: str, axis_order: AxisOrder = "xyz") -> Path:
    suffix = "" if axis_order == "xyz" else f".{axis_order}"
    return project_dir / CACHE_DIR / "npy" / f"{source_fp}{suffix}.nii.gz"


def axis_order_of(value: object) -> AxisOrder | None:
    return value if value in AXIS_ORDERS else None


def decide_axis_order(
    shape: Sequence[int], declared: object = None, reference_shape: Sequence[int] | None = None
) -> AxisOrder | None:
    """SRC-12: an explicit order wins; else a reference image's shape decides; else None."""
    order = axis_order_of(declared)
    if order is not None:
        return order
    if reference_shape is None:
        return None
    same = tuple(shape) == tuple(reference_shape)
    rev = tuple(reversed(shape)) == tuple(reference_shape)
    if same != rev:
        return "xyz" if same else "zyx"
    return None  # both (a cube-like shape) or neither: ambiguous


def read_sidecar(npy_path: Path) -> dict[str, Any]:
    """`{name}.npy.json`: axis_order, spacing (x, y, z), affine, reference_ref (SRC-12)."""
    p = npy_path.with_name(npy_path.name + ".json")
    if not p.is_file():
        return {}
    try:
        with open_source(p) as fh:
            raw = json.loads(fh.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def nifti_name(npy_name: str) -> str:
    """`01_case_00023_L.npy` → `01_case_00023_L.nii.gz` (NiiVue picks the reader by extension)."""
    stem = npy_name[:-4] if npy_name.lower().endswith(".npy") else npy_name
    return f"{stem}.nii.gz"


def _check_cache_target(dst: Path) -> None:
    parts = dst.parent.parts
    if CACHE_DIR not in parts and ".scratch" not in parts:
        raise ValueError("conversion output must live under cache/ or .scratch/")


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


def to_nifti(
    arr: Any,
    spacing: Sequence[float],
    axis_order: AxisOrder = "xyz",
    affine: Sequence[Sequence[float]] | None = None,
) -> Any:
    """SRC-12 conversion: `zyx` is transposed (2,1,0); spacing is never permuted."""
    if arr.ndim != 3:
        raise ValueError(f"expected a 3D array, got shape {tuple(arr.shape)}")
    if arr.dtype == np.bool_:
        arr = arr.astype(np.uint8)
    if axis_order == "zyx":
        arr = np.transpose(arr, (2, 1, 0))
    sp = [float(s) for s in spacing][:3]
    if len(sp) != 3 or not all(np.isfinite(s) and s > 0 for s in sp):
        sp = [1.0, 1.0, 1.0]
    aff = np.asarray(affine, dtype=float) if affine is not None else np.diag([*sp, 1.0])
    if aff.shape != (4, 4):
        raise ValueError("affine must be 4x4")
    img = nib.Nifti1Image(np.ascontiguousarray(arr), aff)
    img.header.set_zooms(sp)
    img.header.set_sform(aff, code=1)
    img.header.set_qform(aff, code=1)
    return img


def convert(
    src: str,
    dst: str,
    spacing: Sequence[float],
    axis_order: AxisOrder = "xyz",
    affine: Sequence[Sequence[float]] | None = None,
) -> str | None:
    """Worker: `.npy` → gzipped NIfTI (affine: given, else diag(spacing)). None, else error."""
    try:
        with open_source(Path(src)) as fh:
            arr: Any = np.load(fh, allow_pickle=False)
        img = to_nifti(arr, spacing, axis_order, affine)
        data = gzip.compress(img.to_bytes(), compresslevel=6, mtime=0)
        atomic_write_cache(Path(dst), data)
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


_inflight: dict[str, asyncio.Future[str | None]] = {}


async def ensure_nifti(
    jobs: WorkerRunner,
    src: Path,
    dst: Path,
    spacing: Sequence[float],
    axis_order: AxisOrder = "xyz",
    affine: Sequence[Sequence[float]] | None = None,
) -> Path:
    """Return the cached NIfTI for `src`, converting once in a worker if needed (IMP-10)."""
    if dst.is_file():
        touch(dst)  # LRU use (CACHE_MAX_GB, AUD-A4-16)
        return dst
    key = str(dst)
    loop = asyncio.get_running_loop()
    fut = _inflight.get(key)
    if fut is None or fut.get_loop() is not loop:
        fut = asyncio.ensure_future(
            jobs.run_in_worker(
                convert,
                str(src),
                str(dst),
                [float(s) for s in spacing],
                axis_order,
                [list(map(float, r)) for r in affine] if affine is not None else None,
            )
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
