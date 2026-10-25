"""Mask sets (`mask_template`): a folder of binary NIfTI masks, one file per structure, read as
one label map whose values the import assigned (`VolumeRef.labels`, name → value).

`compose` runs in a job worker: it reads the members `rb` and writes only the disposable
`cache/maskset/`, atomically. Where structures overlap, the higher value wins.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np

from app.imaging.npy_convert import CACHE_DIR, WorkerRunner, atomic_write_cache, ensure_cached

CACHE_SUBDIR = "maskset"


def _is_nifti(p: Path) -> bool:
    name = p.name.lower()
    return not name.startswith(".") and name.endswith((".nii", ".nii.gz"))


def members(folder: Path) -> list[Path]:
    """The NIfTI files directly in the folder, sorted by name."""
    files = []
    for p in folder.iterdir():
        if not _is_nifti(p):
            continue
        if p.is_symlink():
            raise ValueError(f"mask set member {p.name} is a symbolic link")
        if p.is_file():
            files.append(p)
    return sorted(files)


def member_name(p: Path) -> str:
    name = p.name
    return name[: -len(".nii.gz")] if name.lower().endswith(".nii.gz") else name[: -len(".nii")]


def fingerprint(folder: Path) -> str:
    """Quick fingerprint of a set: member names, sizes and mtimes (no voxel read)."""
    files = members(folder)
    h = hashlib.sha256()
    for p in files:
        st = p.stat()
        h.update(f"{p.name}\0{st.st_size}\0{st.st_mtime_ns}\n".encode())
    return f"set{len(files)}-{h.hexdigest()[:32]}"


def cache_path(project_dir: Path, fp: str, labels: dict[str, int]) -> Path:
    key = hashlib.sha256(json.dumps([fp, sorted(labels.items())]).encode()).hexdigest()[:32]
    return project_dir / CACHE_DIR / CACHE_SUBDIR / f"{key}.nii.gz"


def compose(src: str, labels: dict[str, int], dst: str) -> str | None:
    """Worker: members → one label map (`uint8`, `uint16` above 255). None, else the error."""
    try:
        files = [p for p in members(Path(src)) if member_name(p) in labels]
        if not files:
            return "no member of the mask set has a label value"
        files.sort(key=lambda p: labels[member_name(p)])  # higher values written last win
        ref: Any = nib.load(files[0])
        shape = tuple(ref.shape[:3])
        dtype = np.uint8 if max(labels.values()) <= 255 else np.uint16
        out = np.zeros(shape, dtype=dtype)
        for p in files:
            img: Any = nib.load(p)
            if not np.allclose(img.affine, ref.affine, rtol=0, atol=1e-3):
                return f"{p.name}: affine differs from {files[0].name}"
            arr = np.asanyarray(img.dataobj)
            if tuple(arr.shape) != shape:
                return f"{p.name}: shape {tuple(arr.shape)} differs from {shape}"
            out[arr > 0] = labels[member_name(p)]
        composed = nib.Nifti1Image(out, ref.affine)
        data = gzip.compress(composed.to_bytes(), compresslevel=6, mtime=0)
        atomic_write_cache(Path(dst), data)
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


async def ensure_composed(
    jobs: WorkerRunner, project_dir: Path, folder: Path, fp: str, labels: dict[str, int]
) -> Path:
    """The cached label map of a mask set, composed once in a worker if needed."""
    dst = cache_path(project_dir, fp, labels)
    return await ensure_cached(
        jobs, dst, "compose mask set", compose, str(folder), labels, str(dst)
    )
