"""The converter's scan/convert stages for Open mode and Save as NIfTI.

Worker units. Builtin plugins are reached only through `app/tasks/`.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any


def is_dicom_image(path: Path, root: Path | None = None) -> bool:
    from plugins.dicom.scan import is_dicom_image as recognize

    return recognize(path, root)


def source_folders(root: Path) -> Iterator[tuple[Path, list[Path]]]:
    """Read-only streamed traversal."""
    from plugins.dicom.files import folders

    return folders(root)


def local_source_file(root: Path, path: Path) -> bool:
    from plugins.dicom.files import local_file

    return local_file(root, path)


def series_fingerprint(root: str, rels: list[str]) -> str:
    """Cache identity covers every guarded member and the native reader."""
    from plugins.dicom import commits, convert, pipeline, scan

    if not rels:
        raise ValueError("DICOM series has no members")
    code = []
    for module in (convert, scan):
        assert module.__file__ is not None
        code.append(commits.file_digest(Path(module.__file__)))
    reader = {
        "versions": commits.reader_versions(pipeline.VERSION),
        "code": code,
    }
    digest = hashlib.sha256(json.dumps(reader, sort_keys=True).encode())
    for rel in sorted(rels):
        member = commits.file_digest(Path(root) / rel, Path(root))
        digest.update(json.dumps([rel, member], sort_keys=True).encode())
    return f"series-{digest.hexdigest()}"


def probe_series(
    root: str, rels: list[str], *, cancelled: Callable[[], bool] | None = None
) -> list[dict[str, Any]]:
    """DICOM files → one record per series (headers only): files, modality, geometry."""
    from plugins.dicom import scan
    from plugins.text import split_multi_value, value_to_text

    groups: dict[tuple[str, str], list[tuple[str, Any]]] = {}
    errors: list[dict[str, Any]] = []
    for rel in rels:
        if cancelled is not None and cancelled():
            raise InterruptedError("Open DICOM header reading cancelled")
        try:
            ds = scan.read_header(Path(root) / rel, Path(root))
        except Exception as exc:
            errors.append({"rel": rel, "format": "dicom", "error": f"{type(exc).__name__}: {exc}"})
            continue
        uid = value_to_text(getattr(ds, "SeriesInstanceUID", "")) or rel
        groups.setdefault((str(Path(rel).parent), uid), []).append((rel, ds))
    out: list[dict[str, Any]] = []
    for (_, uid), members in sorted(groups.items()):
        members.sort(key=lambda m: m[0])
        rel0, ds = members[0]
        sop = value_to_text(getattr(ds, "SOPClassUID", ""))
        rec: dict[str, Any] = {
            "rel": rel0,
            "format": "dicom",
            "files": [m[0] for m in members],
            "series_uid": uid,
            "modality": value_to_text(getattr(ds, "Modality", "")).upper() or None,
            "description": value_to_text(getattr(ds, "SeriesDescription", "")),
            "window": _window(ds),
        }
        identity = scan.identity_codes([member for _, member in members])
        if identity:
            rec["error"] = "DICOM identity is not usable: " + "; ".join(identity)
            out.append(rec)
            continue
        if sop == scan.DICOM_SEG_SOP_CLASS_UID:
            rec["error"] = "DICOM SEG is not supported yet"
        frames = int(value_to_text(getattr(ds, "NumberOfFrames", "")) or 0)
        n = frames if len(members) == 1 and frames > 1 else len(members)
        sp = split_multi_value(getattr(ds, "PixelSpacing", ""))
        try:
            thick = float(value_to_text(getattr(ds, "SliceThickness", "")) or 1.0)
            spacing = [float(sp[1]), float(sp[0]), thick] if len(sp) > 1 else [1.0, 1.0, thick]
        except ValueError:
            spacing = [1.0, 1.0, 1.0]
        rec["geometry"] = {
            "shape": [int(getattr(ds, "Columns", 0) or 0), int(getattr(ds, "Rows", 0) or 0), n],
            "spacing": spacing,
            "dtype": "int16",
            "orientation": None,
            "affine": None,
        }
        out.append(rec)
    return out + errors


def _window(ds: Any) -> list[float] | None:
    """`[width, center]` from the header (first value of each), or None."""
    from plugins.text import split_multi_value

    try:
        c = split_multi_value(getattr(ds, "WindowCenter", ""))
        w = split_multi_value(getattr(ds, "WindowWidth", ""))
        width, center = float(w[0]), float(c[0])
    except (ValueError, IndexError, TypeError):
        return None
    return [width, center] if width > 0 else None


def dicom_tags(root: str, rel: str) -> dict[str, Any]:
    """Worker: the DICOM JSON model of one file's header (no PixelData)."""
    from plugins.dicom import scan, sidecar

    return sidecar.to_json_model(scan.read_header(Path(root) / rel, Path(root)))


def convert_series(
    root: str,
    files: list[str],
    dst: str,
    memory_mb: int | None = None,
    *,
    expected_fingerprint: str | None = None,
) -> str | None:
    """Worker: one series (or one file) → NIfTI at `dst`. None, else the error."""
    from plugins.dicom import convert, resources, scan

    try:
        paths = tuple(Path(root) / f for f in files)
        if Path(dst).exists():
            return None

        def verify_inputs() -> None:
            if (
                expected_fingerprint is not None
                and series_fingerprint(root, files) != expected_fingerprint
            ):
                raise ValueError("DICOM series changed during conversion; reopen the source")

        verify_inputs()
        headers = [scan.image_info(path, Path(root)) for path in paths]
        if any(header is None for header in headers):
            return "The series contains an unreadable or non-image DICOM member"
        facts = [header[0] for header in headers if header is not None]
        order = scan._ipp_order(list(paths), facts)
        ordered = tuple(paths[index] for index in order)
        first = facts[0]
        frames = int(getattr(first, "NumberOfFrames", 1) or 1) if len(paths) == 1 else len(paths)
        resources.require_memory(
            {"dim_x": first.Columns, "dim_y": first.Rows, "num_slices": frames}, first, memory_mb
        )
        series = scan.Series(paths[0].parent, "open", ordered, source_root=Path(root))
        convert.write_nifti(series, Path(dst), before_publish=verify_inputs)
    except Exception as exc:
        if Path(dst).is_file():
            return None  # another writer finished the same volume first
        return f"{type(exc).__name__}: {exc}"
    return None


def write_sidecar(src: str, dst: str, anonymize: bool, case_id: str) -> str | None:
    """Worker: the DICOM JSON sidecar of one file, optionally anonymized."""
    from plugins.dicom import scan, sidecar

    try:
        ds = scan.read_header(Path(src))
        if anonymize:
            ds = sidecar.anonymize_dataset(ds, case_id, salt=case_id)
        sidecar.write_sidecar(ds, Path(dst))
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


def link_new(tmp: Path, dest_dir: Path, stem: str, suffix: str) -> Path:
    """Publish `tmp` under a new name (`-1`, `-2` … appended)."""
    n = 0
    while True:
        name = f"{stem}{suffix}" if n == 0 else f"{stem}-{n}{suffix}"
        target = dest_dir / name
        try:
            os.link(tmp, target)  # atomic no-clobber
        except FileExistsError:
            n += 1
            continue
        tmp.unlink()
        return target
