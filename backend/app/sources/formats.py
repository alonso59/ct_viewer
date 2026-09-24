"""Accepted file formats (SRC-02, SOURCES.md §Formats). Headers and magic bytes only."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from app.core.paths import open_source

Kind = Literal["nifti", "dicom", "npy"]
REFUSED = {".npz": "NumPy archives (.npz) are not supported; save one array per .npy"}
SKIP_NAMES = {"metadata.jsonl", "phase.json", "voi_catalog.jsonl", "curation.csv", "source.json"}
DICOM_SEG_UID = "1.2.840.10008.5.1.4.1.1.66.4"
MAX_FILES = 200_000


def extension(name: str) -> str:
    low = name.lower()
    if low.endswith(".nii.gz"):
        return ".nii.gz"
    return Path(low).suffix or "(none)"


def _dicom_magic(path: Path) -> bool:
    try:
        with open_source(path) as fh:
            fh.seek(128)
            return fh.read(4) == b"DICM"
    except OSError:
        return False


def classify(path: Path) -> Kind | None:
    """`nifti` | `dicom` | `npy` for accepted files, None otherwise (never opens for writing)."""
    ext = extension(path.name)
    if ext in (".nii", ".nii.gz"):
        return "nifti"
    if ext == ".npy":
        return "npy"
    if ext == ".dcm" or (ext in ("(none)", ".ima") and _dicom_magic(path)):
        return "dicom"
    return None


def stem(name: str) -> str:
    """File name without `.nii.gz` / `.nii` / `.npy` / `.dcm`."""
    ext = extension(name)
    return name[: -len(ext)] if ext != "(none)" and name.lower().endswith(ext) else name


@dataclass
class Scan:
    """Accepted files under a root (sorted, relative POSIX paths) and ignored extensions."""

    root: Path
    files: dict[Kind, list[str]] = field(
        default_factory=lambda: {"nifti": [], "dicom": [], "npy": []}
    )
    ignored: Counter[str] = field(default_factory=Counter)
    refused: dict[str, str] = field(default_factory=dict)
    truncated: bool = False

    @property
    def n_accepted(self) -> int:
        return sum(len(v) for v in self.files.values())


def scan(root: Path, include: Iterable[str] | None = None) -> Scan:
    """Walk a (guarded) folder, or only `include` (relative names, SRC-05); skips hidden."""
    out = Scan(root)
    if include is not None:
        candidates = [root / r for r in include]
    else:
        candidates = []
        for p in sorted(root.rglob("*")):
            if any(part.startswith(".") for part in p.relative_to(root).parts):
                continue
            candidates.append(p)
            if len(candidates) >= MAX_FILES:
                out.truncated = True
                break
    for p in candidates:
        if not p.is_file() or p.name in SKIP_NAMES:
            continue
        rel = p.relative_to(root).as_posix()
        kind = classify(p)
        if kind is None:
            ext = extension(p.name)
            out.ignored[ext] += 1
            if ext in REFUSED:
                out.refused[ext] = REFUSED[ext]
            continue
        out.files[kind].append(rel)
    return out


def dicom_series_folders(s: Scan) -> list[str]:
    """Folders holding DICOM files (one or more series each)."""
    return sorted({str(Path(f).parent.as_posix()) for f in s.files["dicom"]})
