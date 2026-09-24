"""The converter's scan/convert stages for Open mode and Save as NIfTI (SRC-13/14, DCM-10).

Worker units (BE-12). Builtin plugins are reached only through `app/tasks/` (BE ARCHITECTURE).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def probe_series(root: str, rels: list[str]) -> list[dict[str, Any]]:
    """DICOM files → one record per series (headers only, R1): files, modality, geometry."""
    from plugins.dicom import scan
    from plugins.text import split_multi_value, value_to_text

    groups: dict[tuple[str, str], list[tuple[str, Any]]] = {}
    errors: list[dict[str, Any]] = []
    for rel in rels:
        try:
            ds = scan.read_header(Path(root) / rel)
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
        }
        if sop == scan.DICOM_SEG_SOP_CLASS_UID:
            rec["error"] = "DICOM SEG is not supported yet (DCM-11)"
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


def convert_series(root: str, files: list[str], dst: str) -> str | None:
    """Worker: one series (or one file) → NIfTI at `dst` (DCM-02/10). None, else the error."""
    from plugins.dicom import convert, scan

    try:
        paths = tuple(Path(root) / f for f in files)
        if Path(dst).exists():
            return None
        if len(paths) > 1:
            import SimpleITK as sitk

            names = sitk.ImageSeriesReader.GetGDCMSeriesFileNames(
                str(paths[0].parent), _uid(paths[0])
            )
            ordered = tuple(Path(n) for n in names if Path(n) in set(paths)) or paths
        else:
            ordered = paths
        convert.write_nifti(scan.Series(paths[0].parent, "open", ordered), Path(dst))
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


def _uid(path: Path) -> str:
    from plugins.dicom import scan
    from plugins.text import value_to_text

    return value_to_text(getattr(scan.read_header(path), "SeriesInstanceUID", ""))


def write_sidecar(src: str, dst: str, anonymize: bool, case_id: str) -> str | None:
    """Worker: the DICOM JSON sidecar of one file (DCM-04), optionally anonymized (DCM-05)."""
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
    """Publish `tmp` under a new name (`-1`, `-2` … appended; SRC-14): never overwrites."""
    n = 0
    while True:
        name = f"{stem}{suffix}" if n == 0 else f"{stem}-{n}{suffix}"
        target = dest_dir / name
        try:
            os.link(tmp, target)  # atomic, fails if the name exists
        except FileExistsError:
            n += 1
            continue
        tmp.unlink()
        return target
