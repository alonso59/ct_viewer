"""The converter pipeline: scan → select (analyzers) → identity → convert → emit.

Used by the task entry (`task.py`) and by the standalone CLI (`cli.py`).
Sources are opened read-only; volumes and sidecars go only into the append-only
`dataset/`; rows, diagnostics and the summary go into the run's own folder.
"""

from __future__ import annotations

import fnmatch
import json
import math
import os
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from plugins.analyzers import readiness as readiness_rules
from plugins.analyzers import target as target_rules
from plugins.dicom import commits, resources, rows, scan, sidecar
from plugins.dicom.identity import Identity
from plugins.text import contrast_delay, value_to_text

VERSION = "1.1.0"
# `metadata.jsonl` holds contract-v1 fields and DICOM facts only. Guesses,
# selection results and human decisions are analyzer or curation layers, never row fields.
STUDY_FIELDS = frozenset(
    {"target_match_level", "output_role", "include_guess", "exclude_reason",
     "analysis_readiness", "group", "notes"}
)  # fmt: skip
STUDY_PREFIXES = ("phase_guess", "curated_", "target_match")


def clean_row(row: dict[str, Any]) -> dict[str, Any]:
    """A converter row without study logic (also strips older rows carried over from `previous`)."""
    return {k: v for k, v in row.items() if k not in STUDY_FIELDS and not k.startswith(STUDY_PREFIXES)}


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
    anonymize: str = "none"  # none | basic

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
    plan: list[dict[str, Any]] = field(default_factory=list)  # one row per series
    resource_wait: dict[str, Any] | None = None
    analyzer_rows: list[dict[str, Any]] = field(default_factory=list)
    conversion_time: dict[str, Any] | None = None


Progress = Callable[[str, str, list[dict[str, Any]], str], None]
# (stage, done, total): `listing` folders → `reading` headers (files) → `planning` series
# → `converting` series (the item events); what the overlay shows while it waits
Stage = Callable[[str, int, int], None]
Timing = Callable[[dict[str, Any]], dict[str, Any]]


def timing_unit(g: Series, ordinal: int) -> dict[str, Any]:
    """Header facts only; the observer hashes the class before persisting measurements."""
    row, ds = g.row, g.header
    x, y, z = (int(row.get(k) or 0) for k in ("dim_x", "dim_y", "num_slices"))
    codec = value_to_text(getattr(getattr(ds, "file_meta", None), "TransferSyntaxUID", ""))
    category = {
        "codec": codec,
        "shape_xy": [x, y],
        "geometry": row.get("scan_type"),
        "geometry_status": row.get("geometry_status"),
        "depth_class": z.bit_length(),
        "multiframe": int(getattr(ds, "NumberOfFrames", 1) or 1) > 1,
        "pixels": [int(getattr(ds, k, 0) or 0) for k in ("BitsAllocated", "SamplesPerPixel", "PixelRepresentation")],
    }
    return {"id": str(ordinal), "class": category, "work": x * y * z if codec and min(x, y, z) > 0 else None}


def patient_dirs(source: Path, pattern: str, limit: int | None) -> list[Path]:
    """The source itself when it holds DICOM directly (or is one file), else its subfolders."""
    if source.is_file() or scan.has_dicom_files(source):
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
    """(source bytes, estimated .nii.gz bytes)."""
    src = s.source_bytes
    for p in s.files if not src else ():
        try:
            src += p.stat().st_size
        except OSError:
            continue
    try:
        voxels = int(row.get("dim_x") or 0) * int(row.get("dim_y") or 0) * int(row.get("num_slices") or 0)
    except ValueError:
        voxels = 0
    bits = int(value_to_text(getattr(ds, "BitsAllocated", "")) or 16)
    raw = voxels * max(1, math.ceil(bits / 8))
    return src, int(raw * 0.45) if raw else src


