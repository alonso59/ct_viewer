"""`detect(path)` (SRC-01/02, API-19): candidate adapters for a folder or one file."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.errors import UnsupportedFormat
from app.sources import formats

Confidence = Literal["high", "medium", "low"]


class Candidate(BaseModel):
    adapter: str  # metadata-v1 | nifti-files | dicom.convert | open
    reason: str
    counts: dict[str, int]
    confidence: Confidence
    options: dict[str, Any] = Field(default_factory=dict)
    available: bool = True
    unavailable_reason: str | None = None


class DetectResult(BaseModel):
    path: str
    kind: Literal["file", "folder"]
    root: str  # the import root: the folder, or a single file's parent (SRC-05)
    candidates: list[Candidate]
    counts: dict[str, int]
    ignored: dict[str, int]  # extension → count (SRC-02)
    truncated: bool = False


def _counts(s: formats.Scan) -> dict[str, int]:
    return {
        "nifti": len(s.files["nifti"]),
        "dicom": len(s.files["dicom"]),
        "npy": len(s.files["npy"]),
        "ignored": sum(s.ignored.values()),
    }


def _refuse(path: Path, s: formats.Scan) -> UnsupportedFormat:
    ignored = ", ".join(f"{n} {ext}" for ext, n in s.ignored.most_common(5)) or "no files"
    extra = "; ".join(s.refused.values())
    detail = f"No accepted file (NIfTI, DICOM, NumPy) in {path.name or path}: {ignored}"
    return UnsupportedFormat(
        detail + (f". {extra}" if extra else ""), actions=["choose_another_path"]
    )


def detect(path: Path, *, dicom_available: bool) -> DetectResult:
    """`path` is already guarded (ALLOWED_DATA_ROOTS)."""
    if path.is_file():
        s = formats.scan(path.parent, [path.name])
        kind = formats.classify(path)
        counts = _counts(s)
        if kind is None:
            raise _refuse(path, s)
        cands: list[Candidate] = []
        if kind == "nifti":
            cands.append(
                Candidate(
                    adapter="nifti-files",
                    reason="One NIfTI file → a one-item project (SRC-05)",
                    counts=counts,
                    confidence="high",
                    options={"include": [path.name]},
                )
            )
        elif kind == "dicom":
            cands.append(_dicom(counts, dicom_available, single=True))
        cands.append(
            Candidate(
                adapter="open", reason="View it without a project", counts=counts, confidence="high"
            )
        )
        return DetectResult(
            path=str(path), kind="file", root=str(path.parent), candidates=cands, counts=counts,
            ignored=dict(s.ignored),
        )  # fmt: skip
    s = formats.scan(path)
    counts = _counts(s)
    has_meta = (path / "metadata.jsonl").is_file()
    if not has_meta and s.n_accepted == 0:
        raise _refuse(path, s)
    cands = []
    if has_meta:
        cands.append(
            Candidate(
                adapter="metadata-v1",
                reason="metadata.jsonl found (contract v1)",
                counts=counts,
                confidence="high",
            )
        )
    if counts["nifti"]:
        cands.append(
            Candidate(
                adapter="nifti-files",
                reason=f"{counts['nifti']} NIfTI files",
                counts=counts,
                confidence="low" if has_meta else "high",
            )
        )
    if counts["dicom"]:
        cands.append(_dicom(counts, dicom_available, single=False))
    if s.n_accepted:
        cands.append(
            Candidate(
                adapter="open",
                reason="View the files without a project",
                counts=counts,
                confidence="low",
            )
        )
    return DetectResult(
        path=str(path), kind="folder", root=str(path), candidates=cands, counts=counts,
        ignored=dict(s.ignored), truncated=s.truncated,
    )  # fmt: skip


def _dicom(counts: dict[str, int], available: bool, *, single: bool) -> Candidate:
    return Candidate(
        adapter="dicom.convert",
        reason=(
            "One DICOM file → converted to NIfTI (DCM-10)"
            if single
            else f"{counts['dicom']} DICOM files → converted to NIfTI with sidecars (DCM-*)"
        ),
        counts=counts,
        confidence="high",
        available=available,
        unavailable_reason=None if available else "the DICOM converter is not installed",
    )


def suggest_for(root: Path) -> tuple[str, list[str]]:
    """Cause + next actions when metadata.jsonl is missing (SRC-11)."""
    s = formats.scan(root)
    c = _counts(s)
    parts, actions = [], []
    if c["nifti"]:
        parts.append(f"{c['nifti']} NIfTI files found")
        actions.append("import_as:nifti-files")
    if c["dicom"]:
        parts.append(f"{c['dicom']} DICOM files found")
        actions.append("import_as:dicom.convert")
    if s.n_accepted:
        actions.append("open")
    found = "; ".join(parts) if parts else "no NIfTI or DICOM files either"
    return f"No metadata.jsonl under the root; {found}", actions or ["choose_another_path"]
