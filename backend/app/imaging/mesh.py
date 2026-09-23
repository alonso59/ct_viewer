"""Surface meshes for mask labels (API-25, VW-09, BE-06, BE-12).

`build` runs in a job worker: it reads the mask `rb` (R1, BE-03), runs marching cubes on one
label (cropped to its bounding box), maps vertices to world mm with the NIfTI affine and writes
a gzip MZ3 under the project `cache/` only (PRJ-10), atomically. `ensure_mesh` (API process)
returns the cached file or the (deduped) `mesh` job that builds it.

MZ3 (NiiVue native): little-endian header `<HHIII` = magic 23117, attr 3 (faces + verts),
nface, nvert, nskip 0; then int32 faces, then float32 vertices; the whole file gzipped.
"""

from __future__ import annotations

import gzip
import struct
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
from numpy.typing import NDArray

from app.core.errors import NotFound, ValidationProblem
from app.core.paths import open_source
from app.imaging.header import VolumeFormat
from app.imaging.npy_convert import CACHE_DIR, atomic_write_cache
from app.jobs.manager import JobManager
from app.jobs.types import TERMINAL, JobInfo, JobSpec, WorkUnit

MZ3_MAGIC = 23117
MZ3_ATTR_FACES_VERTS = 3
MZ3_HEADER = struct.Struct("<HHIII")
SMOOTH_VALUES: frozenset[int] = frozenset({0, 1})
SMOOTH_SIGMA = 1.0  # voxels
LABEL_ABSENT = "label-absent"


class MeshBuildError(Exception):
    """A worker-reported build failure; the job fails with this message."""


def cache_key(mask_fp: str, label: int, smooth: int) -> str:
    return f"{mask_fp}_{label}_{smooth}"


def cache_path(project_dir: Path, mask_fp: str, label: int, smooth: int) -> Path:
    return project_dir / CACHE_DIR / "meshes" / f"{cache_key(mask_fp, label, smooth)}.mz3"


def check_params(label: int, smooth: int) -> None:
    if smooth not in SMOOTH_VALUES:
        raise ValidationProblem(
            "smooth must be 0 or 1",
            errors=[{"loc": ["query", "smooth"], "msg": "must be 0 or 1", "type": "enum"}],
        )
    if label < 1:
        raise ValidationProblem(
            "label must be a positive integer",
            errors=[{"loc": ["path", "label"], "msg": "must be >= 1", "type": "greater_than"}],
        )


# --- worker side -------------------------------------------------------------------------


def encode_mz3(faces: NDArray[Any], verts: NDArray[Any]) -> bytes:
    f = np.ascontiguousarray(faces, dtype="<i4")
    v = np.ascontiguousarray(verts, dtype="<f4")
    header = MZ3_HEADER.pack(MZ3_MAGIC, MZ3_ATTR_FACES_VERTS, len(f), len(v), 0)
    return gzip.compress(header + f.tobytes() + v.tobytes(), compresslevel=6, mtime=0)


def decode_mz3(data: bytes) -> tuple[NDArray[np.int32], NDArray[np.float32]]:
    """Inverse of `encode_mz3` (faces + verts only; tests and tooling)."""
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    magic, attr, nface, nvert, nskip = MZ3_HEADER.unpack_from(data)
    if magic != MZ3_MAGIC or attr != MZ3_ATTR_FACES_VERTS:
        raise ValueError(f"not a faces+verts MZ3 (magic={magic}, attr={attr})")
    off = MZ3_HEADER.size + nskip
    faces = np.frombuffer(data, dtype="<i4", count=nface * 3, offset=off).reshape(nface, 3)
    off += nface * 12
    verts = np.frombuffer(data, dtype="<f4", count=nvert * 3, offset=off).reshape(nvert, 3)
    return faces.astype(np.int32), verts.astype(np.float32)


def _read_mask(src: Path, spacing: Sequence[float] | None) -> tuple[NDArray[Any], NDArray[Any]]:
    """(voxels, 4x4 affine). `.npy` gets affine = diag(spacing) like the npy→NIfTI cache."""
    with open_source(src) as fh:
        if src.name.lower().endswith(".npy"):
            arr: Any = np.load(fh, allow_pickle=False)
            sp = [float(s) for s in (spacing or [])][:3]
            if len(sp) != 3 or not all(np.isfinite(s) and s > 0 for s in sp):
                sp = [1.0, 1.0, 1.0]
            return np.asarray(arr), np.diag([*sp, 1.0])
        raw = fh.read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    img: Any
    try:
        img = nib.Nifti1Image.from_bytes(raw)
    except Exception:
        img = nib.Nifti2Image.from_bytes(raw)
    return np.asanyarray(img.dataobj), np.asarray(img.affine, dtype=np.float64)