def decide_conversion(row: dict[str, Any], role: str, role_reason: str, settings: Settings) -> tuple[bool, str]:
    """Convert / skip decision for one series: (planned, skip reason or "")."""
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
    on_stage: Stage | None = None,
    cached_discover: Callable[[Path], list[scan.Series]] | None = None,
    cached_file_total: int = 0,
    checkpoint: Path | None = None,
    memory_mb: int | None = None,
    retry_item_ids: list[str] | None = None,
    on_timing: Timing | None = None,
) -> Result:
    retry_ids = set(retry_item_ids) if retry_item_ids is not None else None
    if retry_ids is not None and (not retry_ids or dry_run):
        raise ValueError("Retry requires a nonempty failed-series selection and a conversion run")
    diagnostics: list[scan.Diagnostic] = []
    profile = target_rules.profile(settings.target_profile)
    anonymize = settings.anonymize == "basic"
    stage: Stage = on_stage or (lambda _s, _d, _t: None)
    found: list[Series] = []
    # one walk up front, so header reading has a file total to show
    walked: list[tuple[Path, list[tuple[Path, list[Path]]] | None]] = []
    for pdir in patient_dirs(source, settings.patient_pattern, settings.patient_limit):
        walked.append((pdir, scan.candidate_files(pdir) if pdir.is_dir() and cached_discover is None else None))
        stage("listing", len(walked), 0)
    n_files = (
        cached_file_total
        if cached_discover is not None
        else sum(sum(len(f) for _, f in w) if w is not None else 1 for _, w in walked)
    )
    read = 0

    def tick(n: int) -> None:
        nonlocal read
        read += n
        stage("reading", read, n_files)

    stage("reading", 0, n_files)
    for pdir, files in walked:
        if cancelled():
            break
        folder = pdir.name if pdir.is_dir() else pdir.parent.name
        per_folder: list[Series] = []
        discovered = (
            cached_discover(pdir) if cached_discover is not None else scan.discover(pdir, diagnostics, files, tick)
        )
        if cached_discover is not None:
            tick(sum(len(s.files) for s in discovered))
        elif files is None:
            tick(1)
        for s in discovered:
            try:
                ds = scan.first_header(s)
            except Exception as exc:  # noqa: BLE001 - one bad series must not stop discovery
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
                        "DICOM SEG is not supported yet",
                        str(s.dicom_dir),
                        s.series_id,
                    )
                )
                continue
            insp = scan.inspect(s, ds, diagnostics)
            s = replace(s, headers=())  # inspected: only the first full header stays in memory
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
    selected_total = 0
    for candidate in found:
        level, _ = target_rules.match(candidate.row, profile)
        role, reason = readiness_rules.output_role(candidate.row, level)
        selected_total += int(decide_conversion(candidate.row, role, reason, settings)[0])
    if on_total is not None:
        on_total(len(found) if dry_run else selected_total)

    by_case: dict[str, list[Series]] = {}
    for f in found:
        raw_key = f.row["patient_id"]
        key = sidecar.hash_identity_key(raw_key, salt) if anonymize else raw_key
        f.row["case_identity_key"] = key
        by_case.setdefault(key, []).append(f)

    if checkpoint is not None and not dry_run:
        commits.restore_identity(checkpoint, identity)
        manifests = []
        for key, group in sorted(by_case.items()):
            identity.case_id(key)
            for g in sorted(group, key=lambda g: rows.series_sort_key(g.row)):
                identity.scan_idx(key, g.row["series_uid"])
                level, _ = target_rules.match(g.row, profile)
                role, reason = readiness_rules.output_role(g.row, level)
                if decide_conversion(g.row, role, reason, settings)[0]:
                    manifests.append(commits.input_manifest(g.series))
                    stage("verifying_inputs", len(manifests), selected_total)
        commits.pin_run(checkpoint, {**asdict(settings), "salt": salt}, VERSION, identity, manifests)

    if retry_ids is not None:
        available = set()
        for key, group in sorted(by_case.items()):
            for g in sorted(group, key=lambda g: rows.series_sort_key(g.row)):
                level, _ = target_rules.match(g.row, profile)
                role, reason = readiness_rules.output_role(g.row, level)
                if decide_conversion(g.row, role, reason, settings)[0]:
                    case = identity.case_id(key)
                    scan_idx = identity.scan_idx(key, g.row["series_uid"])
                    available.add(f"{case}.{scan_idx}.complete.-")
        if retry_ids - available:
            raise ValueError("Retry selection contains unavailable series; recover its original plan")

    timing_ids = {id(g): str(i) for i, g in enumerate(found)}
    conversion_time = None
    if on_timing is not None:
        units = []
        for i, g in enumerate(found):
            level, _ = target_rules.match(g.row, profile)
            role, reason = readiness_rules.output_role(g.row, level)
            if not decide_conversion(g.row, role, reason, settings)[0]:
                continue
            key = g.row["case_identity_key"]
            if retry_ids is not None:
                case, scan_idx = identity.case_id(key), identity.scan_idx(key, g.row["series_uid"])
                if f"{case}.{scan_idx}.complete.-" not in retry_ids:
                    continue
            units.append(timing_unit(g, i))
        conversion_time = on_timing({"t": "plan", "units": units})

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
    resource_wait = None
    analyzer_rows: list[dict[str, Any]] = []
    stage("planning" if dry_run else "converting", 0, len(found) if dry_run else selected_total)
    for key, group in sorted(by_case.items()):
        if resource_wait is not None:
            break
        case_id = identity.case_id(key)
        rows.apply_scan_timing([g.row for g in group])
        for g in sorted(group, key=lambda g: rows.series_sort_key(g.row)):
            row = g.row
            row["case_id"] = case_id
            row["scan_idx"] = identity.scan_idx(key, row["series_uid"])
            level, level_ev = target_rules.match(row, profile)
            role, role_reason = readiness_rules.output_role(row, level)
            delay, delay_source = contrast_delay(row)
            row["contrast_delay_seconds"] = "" if delay is None else str(delay)
            row["contrast_delay_source"] = delay_source
            row["target_match_level"] = level
            row["output_role"] = role
            row["include_guess"] = {"PRIMARY": "include", "SECONDARY": "secondary"}.get(role, "exclude")
            row["exclude_reason"] = role_reason if role == "EXCLUDED" else ""
            planned, skip_reason = decide_conversion(row, role, role_reason, settings)
            if skip_reason:
                row["skip_reason"] = skip_reason
            row["planned_conversion"] = planned
            iid = f"{case_id}.{row['scan_idx']}.complete.-"
            g.annotations = [
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
                side = sidecar_dir / f"{filename}.dicom.json"
                fresh_pixels = False
                started = time.monotonic()

                def before_pixels(row: dict[str, Any] = row, header: Any = g.header) -> None:
                    nonlocal fresh_pixels
                    resources.require_memory(row, header, memory_mb)
                    fresh_pixels = True

                try:
                    header = sidecar.anonymize_dataset(g.header, case_id, salt) if anonymize else g.header
                    publication = commits.commit_series(
                        g.series,
                        header,
                        out,
                        side,
                        settings={**asdict(settings), "salt": salt},
                        version=VERSION,
                        sidecars=settings.sidecars,
                        before_pixels=before_pixels,
                        verify_only=retry_ids is not None and iid not in retry_ids,
                    )
                    if publication is None:
                        status = row["status"] = "pending"
                    else:
                        converted, reused, item_outputs = publication
                        rows.update_geometry(
                            row,
                            converted.size,
                            converted.spacing,
                            converted.origin,
                            converted.direction,
                            converted.pixel_type,
                        )
                        status = row["status"] = "already_converted" if reused else "converted"
                        if settings.sidecars:
                            row["dicom_sidecar"] = f"{ref_alias}:{ref_rel}/sidecars/{filename}.dicom.json"
                except resources.MemoryBudgetExceeded as exc:
                    row["status"] = "waiting_for_resources"
                    resource_wait = exc.detail
                    stage("memory_budget", 0, selected_total)
                    break
                except Exception as exc:  # noqa: BLE001 - retain safe committed output on conflict
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
                if on_timing is not None and status != "pending":
                    conversion_time = on_timing(
                        {
                            "t": "unit",
                            "id": timing_ids[id(g)],
                            "committed": status in {"converted", "already_converted"},
                            "seconds": time.monotonic() - started if fresh_pixels and status == "converted" else None,
                        }
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
            if status in {"converted", "already_converted"}:
                analyzer_rows.append({**clean_row(row), "item_id": iid})
            if anonymize:
                sidecar.anonymize_row(row, case_id, salt)
            annotations += g.annotations
            outputs += item_outputs
            if dry_run:
                stage("planning", len(plan), len(found))
            else:
                stage("converting", counts["converted"] + counts["already_converted"], selected_total)
            if progress is not None and status != "pending":
                progress(
                    iid,
                    "failed" if status == "failed" else "ok" if planned else "skipped",
                    item_outputs,
                    message,
                )
    counts["selected"] = selected_total
    counts["pending"] = (
        0 if dry_run else max(0, selected_total - counts["converted"] - counts["already_converted"] - counts["failed"])
    )
    current = [g.row for g in found]
    merged = {_key(r): r for r in previous}
    merged.update({_key(r): r for r in current})  # current rows replace their previous versions
    rows_out = [clean_row(r) for r in merged.values()]
    if on_timing is not None:
        conversion_time = on_timing({"t": "finish"})
    return Result(
        rows_out,
        annotations,
        diagnostics,
        counts,
        storage,
        outputs,
        plan,
        resource_wait,
        analyzer_rows,
        conversion_time,
    )


def write_jsonl(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for r in items:
            fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
