"""The converter pipeline: plan (scan → select → identity) → execute (one unit per series) → assemble.

Used by the ct_viewer task entry (`plugins/dicom/task.py`) and by `rw-dicom` (`cli.py`).
Sources are opened read-only; volumes and sidecars go only into the append-only `dataset/`.
Planning keeps header facts and rows, not file lists, when an inventory supplies the series, so
memory follows the number of series. Outputs and rows do not depend on how many workers ran
or in which order units finished.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import math
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field, replace
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Protocol

from rw_dicom import commits, resources, rows, scan, sidecar
from rw_dicom.analyzers import readiness as readiness_rules
from rw_dicom.analyzers import target as target_rules
from rw_dicom.identity import Identity
from rw_dicom.text import contrast_delay, geometry_codes, value_to_text

VERSION = "1.1.0"  # the artifact contract; unchanged while outputs stay byte-identical
# `metadata.jsonl` holds contract-v1 fields and DICOM facts only. Guesses,
# selection results and human decisions are analyzer or curation layers, never row fields.
STUDY_FIELDS = frozenset(
    {"target_match_level", "output_role", "include_guess", "exclude_reason",
     "analysis_readiness", "group", "notes"}
)  # fmt: skip
STUDY_PREFIXES = ("phase_guess", "curated_", "target_match")


class MixedVersions(commits.CommitConflict):
    """New units would join committed units made by other readers; needs an acknowledgment."""


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
    patient_folders: list[str] | None = None
    include_modality_prefix: bool = True
    sidecars: bool = True
    anonymize: str = "none"  # none | basic

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Settings:
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)


class SeriesSource(Protocol):
    """A completed inventory: series per patient subtree, loaded again when a unit runs."""

    def discover(self, subtree: Path) -> Iterable[scan.Series]: ...

    def series(self, key: str) -> scan.Series: ...

    def members(self, key: str) -> list[Path]: ...


@dataclass
class Unit:
    """One discovered series: its row and header facts; members are loaded when it runs."""

    order: int  # discovery order (timing IDs, row order)
    key: str
    series_id: str
    dicom_dir: Path
    n_files: int
    source_bytes: int
    row: dict[str, Any]
    facts: dict[str, Any]
    annotations: list[dict[str, Any]] = field(default_factory=list)
    planned: bool = False
    iid: str = ""
    outputs: list[dict[str, Any]] = field(default_factory=list)
    message: str = ""


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
    units_by_versions: dict[str, dict[str, Any]] = field(default_factory=dict)


Progress = Callable[[str, str, list[dict[str, Any]], str], None]
# (stage, done, total): `listing` folders → `reading` headers (files) → `planning` series
# → `converting` series (the item events); what the overlay shows while it waits
Stage = Callable[[str, int, int], None]
Timing = Callable[[dict[str, Any]], dict[str, Any]]


def header_facts(ds: Any) -> dict[str, Any]:
    """What timing, storage and memory admission need from the first header, so it can be dropped."""
    return {
        "codec": value_to_text(getattr(getattr(ds, "file_meta", None), "TransferSyntaxUID", "")),
        "frames": int(getattr(ds, "NumberOfFrames", 1) or 1),
        "bits": int(value_to_text(getattr(ds, "BitsAllocated", "")) or 16),
        "samples": int(getattr(ds, "SamplesPerPixel", 1) or 1),
        "pixel_representation": int(getattr(ds, "PixelRepresentation", 0) or 0),
    }


def timing_unit(u: Unit) -> dict[str, Any]:
    """Header facts only; the observer hashes the class before persisting measurements."""
    row, facts = u.row, u.facts
    x, y, z = (int(row.get(k) or 0) for k in ("dim_x", "dim_y", "num_slices"))
    category = {
        "codec": facts["codec"],
        "shape_xy": [x, y],
        "geometry": row.get("scan_type"),
        "geometry_status": row.get("geometry_status"),
        "depth_class": z.bit_length(),
        "multiframe": facts["frames"] > 1,
        "pixels": [facts["bits"], facts["samples"], facts["pixel_representation"]],
    }
    return {
        "id": str(u.order),
        "class": category,
        "work": x * y * z if facts["codec"] and min(x, y, z) > 0 else None,
    }


def patient_dirs(source: Path, pattern: str, limit: int | None, folders: list[str] | None = None) -> list[Path]:
    """The source itself when it holds DICOM directly (or is one file), else its subfolders.

    An explicit `folders` list names the top-level folders and overrides pattern and limit.
    """
    if folders is not None:
        chosen = (source / name for name in set(folders))
        return sorted((p for p in chosen if p.is_dir() and not p.is_symlink()), key=lambda p: p.name.lower())
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


def _estimate(u: Unit) -> tuple[int, int]:
    """(source bytes, estimated .nii.gz bytes)."""
    try:
        voxels = int(u.row.get("dim_x") or 0) * int(u.row.get("dim_y") or 0) * int(u.row.get("num_slices") or 0)
    except ValueError:
        voxels = 0
    raw = voxels * max(1, math.ceil(u.facts["bits"] / 8))
    return u.source_bytes, int(raw * 0.45) if raw else u.source_bytes


def decide_conversion(row: dict[str, Any], role: str, role_reason: str, settings: Settings) -> tuple[bool, str]:
    """Convert / skip decision for one series: (planned, skip reason or "")."""
    if row.get("dicom_identity_codes"):
        return False, "invalid_dicom_identity: " + str(row["dicom_identity_codes"])
    planned = {
        "PRIMARY": settings.convert_primary,
        "SECONDARY": settings.convert_secondary,
    }.get(role, settings.convert_excluded)
    if planned and "MATRIX_SIZE_CONFLICT" in geometry_codes(row):
        return False, "matrix_size_conflict"  # slices of different sizes cannot be stacked
    if planned and settings.skip_unsafe_geometry and readiness_rules.has_unsafe_geometry(row):
        return False, "unsafe_geometry"
    if not planned:
        return False, role_reason if role == "EXCLUDED" else f"{role.lower()}_disabled"
    return True, ""


def failure_category(exc: BaseException) -> str:
    """input: the series itself; conflict: recorded state disagrees; resource: the host ran short."""
    if isinstance(exc, commits.CommitConflict):
        return "conflict"
    if isinstance(exc, MemoryError) or (isinstance(exc, OSError) and exc.errno in {12, 23, 24, 28, 122}):
        return "resource"
    return "input"


def convert_unit(job: dict[str, Any]) -> dict[str, Any]:
    """Run one unit; safe in a worker process (arguments and result are plain data)."""
    series: scan.Series = job["series"]
    fresh = False
    started = time.monotonic()

    def header() -> Any:
        ds = scan.first_header(series)
        return sidecar.anonymize_dataset(ds, job["case_id"], job["salt"]) if job["anonymize"] else ds

    def before_pixels() -> None:
        nonlocal fresh
        resources.require_memory(job["dims"], SimpleNamespace(**job["memory_facts"]), job["memory_mb"])
        fresh = True

    try:
        publication = commits.commit_series(
            series,
            header,
            job["out"],
            job["side"],
            settings=job["settings"],
            version=VERSION,
            sidecars=job["sidecars"],
            before_pixels=before_pixels,
            verify_only=job["verify_only"],
            expected_stat=job["stat"],
        )
    except resources.MemoryBudgetExceeded as exc:
        return {"status": "waiting_for_resources", "detail": exc.detail}
    except Exception as exc:  # noqa: BLE001 - one failed series never stops the others
        if "Zero-valued spacing" in str(exc):
            return {"status": "skipped", "reason": "zero_slice_spacing"}  # slices share one position
        return {"status": "failed", "error": f"{type(exc).__name__}: {exc}", "category": failure_category(exc)}
    if publication is None:
        return {"status": "pending"}
    return {
        "status": "already_converted" if publication.reused else "converted",
        "geometry": asdict(publication.converted),
        "outputs": publication.outputs,
        "versions": publication.versions,
        "fresh": fresh,
        "seconds": time.monotonic() - started,
    }


def _versions_key(versions: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(versions, sort_keys=True).encode()).hexdigest()[:16]


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
    inventory: SeriesSource | None = None,
    cached_discover: Callable[[Path], Iterable[scan.Series]] | None = None,
    cached_file_total: int = 0,
    checkpoint: Path | None = None,
    memory_mb: int | None = None,
    retry_item_ids: list[str] | None = None,
    on_timing: Timing | None = None,
    on_bytes: Callable[[dict[str, float]], None] | None = None,
    workers: int = 1,
    allow_mixed_versions: bool = False,
    max_failures: int | None = None,
) -> Result:
    retry_ids = set(retry_item_ids) if retry_item_ids is not None else None
    if retry_ids is not None and (not retry_ids or dry_run):
        raise ValueError("Retry requires a nonempty failed-series selection and a conversion run")
    if inventory is not None:
        cached_discover = inventory.discover
    diagnostics: list[scan.Diagnostic] = []
    profile = target_rules.profile(settings.target_profile)
    anonymize = settings.anonymize == "basic"
    stage: Stage = on_stage or (lambda _s, _d, _t: None)

    # ---- plan: discover and inspect, one series at a time ----
    found: list[Unit] = []
    retained: dict[str, scan.Series] = {}  # only without an inventory (small in-memory sources)
    walked: list[tuple[Path, list[tuple[Path, list[Path]]] | None]] = []
    for pdir in patient_dirs(source, settings.patient_pattern, settings.patient_limit, settings.patient_folders):
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
        per_folder: list[Unit] = []
        discovered: Iterable[scan.Series] = (
            cached_discover(pdir) if cached_discover is not None else scan.discover(pdir, diagnostics, files, tick)
        )
        if cached_discover is None and files is None:
            tick(1)
        for s in discovered:
            if cached_discover is not None:
                tick(len(s.files))
            try:
                ds = scan.first_header(s)
            except Exception as exc:  # noqa: BLE001 - one bad series must not stop discovery
                diagnostics.append(
                    scan.Diagnostic(
                        "ERROR", "series_header", "SERIES_HEADER_READ_FAILED", str(exc), str(s.dicom_dir), s.series_id
                    )
                )
                continue
            if value_to_text(getattr(ds, "SOPClassUID", "")) == scan.DICOM_SEG_SOP_CLASS_UID:
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
            key = s.key if inventory is not None and s.key else f"memory:{len(found) + len(per_folder)}"
            if key.startswith("memory:"):
                retained[key] = replace(s, headers=())
            source_bytes = s.source_bytes
            for p in s.files if not source_bytes else ():
                try:
                    source_bytes += p.stat().st_size
                except OSError:
                    continue
            per_folder.append(
                Unit(
                    order=len(found) + len(per_folder),
                    key=key,
                    series_id=s.series_id,
                    dicom_dir=s.dicom_dir,
                    n_files=len(s.files),
                    source_bytes=source_bytes,
                    row=rows.header_row(ds, s, folder, insp),
                    facts=header_facts(ds),
                )
            )
        patients = {u.row["patient_id"] for u in per_folder}
        if settings.mixed_folder_policy == "fail" and len(patients) > 1:
            diagnostics.append(
                scan.Diagnostic(
                    "ERROR", "case_identity", "MIXED_FOLDER", f"{folder}: {len(patients)} PatientIDs", str(pdir)
                )
            )
            for u in per_folder:
                retained.pop(u.key, None)
            continue
        found += per_folder
    folders_by_uid: dict[str, set[Path]] = {}
    for u in found:
        folders_by_uid.setdefault(u.series_id, set()).add(u.dicom_dir)
    for uid, folders in folders_by_uid.items():
        if len(folders) > 1:
            diagnostics.append(
                scan.Diagnostic(
                    "WARN",
                    "dicom_identity",
                    "SERIES_UID_REUSED_ACROSS_FOLDERS",
                    "The same series UID occurs in multiple folders; stacks remain separate. Verify the source grouping.",
                    series_id=uid,
                )
            )

    # ---- select and allocate identity (deterministic: case key, then series order) ----
    decisions: dict[int, tuple[str, Any, str, str, bool, str]] = {}
    for u in found:
        level, level_ev = target_rules.match(u.row, profile)
        role, reason = readiness_rules.output_role(u.row, level)
        planned, skip_reason = decide_conversion(u.row, role, reason, settings)
        decisions[u.order] = (level, level_ev, role, reason, planned, skip_reason)
    selected_total = sum(1 for d in decisions.values() if d[4])
    if on_total is not None:
        on_total(len(found) if dry_run else selected_total)
    if not dry_run and selected_total == 0 and any(u.row.get("dicom_identity_codes") for u in found):
        raise ValueError("No selected DICOM series has usable instance identities; review the dry-run diagnostics")
    by_case: dict[str, list[Unit]] = {}
    for u in found:
        raw_key = u.row["patient_id"]
        key = sidecar.hash_identity_key(raw_key, salt) if anonymize else raw_key
        u.row["case_identity_key"] = key
        by_case.setdefault(key, []).append(u)
    if checkpoint is not None and not dry_run:
        commits.restore_identity(checkpoint, identity)
    ordered: list[Unit] = []
    for key, group in sorted(by_case.items()):
        identity.case_id(key)
        for u in sorted(group, key=lambda u: rows.series_sort_key(u.row)):
            identity.scan_idx(key, u.row["series_uid"])
            ordered.append(u)

    def members(u: Unit) -> list[Path]:
        if u.key.startswith("memory:"):
            return list(retained[u.key].files)
        assert inventory is not None
        return inventory.members(u.key)

    def load(u: Unit) -> scan.Series:
        if u.key.startswith("memory:"):
            return retained[u.key]
        assert inventory is not None
        return replace(inventory.series(u.key), headers=())

    stats: dict[int, str] = {}
    if checkpoint is not None and not dry_run:
        pinned = []
        for u in ordered:
            if decisions[u.order][4]:
                stats[u.order] = commits.stat_digest(members(u))
                key = u.row["case_identity_key"]
                pinned.append(
                    {
                        "item": f"{identity.case_id(key)}.{identity.scan_idx(key, u.row['series_uid'])}.complete.-",
                        "files": u.n_files,
                        "stat": stats[u.order],
                    }
                )
                stage("verifying_inputs", len(pinned), selected_total)
        commits.pin_run(checkpoint, {**asdict(settings), "salt": salt}, VERSION, identity, pinned)

    # ---- decorate every series in plan order (no I/O) ----
    counts = {"series": len(found), "selected": 0, "converted": 0, "already_converted": 0, "skipped": 0, "failed": 0}
    storage = {"source_bytes": 0, "nifti_gz_estimated_bytes": 0}
    plan: list[dict[str, Any]] = []
    for group in by_case.values():
        rows.apply_scan_timing([u.row for u in group])
    for u in ordered:
        if dry_run and cancelled():
            break
        row = u.row
        key = row["case_identity_key"]
        case_id = identity.case_id(key)
        row["case_id"] = case_id
        row["scan_idx"] = identity.scan_idx(key, row["series_uid"])
        level, level_ev, role, role_reason, planned, skip_reason = decisions[u.order]
        delay, delay_source = contrast_delay(row)
        row["contrast_delay_seconds"] = "" if delay is None else str(delay)
        row["contrast_delay_source"] = delay_source
        row["target_match_level"] = level
        row["output_role"] = role
        row["include_guess"] = {"PRIMARY": "include", "SECONDARY": "secondary"}.get(role, "exclude")
        row["exclude_reason"] = role_reason if role == "EXCLUDED" else ""
        if skip_reason:
            row["skip_reason"] = skip_reason
        row["planned_conversion"] = planned
        u.planned = planned
        u.iid = f"{case_id}.{row['scan_idx']}.complete.-"
        u.annotations = [
            {
                "item_id": u.iid,
                "field": "target_match",
                "value": level,
                "confidence": target_rules.CONFIDENCE[level],
                "evidence": level_ev,
                "rules_version": target_rules.RULES_VERSION,
            },
            {
                "item_id": u.iid,
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
        row["filename"] = "_".join([*parts, case_id]) + "_0000.nii.gz"
        row["relative_path"] = f"{ref_rel}/nifti/{row['filename']}"
        est = 0
        if planned:
            counts["selected"] += 1
            src, est = _estimate(u)
            storage["source_bytes"] += src
            storage["nifti_gz_estimated_bytes"] += est
        plan.append(
            {
                "case_id": case_id,
                "scan_idx": row["scan_idx"],
                "patient": "" if anonymize else str(row.get("patient_id") or ""),
                "description": str(row.get("series_description") or ""),
                "modality": str(row.get("modality") or ""),
                "n_files": u.n_files,
                "action": "convert" if planned else "skip",
                "reason": "" if planned else str(row.get("skip_reason") or ""),
                "bytes": est,
            }
        )
        if not planned:
            row["status"] = "skipped"
            counts["skipped"] += 1
            u.message = str(row.get("skip_reason", ""))
        elif dry_run:
            row["status"] = "would_convert"
        if dry_run:
            stage("planning", len(plan), len(found))
        if progress is not None and (dry_run or not planned):
            progress(u.iid, "ok" if planned else "skipped", [], u.message)

    if retry_ids is not None:
        available = {u.iid for u in ordered if u.planned}
        if retry_ids - available:
            raise ValueError("Retry selection contains unavailable series; recover its original plan")
    jobs = [u for u in ordered if u.planned] if not dry_run else []
    if jobs and not allow_mixed_versions and retry_ids is None:
        current = commits.reader_versions(VERSION)
        earlier, new = 0, 0
        for u in jobs:
            record = nifti_dir / ".checkpoints" / u.row["filename"] / "commit.json"
            try:
                versions = json.loads(record.read_text())["identity"]["versions"]
            except (OSError, ValueError, KeyError, TypeError):
                new += 1
                continue
            earlier += commits.versions_differ(versions, current)
        if earlier and new:
            raise MixedVersions(
                f"Mixed converter versions: {earlier} committed series were converted by other reader "
                f"versions and {new} new series would use {current}; acknowledge mixed versions "
                "(allow_mixed_versions) or convert into a new dataset"
            )

    # ---- execute ----
    conversion_time = None
    sizes = {u.order: u.source_bytes for u in jobs} if on_bytes is not None else {}
    if on_timing is not None or on_bytes is not None:
        # discovery order, dry runs included: the estimate needs the same units as the run
        timed = [u for u in found if decisions[u.order][4] and (retry_ids is None or u.iid in retry_ids)]
        if on_timing is not None:
            conversion_time = on_timing({"t": "plan", "units": [timing_unit(u) for u in timed]})
        if retry_ids is not None:
            sizes = {u.order: sizes[u.order] for u in timed if u.order in sizes}
    bytes_total = sum(sizes.values())
    bytes_done = fresh_bytes = 0
    fresh_seconds = 0.0
    resource_wait: dict[str, Any] | None = None
    analyzer_rows: list[dict[str, Any]] = []
    units_by_versions: dict[str, dict[str, Any]] = {}
    started_at = time.monotonic()

    def report_bytes() -> None:
        if on_bytes is not None and not dry_run:
            on_bytes(
                {"done": bytes_done, "total": bytes_total, "fresh_bytes": fresh_bytes, "fresh_seconds": fresh_seconds}
            )

    def payload(u: Unit, *, pooled: bool) -> dict[str, Any]:
        row = u.row
        return {
            "series": load(u),
            "out": nifti_dir / row["filename"],
            "side": sidecar_dir / f"{row['filename']}.dicom.json",
            "settings": {**asdict(settings), "salt": salt},
            "sidecars": settings.sidecars,
            "anonymize": anonymize,
            "case_id": row["case_id"],
            "salt": salt,
            "dims": {k: row.get(k) for k in ("dim_x", "dim_y", "num_slices")},
            "memory_facts": {"SamplesPerPixel": u.facts["samples"], "BitsAllocated": u.facts["bits"]},
            "memory_mb": None if pooled else memory_mb,
            "verify_only": retry_ids is not None and u.iid not in retry_ids,
            "stat": stats.get(u.order),
        }

    def finish(u: Unit, outcome: dict[str, Any]) -> None:
        nonlocal bytes_done, fresh_bytes, fresh_seconds, resource_wait, conversion_time
        status = outcome["status"]
        row = u.row
        if status == "waiting_for_resources":
            row["status"] = status
            resource_wait = resource_wait or outcome["detail"]
            stage("memory_budget", 0, selected_total)
            return
        if status == "pending":
            row["status"] = "pending"
            return
        if status == "skipped":
            row["status"] = status
            row["skip_reason"] = u.message = outcome["reason"]
            counts["skipped"] += 1
            diagnostics.append(
                scan.Diagnostic(
                    "WARNING",
                    "series_conversion",
                    "SERIES_UNSTACKABLE",
                    outcome["reason"],
                    str(u.dicom_dir),
                    u.series_id,
                )
            )
        elif status == "failed":
            row["status"] = "failed"
            u.message = row["raw_metadata_error"] = outcome["error"]
            row["failure_category"] = outcome["category"]
            counts["failed"] += 1
            diagnostics.append(
                scan.Diagnostic(
                    "ERROR",
                    "series_conversion",
                    "SERIES_CONVERSION_FAILED",
                    outcome["error"],
                    str(u.dicom_dir),
                    u.series_id,
                )
            )
        else:
            g = outcome["geometry"]
            rows.update_geometry(
                row, tuple(g["size"]), tuple(g["spacing"]), tuple(g["origin"]), tuple(g["direction"]), g["pixel_type"]
            )
            row["status"] = status
            counts[status] += 1
            if settings.sidecars:
                row["dicom_sidecar"] = f"{ref_alias}:{ref_rel}/sidecars/{row['filename']}.dicom.json"
            u.outputs = outcome["outputs"]
            versions = outcome["versions"]
            entry = units_by_versions.setdefault(_versions_key(versions), {"versions": versions, "count": 0})
            entry["count"] += 1
            if u.order in sizes:
                bytes_done += sizes[u.order]
                if status == "converted" and outcome["fresh"]:
                    fresh_bytes += sizes[u.order]
                    fresh_seconds = time.monotonic() - started_at if workers > 1 else fresh_seconds + outcome["seconds"]
                report_bytes()
        if on_timing is not None:
            conversion_time = on_timing(
                {
                    "t": "unit",
                    "id": str(u.order),
                    "committed": status in {"converted", "already_converted"},
                    "seconds": outcome.get("seconds") if outcome.get("fresh") and status == "converted" else None,
                }
            )
        stage("converting", counts["converted"] + counts["already_converted"], selected_total)
        if progress is not None:
            progress(u.iid, {"failed": "failed", "skipped": "skipped"}.get(status, "ok"), u.outputs, u.message)

    def stop() -> bool:
        return cancelled() or (max_failures is not None and counts["failed"] > max_failures)

    stage(
        "planning" if dry_run else "converting", len(plan) if dry_run else 0, len(found) if dry_run else selected_total
    )
    report_bytes()
    if jobs and workers > 1:
        from rw_dicom.workers import WorkerSet

        by_order = {u.order: u for u in jobs}
        with WorkerSet(workers) as pool:
            pool.run(
                ((u.order, partial(payload, u, pooled=True), resources.estimate_mb(u.row, u.facts)) for u in jobs),
                budget_mb=memory_mb,
                stop=stop,
                on_result=lambda order, outcome: finish(by_order[order], outcome),
            )
    else:
        for u in jobs:
            if stop():
                break
            finish(u, convert_unit(payload(u, pooled=False)))
    for u in jobs:
        if "status" not in u.row or u.row["status"] in {"would_convert"}:
            u.row["status"] = "pending"

    # ---- assemble in plan order ----
    annotations: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    for u in ordered[: len(plan)]:
        row = u.row
        ready, reasons = readiness_rules.readiness(row)
        row["analysis_readiness"] = ready
        u.annotations.append(
            {
                "item_id": u.iid,
                "field": "readiness",
                "value": ready,
                "confidence": "high" if ready in ("ready", "unsuitable") else "medium",
                "evidence": ", ".join(reasons) or "no issues",
                "rules_version": readiness_rules.RULES_VERSION,
            }
        )
        if row.get("status") in {"converted", "already_converted"}:
            analyzer_rows.append({**clean_row(row), "item_id": u.iid})
        if anonymize:
            sidecar.anonymize_row(row, row["case_id"], salt)
        annotations += u.annotations
        outputs += u.outputs
    counts["selected"] = selected_total
    counts["pending"] = (
        0 if dry_run else max(0, selected_total - counts["converted"] - counts["already_converted"] - counts["failed"])
    )
    merged = {_key(r): r for r in previous}
    merged.update({_key(u.row): u.row for u in sorted(found, key=lambda u: u.order)})
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
        units_by_versions,
    )