def _label_mask(arr: NDArray[Any], label: int) -> NDArray[np.bool_]:
    if arr.ndim == 4 and arr.shape[3] == 1:
        arr = arr[..., 0]
    if arr.ndim != 3:
        raise ValueError(f"expected a 3D mask, got shape {tuple(arr.shape)}")
    if np.issubdtype(arr.dtype, np.floating):
        return np.asarray(np.rint(arr) == label)
    return np.asarray(arr == label)


def surface(
    binary: NDArray[np.bool_], affine: NDArray[Any], smooth: int
) -> tuple[NDArray[np.int32], NDArray[np.float32]] | None:
    """Closed outward-facing surface of `binary` in world mm, or None if the label is empty."""
    from skimage.filters import gaussian
    from skimage.measure import marching_cubes

    axes = [np.flatnonzero(binary.any(axis=tuple(a for a in range(3) if a != k))) for k in range(3)]
    if any(len(ix) == 0 for ix in axes):
        return None
    lo = np.array([int(ix[0]) for ix in axes])
    hi = np.array([int(ix[-1]) for ix in axes])
    pad = 1 + 2 * smooth  # zero border closes the surface; room for the Gaussian tail
    sub = binary[lo[0] : hi[0] + 1, lo[1] : hi[1] + 1, lo[2] : hi[2] + 1]
    field = np.pad(sub.astype(np.float32), pad)
    verts: Any = None
    faces: Any = None
    if smooth:
        smoothed = gaussian(
            field, sigma=SMOOTH_SIGMA, mode="constant", cval=0.0, preserve_range=True
        )
        if float(smoothed.max()) > 0.5:
            verts, faces, _, _ = marching_cubes(smoothed, level=0.5)
    if verts is None:  # unsmoothed, or smoothing erased a thin structure
        verts, faces, _, _ = marching_cubes(field, level=0.5)
    ijk = verts.astype(np.float64) + (lo - pad)
    world = ijk @ affine[:3, :3].T + affine[:3, 3]
    faces = np.asarray(faces, dtype=np.int32)
    # skimage's winding is inward in index space; a positive-determinant affine keeps it
    # inward, a negative one mirrors it outward. Flip so normals always point outward.
    if np.linalg.det(affine[:3, :3]) > 0:
        faces = faces[:, ::-1]
    return np.ascontiguousarray(faces), world.astype(np.float32)


def build(
    src: str, dst: str, label: int, smooth: int, spacing: Sequence[float] | None = None
) -> str | None:
    """Worker: mask label → gzip MZ3 at `dst` (under `cache/`). None on success, else error."""
    try:
        arr, affine = _read_mask(Path(src), spacing)
        binary = _label_mask(arr, int(label))
        del arr
        mesh = surface(binary, affine, 1 if smooth else 0)
        if mesh is None:
            return f"{LABEL_ABSENT}: label {label} is not present in the mask"
        faces, verts = mesh
        atomic_write_cache(Path(dst), encode_mz3(faces, verts))
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


# --- API process -------------------------------------------------------------------------

_inflight: dict[str, str] = {}  # cache path → mesh job_id


async def _on_result(result: Any) -> None:
    """`build` returns an error string instead of raising; turn it into a failed job."""
    if result is not None:
        raise MeshBuildError(str(result))


def ensure_mesh(
    jobs: JobManager,
    project_id: str,
    project_dir: Path,
    src: Path,
    mask_fp: str,
    label: int,
    smooth: int,
    *,
    fmt: VolumeFormat = "nifti",
    spacing: Sequence[float] | None = None,
) -> Path | JobInfo:
    """Cached mesh path, or the queued/running `mesh` job building it (one per cache key).

    A failed build is reported on the job (`status=failed`, `error="MeshBuildError: …"`).
    Once a job for this key has failed with `label-absent`, later calls raise NotFound;
    other failures are retried by the next call.
    """
    check_params(label, smooth)
    dst = cache_path(project_dir, mask_fp, label, smooth)
    if dst.is_file():
        return dst
    key = str(dst)
    job_id = _inflight.get(key)
    if job_id is not None:
        try:
            info = jobs.get(job_id)
        except NotFound:
            info = None
        if info is not None and info.status not in TERMINAL:
            return info
        _inflight.pop(key, None)
        if info is not None and info.status == "succeeded" and dst.is_file():
            return dst
        if info is not None and info.status == "failed" and LABEL_ABSENT in (info.error or ""):
            _inflight[key] = job_id  # remember the verdict for this content-addressed key
            raise NotFound(f"label {label} is not present in the mask")
    sp = [float(s) for s in spacing] if (fmt == "npy" and spacing is not None) else None
    info = jobs.submit(
        JobSpec(
            project_id=project_id,
            kind="mesh",
            units=[WorkUnit(build, (str(src), str(dst), int(label), int(smooth), sp))],
            on_result=_on_result,
            exclusive=False,
            ref=cache_key(mask_fp, label, smooth),
            meta={"label": label, "smooth": smooth},
        )
    )
    _inflight[key] = info.job_id
    return info
