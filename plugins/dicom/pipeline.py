"""The converter pipeline: scan → select (analyzers) → identity → convert → emit (DCM-01..10).

Used by the task entry (`task.py`, in the app) and by the standalone CLI (`cli.py`, DCM-09).
Sources are opened read-only (R1); volumes and sidecars go only into the append-only
`dataset/` (ADR-0014); rows, diagnostics and the summary go into the run's own folder.
"""

from __future__ import annotations

import fnmatch
import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from plugins.analyzers import phase as phase_rules
from plugins.analyzers import readiness as readiness_rules
from plugins.analyzers import target as target_rules
from plugins.dicom import convert, rows, scan, sidecar
from plugins.dicom.identity import Identity
from plugins.text import value_to_text

VERSION = "1.1.0"
# DCM-13 / ADR-0020: `metadata.jsonl` holds contract-v1 fields and DICOM facts only. Guesses,
# selection results and human decisions are analyzer or curation layers, never row fields.
STUDY_FIELDS = frozenset(
    {"target_match_level", "output_role", "include_guess", "exclude_reason",
     "analysis_readiness", "group", "notes"}
)  # fmt: skip
STUDY_PREFIXES = ("phase_guess", "curated_", "target_match")


def clean_row(row: dict[str, Any]) -> dict[str, Any]:
    """A converter row without study logic (also strips legacy rows carried over by DCM-07)."""
    return {
        k: v for k, v in row.items() if k not in STUDY_FIELDS and not k.startswith(STUDY_PREFIXES)
    }


@dataclass
class Settings:
    target_profile: str = "generic"
    convert_primary: bool = True
    convert_secondary: bool = True
    convert_excluded: bool = False
    skip_unsafe_geometry: bool = False
    mixed_folder_policy: str = "split"
    patient_pattern: str = "*"
    patient_limit: int | None = None
    include_modality_prefix: bool = True
    sidecars: bool = True
    anonymize: str = "none"  # none | basic (DCM-05)
    phase_vocabulary: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Settings:
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class Series:
    """One discovered series with its header row, annotations and outcome."""

    series: scan.Series
    header: Any
    row: dict[str, Any]
    annotations: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Result:
    rows: list[dict[str, Any]]
    annotations: list[dict[str, Any]]
    diagnostics: list[scan.Diagnostic]
    counts: dict[str, int]
    storage: dict[str, int]
    outputs: list[dict[str, Any]]
    plan: list[dict[str, Any]] = field(default_factory=list)  # one row per series (DCM-06)


Progress = Callable[[str, str, list[dict[str, Any]], str], None]


def patient_dirs(source: Path, pattern: str, limit: int | None) -> list[Path]:
    """The source itself when it holds DICOM directly (or is one file), else its subfolders."""
    if source.is_file():
        return [source]
    if scan.has_dicom_files(source):
        return [source]
    dirs = sorted(
        (p for p in source.iterdir() if p.is_dir() and fnmatch.fnmatch(p.name, pattern)),
        key=lambda p: p.name.lower(),
    )
    if not dirs and scan.candidate_dirs(source):
        dirs = [source]
    return dirs[:limit] if limit else dirs


def _key(row: dict[str, Any]) -> str:
    return f"{row.get('case_identity_key', '')}|{row.get('series_uid', '')}"


def _estimate(ds: Any, s: scan.Series, row: dict[str, Any]) -> tuple[int, int]:
    """(source bytes, estimated .nii.gz bytes) as the legacy dry run did (DCM-06)."""
    src = 0
    for p in s.files:
        try:
            src += p.stat().st_size
        except OSError:
            continue
    try:
        voxels = (
            int(row.get("dim_x") or 0)
            * int(row.get("dim_y") or 0)
            * int(row.get("num_slices") or 0)
        )
    except ValueError:
        voxels = 0
    bits = int(value_to_text(getattr(ds, "BitsAllocated", "")) or 16)
    raw = voxels * max(1, math.ceil(bits / 8))
    return src, int(raw * 0.45) if raw else src


def decide_conversion(
    row: dict[str, Any], role: str, role_reason: str, settings: Settings
) -> tuple[bool, str]:
    """DCM-06 convert / skip decision for one series: (planned, skip reason or "")."""
    planned = {
        "PRIMARY": settings.convert_primary,
        "SECONDARY": settings.convert_secondary,
    }.get(role, settings.convert_excluded)
    if planned and settings.skip_unsafe_geometry and readiness_rules.has_unsafe_geometry(row):
        return False, "unsafe_geometry"
    if not planned:
        return False, role_reason if role == "EXCLUDED" else f"{role.lower()}_disabled"
    return True, ""


def run(
    source: Path,
    settings: Settings,
    identity: Identity,
    *,
    nifti_dir: Path,
    sidecar_dir: Path,
    ref_rel: str,
    ref_alias: str,
    salt: str,
    previous: list[dict[str, Any]],
    dry_run: bool,
    progress: Progress | None = None,
    cancelled: Callable[[], bool] = lambda: False,
    on_total: Callable[[int], None] | None = None,
) -> Result:
    diagnostics: list[scan.Diagnostic] = []
    profile = target_rules.profile(settings.target_profile)
    anonymize = settings.anonymize == "basic"
    found: list[Series] = []
    for pdir in patient_dirs(source, settings.patient_pattern, settings.patient_limit):
        folder = pdir.name if pdir.is_dir() else pdir.parent.name
        per_folder: list[Series] = []
        for s in scan.discover(pdir, diagnostics):
            try:
                ds = scan.first_header(s)
            except Exception as exc:
                diagnostics.append(
                    scan.Diagnostic(
                        "ERROR",
                        "series_header",
                        "SERIES_HEADER_READ_FAILED",
                        str(exc),
                        str(s.dicom_dir),
                        s.series_id,
                    )
                )
                continue
            sop = value_to_text(getattr(ds, "SOPClassUID", ""))
            if sop == scan.DICOM_SEG_SOP_CLASS_UID:
                diagnostics.append(
                    scan.Diagnostic(
                        "INFO",
                        "series_header",
                        "DICOM_SEG_NOT_SUPPORTED",
                        "DICOM SEG is not supported yet (DCM-11)",
                        str(s.dicom_dir),
                        s.series_id,
                    )
                )
                continue
            insp = scan.inspect(s, ds, diagnostics)
            per_folder.append(Series(s, ds, rows.header_row(ds, s, folder, insp)))
        patients = {r.row["patient_id"] for r in per_folder}
        if settings.mixed_folder_policy == "fail" and len(patients) > 1:
            diagnostics.append(
                scan.Diagnostic(
                    "ERROR",
                    "case_identity",
                    "MIXED_FOLDER",
                    f"{folder}: {len(patients)} PatientIDs",
                    str(pdir),
                )
            )
            continue
        found += per_folder
    if on_total is not None:
        on_total(len(found))

    by_case: dict[str, list[Series]] = {}
    for f in found:
        raw_key = f.row["patient_id"]
        key = sidecar.hash_identity_key(raw_key, salt) if anonymize else raw_key
        f.row["case_identity_key"] = key
        by_case.setdefault(key, []).append(f)

    prev_by_key = {_key(r): r for r in previous}
    counts = {
        "series": len(found),
        "selected": 0,
        "converted": 0,
        "already_converted": 0,
        "skipped": 0,
        "failed": 0,
    }
    storage = {"source_bytes": 0, "nifti_gz_estimated_bytes": 0}
    outputs: list[dict[str, Any]] = []
    annotations: list[dict[str, Any]] = []
    plan: list[dict[str, Any]] = []
    for key, group in sorted(by_case.items()):
        case_id = identity.case_id(key)
        rows.apply_scan_timing([g.row for g in group])
        for g in sorted(group, key=lambda g: rows.series_sort_key(g.row)):
            row = g.row
            row["case_id"] = case_id
            row["scan_idx"] = identity.scan_idx(key, row["series_uid"])
            level, level_ev = target_rules.match(row, profile)
            role, role_reason = readiness_rules.output_role(row, level)
            value, conf, ev, extras = phase_rules.guess(row, settings.phase_vocabulary)
            row.update({k: ("" if v is None else str(v)) for k, v in extras.items()})
            row["target_match_level"] = level
            row["output_role"] = role
            row["include_guess"] = {"PRIMARY": "include", "SECONDARY": "secondary"}.get(
                role, "exclude"
            )
            row["exclude_reason"] = role_reason if role == "EXCLUDED" else ""
            planned, skip_reason = decide_conversion(row, role, role_reason, settings)
            if skip_reason:
                row["skip_reason"] = skip_reason
            row["planned_conversion"] = planned
            iid = f"{case_id}.{row['scan_idx']}.complete.-"
            g.annotations = [
                {
                    "item_id": iid,
                    "field": "phase",
                    "value": value,
                    "confidence": conf,
                    "evidence": ev,
                    "rules_version": phase_rules.RULES_VERSION,
                },
                {
                    "item_id": iid,
                    "field": "target_match",
                    "value": level,
                    "confidence": target_rules.CONFIDENCE[level],
                    "evidence": level_ev,
                    "rules_version": target_rules.RULES_VERSION,
                },
                {
                    "item_id": iid,
                    "field": "output_role",
                    "value": role,
                    "confidence": readiness_rules.ROLE_CONFIDENCE[role],
                    "evidence": role_reason,
                    "rules_version": readiness_rules.RULES_VERSION,
                },
            ]
            parts = (
                [row["scan_idx"], row["modality"]]
                if settings.include_modality_prefix and row["modality"]
                else [row["scan_idx"]]
            )
            filename = "_".join([*parts, case_id]) + "_0000.nii.gz"
            row["filename"] = filename
            row["relative_path"] = f"{ref_rel}/nifti/{filename}"
            est = 0
            if planned:
                counts["selected"] += 1
                src, est = _estimate(g.header, g.series, row)
                storage["source_bytes"] += src
                storage["nifti_gz_estimated_bytes"] += est
            plan.append(
                {
                    "case_id": case_id,
                    "scan_idx": row["scan_idx"],
                    "patient": "" if anonymize else str(row.get("patient_id") or ""),
                    "description": str(row.get("series_description") or ""),
                    "modality": str(row.get("modality") or ""),
                    "n_files": len(g.series.files),
                    "action": "convert" if planned else "skip",
                    "reason": "" if planned else str(row.get("skip_reason") or ""),
                    "bytes": est,
                }
            )
            if cancelled():
                break
            item_outputs: list[dict[str, Any]] = []
            status, message = "skipped", str(row.get("skip_reason", ""))
            if planned and dry_run:
                status = row["status"] = "would_convert"
            elif planned:
                out = nifti_dir / filename
                prev = prev_by_key.get(_key(row))
                if out.is_file():
                    status = row["status"] = "already_converted"  # DCM-07: never rewritten
                    if prev is not None:
                        for k in (
                            "dim_x",
                            "dim_y",
                            "dim_z",
                            "spacing_x",
                            "spacing_y",
                            "spacing_z",
                            "origin_x",
                            "origin_y",
                            "origin_z",
                            "direction",
                            "pixel_type",
                            "num_slices",
                            "dicom_sidecar",
                        ):
                            if prev.get(k):
                                row[k] = prev[k]
                else:
                    try:
                        c = convert.write_nifti(g.series, out)
                    except Exception as exc:
                        status = row["status"] = "failed"
                        message = row["raw_metadata_error"] = f"{type(exc).__name__}: {exc}"
                        diagnostics.append(
                            scan.Diagnostic(
                                "ERROR",
                                "series_conversion",
                                "SERIES_CONVERSION_FAILED",
                                message,
                                str(g.series.dicom_dir),
                                g.series.series_id,
                            )
                        )
                    else:
                        rows.update_geometry(
                            row, c.size, c.spacing, c.origin, c.direction, c.pixel_type
                        )
                        status = row["status"] = "converted"
                        item_outputs.append({"kind": "image", "path": str(out)})
                        if settings.sidecars:
                            header = (
                                sidecar.anonymize_dataset(g.header, case_id, salt)
                                if anonymize
                                else g.header
                            )
                            side = sidecar_dir / f"{filename}.dicom.json"
                            if not side.exists():
                                sha = sidecar.write_sidecar(header, side)
                                item_outputs.append(
                                    {"kind": "sidecar", "path": str(side), "sha256": sha}
                                )
                            row["dicom_sidecar"] = (
                                f"{ref_alias}:{ref_rel}/sidecars/{filename}.dicom.json"
                            )
            else:
                row["status"] = "skipped"
            if status in counts:
                counts[status] += 1
            ready, reasons = readiness_rules.readiness(row)
            row["analysis_readiness"] = ready
            g.annotations.append(
                {
                    "item_id": iid,
                    "field": "readiness",
                    "value": ready,
                    "confidence": "high" if ready in ("ready", "unsuitable") else "medium",
                    "evidence": ", ".join(reasons) or "no issues",
                    "rules_version": readiness_rules.RULES_VERSION,
                }
            )
            if anonymize:
                sidecar.anonymize_row(row, case_id, salt)
            annotations += g.annotations
            outputs += item_outputs
            if progress is not None:
                progress(
                    iid,
                    "failed" if status == "failed" else "ok" if planned else "skipped",
                    item_outputs,
                    message,
                )
    current = [g.row for g in found]
    merged = {_key(r): r for r in previous}
    merged.update({_key(r): r for r in current})  # DCM-07: the full current row set
    rows_out = [clean_row(r) for r in merged.values()]
    return Result(rows_out, annotations, diagnostics, counts, storage, outputs, plan)


def write_jsonl(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for r in items:
            fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    tmp.replace(path)
