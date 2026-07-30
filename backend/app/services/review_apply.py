from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
from tempfile import NamedTemporaryFile
from threading import Lock, RLock
import uuid

from app.config import get_settings
from app.models.review import (
    ReviewApplyResponse,
    ReviewApplyResult,
    ReviewApplySummary,
    ReviewDeleteDecision,
    ReviewMovedFile,
    ReviewOperation,
)
from app.services.converter_metadata import (
    mark_converter_deleted,
    restore_converter_deleted,
    update_converter_phase,
)
from app.services.discovery import resolve_series_source
from app.services.runtime_cache import reset_runtime_caches
from app.services.workspace import validate_workspace_dataset_id, workspace_file


_DATASET_LOCKS: dict[str, RLock] = {}
_DATASET_LOCKS_GUARD = Lock()
CASE_ID_PATTERN = re.compile(r"(case_\d{5})")
MANIFEST_MINIMAL_FIELDS = [
    "filename",
    "patient_id",
    "case_id",
    "phase",
    "protocol_source",
]
DELETE_DECISION_LIMIT = 20


def apply_review_operations(
    dataset_id: str,
    operations: list[ReviewOperation],
) -> ReviewApplyResponse:
    settings = get_settings()
    if not settings.allow_data_mutations:
        raise PermissionError(
            "Review apply is disabled. Set ALLOW_DATA_MUTATIONS=true to enable dataset mutations."
        )

    dataset_path = validate_workspace_dataset_id(dataset_id)
    lock = _dataset_lock(dataset_id)
    batch_id = _build_batch_id()
    applied_at = _now_iso()

    with lock:
        summary = ReviewApplySummary(requested=len(operations))
        results: list[ReviewApplyResult] = []
        decisions_path = workspace_file("decisions.json")
        decisions_payload = _load_json_payload(decisions_path, default=[])
        reclassification_entries: list[dict] = []
        deletion_entries: list[dict] = []

        for operation in operations:
            result, metadata = _apply_single_operation(
                dataset_id=dataset_id,
                dataset_path=dataset_path,
                operation=operation,
            )
            results.append(result)
            _increment_summary(summary, result.status)
            decisions_payload.append(
                _decision_entry(
                    batch_id=batch_id,
                    applied_at=applied_at,
                    dataset_id=dataset_id,
                    operation=operation,
                    result=result,
                    metadata=metadata,
                )
            )
            if operation.action == "reclassify":
                reclassification_entries.append(
                    _batch_log_entry(operation=operation, result=result, metadata=metadata)
                )
            else:
                deletion_entries.append(
                    _batch_log_entry(operation=operation, result=result, metadata=metadata)
                )

        _atomic_write_json(decisions_path, decisions_payload)
        if reclassification_entries:
            _append_batch_log(
                workspace_file("reclassification_log.json"),
                batch_id=batch_id,
                applied_at=applied_at,
                entries=reclassification_entries,
            )
        if deletion_entries:
            _append_batch_log(
                workspace_file("deletion_log.json"),
                batch_id=batch_id,
                applied_at=applied_at,
                entries=deletion_entries,
            )
        reset_runtime_caches()

    return ReviewApplyResponse(
        batch_id=batch_id,
        applied_at=applied_at,
        summary=summary,
        results=results,
    )


def _apply_single_operation(
    dataset_id: str,
    dataset_path: Path,
    operation: ReviewOperation,
) -> tuple[ReviewApplyResult, dict]:
    try:
        source = resolve_series_source(dataset_path, operation.patient_id, operation.series_id)
    except FileNotFoundError as exc:
        return (
            ReviewApplyResult(
                patient_id=operation.patient_id,
                series_id=operation.series_id,
                action=operation.action,
                target_phase=operation.target_phase,
                status="skipped",
                message=str(exc),
            ),
            {
                "dataset_id": dataset_id,
                "series_type": None,
                "group": None,
                "phase": None,
                "filename": None,
                "moved_file_pairs": [],
            },
        )

    metadata = {
        "dataset_id": dataset_id,
        "series_type": source.type,
        "group": source.group,
        "phase": source.phase,
        "filename": source.filename,
        "moved_file_pairs": [],
    }

    if operation.action == "reclassify":
        return _apply_reclassify(dataset_path, operation, source), metadata
    if operation.action == "delete":
        result, moved_pairs = _apply_delete(dataset_path, operation, source)
    else:
        result, moved_pairs = _apply_restore(dataset_path, operation, source)
    metadata["moved_file_pairs"] = moved_pairs
    return result, metadata


def _apply_reclassify(dataset_path: Path, operation: ReviewOperation, source) -> ReviewApplyResult:
    target_phase = operation.target_phase
    if target_phase is None:
        return ReviewApplyResult(
            patient_id=operation.patient_id,
            series_id=operation.series_id,
            action=operation.action,
            target_phase=None,
            status="failed",
            message="target_phase is required for reclassify",
        )

    if source.type == "nifti":
        metadata_updated = update_converter_phase(dataset_path, source.filename, target_phase)
        message = _metadata_update_message(metadata_updated, manifest_updated=False)
        return ReviewApplyResult(
            patient_id=operation.patient_id,
            series_id=operation.series_id,
            action=operation.action,
            target_phase=target_phase,
            status="applied",
            message=message,
            moved_files=[],
            manifest_updated=False,
            metadata_updated=metadata_updated,
        )

    moved_files, message, status = _move_voi_to_phase(
        dataset_path=dataset_path,
        image_path=Path(source.image_path),
        mask_path=Path(source.mask_path) if source.mask_path else None,
        target_phase=target_phase,
    )
    return ReviewApplyResult(
        patient_id=operation.patient_id,
        series_id=operation.series_id,
        action=operation.action,
        target_phase=target_phase,
        status=status,
        message=message,
        moved_files=moved_files,
        manifest_updated=False,
        metadata_updated=False,
    )


def _apply_delete(
    dataset_path: Path,
    operation: ReviewOperation,
    source,
) -> tuple[ReviewApplyResult, list[dict[str, str]]]:
    metadata_updated = False
    if source.type == "nifti":
        moved_files, moved_pairs, message, status = _move_nifti_to_recycle(
            dataset_path=dataset_path,
            image_path=Path(source.image_path),
            mask_path=Path(source.mask_path) if source.mask_path else None,
        )
        if status == "applied":
            metadata_updated = mark_converter_deleted(
                dataset_path,
                source.filename,
                _nifti_destination_relative(moved_pairs),
            )
            if metadata_updated:
                message = f"{message}; converter metadata updated"
    else:
        moved_files, moved_pairs, message, status = _move_voi_to_recycle(
            dataset_path=dataset_path,
            image_path=Path(source.image_path),
            mask_path=Path(source.mask_path) if source.mask_path else None,
        )

    return (
        ReviewApplyResult(
            patient_id=operation.patient_id,
            series_id=operation.series_id,
            action=operation.action,
            target_phase=None,
            status=status,
            message=message,
            moved_files=moved_files,
            manifest_updated=False,
            metadata_updated=metadata_updated,
        ),
        moved_pairs,
    )


def _apply_restore(
    dataset_path: Path,
    operation: ReviewOperation,
    source,
) -> tuple[ReviewApplyResult, list[dict[str, str]]]:
    metadata_updated = False
    if not source.deleted:
        return (
            ReviewApplyResult(
                patient_id=operation.patient_id,
                series_id=operation.series_id,
                action=operation.action,
                target_phase=None,
                status="skipped",
                message="series is not marked as deleted",
                moved_files=[],
                manifest_updated=False,
                metadata_updated=False,
            ),
            [],
        )

    if source.type == "nifti":
        moved_files, moved_pairs, message, status = _restore_nifti_from_recycle(
            dataset_path=dataset_path,
            image_path=Path(source.image_path),
            mask_path=Path(source.mask_path) if source.mask_path else None,
        )
        if status == "applied":
            metadata_updated = restore_converter_deleted(
                dataset_path,
                source.filename,
                _nifti_restored_relative(moved_pairs),
            )
            if metadata_updated:
                message = f"{message}; converter metadata updated"
    else:
        moved_files, moved_pairs, message, status = _restore_voi_from_recycle(
            dataset_path=dataset_path,
            image_path=Path(source.image_path),
            mask_path=Path(source.mask_path) if source.mask_path else None,
        )

    return (
        ReviewApplyResult(
            patient_id=operation.patient_id,
            series_id=operation.series_id,
            action=operation.action,
            target_phase=None,
            status=status,
            message=message,
            moved_files=moved_files,
            manifest_updated=False,
            metadata_updated=metadata_updated,
        ),
        moved_pairs,
    )


def _move_nifti_to_recycle(
    dataset_path: Path,
    image_path: Path,
    mask_path: Path | None,
) -> tuple[list[ReviewMovedFile], list[dict[str, str]], str, str]:
    recycle_nifti_root = dataset_path / "deleted" / "nifti"
    recycle_seg_root = dataset_path / "deleted" / "seg"

    candidates: list[tuple[Path, Path]] = []
    image_resolved = _ensure_within(image_path, dataset_path)
    if not image_resolved.exists():
        return [], [], f"Source image not found: {image_resolved.name}", "skipped"
    candidates.append((image_resolved, recycle_nifti_root / image_resolved.name))

    if mask_path is not None:
        mask_resolved = _ensure_within(mask_path, dataset_path)
        if not mask_resolved.exists():
            return [], [], f"Source mask not found: {mask_resolved.name}", "skipped"
        candidates.append((mask_resolved, recycle_seg_root / mask_resolved.name))

    collision = _first_collision(candidates)
    if collision is not None:
        return [], [], f"Destination already exists: {collision}", "skipped"

    moved, move_pairs = _execute_moves(candidates, dataset_path)
    return moved, move_pairs, "moved to recycle bin", "applied"


def _restore_nifti_from_recycle(
    dataset_path: Path,
    image_path: Path,
    mask_path: Path | None,
) -> tuple[list[ReviewMovedFile], list[dict[str, str]], str, str]:
    recycle_nifti_root = (dataset_path / "deleted" / "nifti").resolve()
    recycle_seg_root = (dataset_path / "deleted" / "seg").resolve()
    nifti_root = dataset_path / "nifti"
    seg_root = dataset_path / "seg"

    candidates: list[tuple[Path, Path]] = []
    image_resolved = _ensure_within(image_path, recycle_nifti_root)
    if not image_resolved.exists():
        return [], [], f"Deleted image not found: {image_resolved.name}", "skipped"
    candidates.append((image_resolved, nifti_root / image_resolved.name))

    if mask_path is not None:
        mask_resolved = _ensure_within(mask_path, recycle_seg_root)
        if not mask_resolved.exists():
            return [], [], f"Deleted mask not found: {mask_resolved.name}", "skipped"
        candidates.append((mask_resolved, seg_root / mask_resolved.name))

    collision = _first_collision(candidates)
    if collision is not None:
        return [], [], f"Destination already exists: {collision}", "skipped"

    moved, move_pairs = _execute_moves(candidates, dataset_path)
    return moved, move_pairs, "restored from recycle bin", "applied"


def _move_voi_to_phase(
    dataset_path: Path,
    image_path: Path,
    mask_path: Path | None,
    target_phase: str,
) -> tuple[list[ReviewMovedFile], str, str]:
    image_root = dataset_path / "voi" / "images"
    image_resolved = _ensure_within(image_path, image_root)
    if not image_resolved.exists():
        return [], f"Source image not found: {image_resolved.name}", "skipped"

    try:
        image_relative = image_resolved.relative_to(image_root)
    except ValueError:
        return [], "VOI image path is outside expected root", "failed"

    if len(image_relative.parts) < 3:
        return [], "VOI image path is malformed", "failed"

    if len(image_relative.parts) == 3:
        group, patient_id, filename = image_relative.parts
    else:
        group, patient_id, _, filename = image_relative.parts[:4]
    image_target_relative = Path(group) / patient_id / target_phase / filename
    image_target = image_root / image_target_relative

    candidates: list[tuple[Path, Path]] = [(image_resolved, image_target)]

    if mask_path is not None:
        mask_resolved = mask_path.resolve()
        mask_roots = [dataset_path / "voi" / "mask", dataset_path / "voi" / "segmentation"]
        selected_root: Path | None = None
        selected_relative: Path | None = None
        for mask_root in mask_roots:
            try:
                selected_relative = mask_resolved.relative_to(mask_root.resolve())
                selected_root = mask_root
                break
            except ValueError:
                continue
        if selected_root is None or selected_relative is None:
            return [], "VOI mask path is outside expected roots", "failed"
        if not mask_resolved.exists():
            return [], f"Source mask not found: {mask_resolved.name}", "skipped"
        if len(selected_relative.parts) == 3:
            mask_group, mask_patient, mask_filename = selected_relative.parts
        else:
            mask_group, mask_patient, _, mask_filename = selected_relative.parts[:4]
        mask_target_relative = Path(mask_group) / mask_patient / target_phase / mask_filename
        candidates.append((mask_resolved, selected_root / mask_target_relative))

    collision = _first_collision(candidates)
    if collision is not None:
        return [], f"Destination already exists: {collision}", "skipped"

    moved, _ = _execute_moves(candidates, dataset_path)
    return moved, "moved to target phase", "applied"


def _move_voi_to_recycle(
    dataset_path: Path,
    image_path: Path,
    mask_path: Path | None,
) -> tuple[list[ReviewMovedFile], list[dict[str, str]], str, str]:
    image_root = dataset_path / "voi" / "images"
    recycle_image_root = dataset_path / "voi" / "deleted" / "images"
    recycle_mask_root = dataset_path / "voi" / "deleted" / "mask"

    image_resolved = _ensure_within(image_path, image_root)
    if not image_resolved.exists():
        return [], [], f"Source image not found: {image_resolved.name}", "skipped"

    try:
        image_relative = image_resolved.relative_to(image_root)
    except ValueError:
        return [], [], "VOI image path is outside expected root", "failed"

    candidates: list[tuple[Path, Path]] = [(image_resolved, recycle_image_root / image_relative)]

    if mask_path is not None:
        mask_resolved = mask_path.resolve()
        mask_roots = [dataset_path / "voi" / "mask", dataset_path / "voi" / "segmentation"]
        selected_relative: Path | None = None
        for mask_root in mask_roots:
            try:
                selected_relative = mask_resolved.relative_to(mask_root.resolve())
                break
            except ValueError:
                continue
        if selected_relative is None:
            return [], [], "VOI mask path is outside expected roots", "failed"
        if not mask_resolved.exists():
            return [], [], f"Source mask not found: {mask_resolved.name}", "skipped"
        candidates.append((mask_resolved, recycle_mask_root / selected_relative))

    collision = _first_collision(candidates)
    if collision is not None:
        return [], [], f"Destination already exists: {collision}", "skipped"

    moved, move_pairs = _execute_moves(candidates, dataset_path)
    return moved, move_pairs, "moved to recycle bin", "applied"


def _restore_voi_from_recycle(
    dataset_path: Path,
    image_path: Path,
    mask_path: Path | None,
) -> tuple[list[ReviewMovedFile], list[dict[str, str]], str, str]:
    recycle_image_root = (dataset_path / "voi" / "deleted" / "images").resolve()
    recycle_mask_root = (dataset_path / "voi" / "deleted" / "mask").resolve()
    image_root = dataset_path / "voi" / "images"
    mask_root = dataset_path / "voi" / "mask"

    image_resolved = _ensure_within(image_path, recycle_image_root)
    if not image_resolved.exists():
        return [], [], f"Deleted image not found: {image_resolved.name}", "skipped"

    try:
        image_relative = image_resolved.relative_to(recycle_image_root)
    except ValueError:
        return [], [], "Deleted VOI image path is outside expected root", "failed"

    candidates: list[tuple[Path, Path]] = [(image_resolved, image_root / image_relative)]

    if mask_path is not None:
        mask_resolved = _ensure_within(mask_path, recycle_mask_root)
        if not mask_resolved.exists():
            return [], [], f"Deleted mask not found: {mask_resolved.name}", "skipped"
        try:
            mask_relative = mask_resolved.relative_to(recycle_mask_root)
        except ValueError:
            return [], [], "Deleted VOI mask path is outside expected root", "failed"
        candidates.append((mask_resolved, mask_root / mask_relative))

    collision = _first_collision(candidates)
    if collision is not None:
        return [], [], f"Destination already exists: {collision}", "skipped"

    moved, move_pairs = _execute_moves(candidates, dataset_path)
    return moved, move_pairs, "restored from recycle bin", "applied"


def _metadata_update_message(metadata_updated: bool, manifest_updated: bool) -> str:
    parts: list[str] = []
    if metadata_updated:
        parts.append("phase.json updated")
    if manifest_updated:
        parts.append("manifest updated")
    return "; ".join(parts) if parts else "phase row not found"


def _update_manifest_phase(dataset_path: Path, filename: str, target_phase: str) -> bool:
    manifest_path = dataset_path / "manifest.csv"
    if not manifest_path.is_file():
        row = {
            "filename": filename,
            "patient_id": _extract_case_id(filename),
            "case_id": _extract_case_id(filename),
            "phase": target_phase,
            "protocol_source": "manual",
        }
        _atomic_write_csv(manifest_path, MANIFEST_MINIMAL_FIELDS, [row])
        return True

    with manifest_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    updated = False
    if "phase" not in fieldnames:
        fieldnames.append("phase")
    if "protocol_source" not in fieldnames:
        fieldnames.append("protocol_source")

    for row in rows:
        if (row.get("filename") or "").strip() != filename:
            continue
        row["phase"] = target_phase
        row["protocol_source"] = "manual"
        updated = True

    if not updated:
        rows.append(
            {
                "filename": filename,
                "patient_id": _extract_case_id(filename),
                "case_id": _extract_case_id(filename),
                "phase": target_phase,
                "protocol_source": "manual",
            }
        )
        updated = True

    _atomic_write_csv(manifest_path, fieldnames, rows)
    return True


def _extract_case_id(filename: str) -> str:
    match = CASE_ID_PATTERN.search(filename)
    if match:
        return match.group(1)
    stem = filename
    if stem.endswith(".nii.gz"):
        stem = stem[:-7]
    elif "." in stem:
        stem = stem.rsplit(".", 1)[0]
    return stem


def _decision_entry(
    batch_id: str,
    applied_at: str,
    dataset_id: str,
    operation: ReviewOperation,
    result: ReviewApplyResult,
    metadata: dict,
) -> dict:
    return {
        "decision_id": uuid.uuid4().hex,
        "batch_id": batch_id,
        "applied_at": applied_at,
        "dataset_id": dataset_id,
        "patient_id": operation.patient_id,
        "series_id": operation.series_id,
        "action": operation.action,
        "target_phase": operation.target_phase,
        "status": result.status,
        "message": result.message,
        "moved_files": [entry.model_dump() for entry in result.moved_files],
        "moved_file_pairs": list(metadata.get("moved_file_pairs", [])),
        "manifest_updated": result.manifest_updated,
        "metadata_updated": result.metadata_updated,
        "series_type": metadata.get("series_type"),
        "group": metadata.get("group"),
        "phase": metadata.get("phase"),
        "filename": metadata.get("filename"),
    }


def _batch_log_entry(operation: ReviewOperation, result: ReviewApplyResult, metadata: dict) -> dict:
    return {
        "patient_id": operation.patient_id,
        "series_id": operation.series_id,
        "action": operation.action,
        "target_phase": operation.target_phase,
        "status": result.status,
        "message": result.message,
        "moved_files": [entry.model_dump() for entry in result.moved_files],
        "manifest_updated": result.manifest_updated,
        "metadata_updated": result.metadata_updated,
        "series_type": metadata.get("series_type"),
        "group": metadata.get("group"),
        "phase": metadata.get("phase"),
        "filename": metadata.get("filename"),
    }


def _append_batch_log(path: Path, batch_id: str, applied_at: str, entries: list[dict]) -> None:
    payload = _load_json_payload(path, default={})
    if isinstance(payload, dict) and isinstance(payload.get("batches"), list):
        batches = payload["batches"]
    else:
        batches = []
        payload = {"batches": batches}
    batches.append(
        {
            "batch_id": batch_id,
            "applied_at": applied_at,
            "entries": entries,
        }
    )
    _atomic_write_json(path, payload)


def _execute_moves(
    candidates: list[tuple[Path, Path]], dataset_path: Path
) -> tuple[list[ReviewMovedFile], list[dict[str, str]]]:
    moved_files: list[ReviewMovedFile] = []
    moved_pairs: list[dict[str, str]] = []
    for source_path, destination_path in candidates:
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source_path), str(destination_path))
        moved_files.append(
            ReviewMovedFile(
                source=str(source_path.relative_to(dataset_path)),
                destination=str(destination_path.relative_to(dataset_path)),
            )
        )
        moved_pairs.append(
            {
                "source": str(source_path.relative_to(dataset_path)),
                "destination": str(destination_path.relative_to(dataset_path)),
            }
        )
    return moved_files, moved_pairs


def _nifti_destination_relative(moved_pairs: list[dict[str, str]]) -> str | None:
    for pair in moved_pairs:
        destination = pair.get("destination", "")
        if destination.startswith("deleted/nifti/"):
            return destination
    return None


def _nifti_restored_relative(moved_pairs: list[dict[str, str]]) -> str | None:
    for pair in moved_pairs:
        destination = pair.get("destination", "")
        if destination.startswith("nifti/"):
            return destination
    return None


def _first_collision(candidates: list[tuple[Path, Path]]) -> str | None:
    for _source, destination in candidates:
        if destination.exists():
            return str(destination)
    return None


def list_recent_delete_decisions(dataset_id: str) -> list[ReviewDeleteDecision]:
    validate_workspace_dataset_id(dataset_id)
    decisions_path = workspace_file("decisions.json")
    payload = _load_json_payload(decisions_path, default=[])
    if not isinstance(payload, list):
        raise RuntimeError(f"Invalid decisions payload in '{decisions_path}'")

    undone_ids = {
        str(entry.get("undoes_decision_id"))
        for entry in payload
        if isinstance(entry, dict) and entry.get("action") == "undo_delete"
    }

    restored_series: set[tuple[str, str]] = set()
    decisions: list[ReviewDeleteDecision] = []
    for entry in reversed(payload):
        if not isinstance(entry, dict):
            continue
        if entry.get("action") == "restore" and entry.get("status") == "applied":
            restored_series.add(
                (
                    str(entry.get("patient_id") or ""),
                    str(entry.get("series_id") or ""),
                )
            )
            continue
        if entry.get("action") != "delete" or entry.get("status") != "applied":
            continue
        decision_id = str(entry.get("decision_id") or "")
        if not decision_id or decision_id in undone_ids:
            continue
        series_key = (
            str(entry.get("patient_id") or ""),
            str(entry.get("series_id") or ""),
        )
        if series_key in restored_series:
            continue
        moved_pairs = [
            ReviewMovedFile.model_validate(item)
            for item in entry.get("moved_file_pairs", [])
            if isinstance(item, dict)
        ]
        decisions.append(
            ReviewDeleteDecision(
                decision_id=decision_id,
                applied_at=str(entry.get("applied_at") or ""),
                patient_id=str(entry.get("patient_id") or ""),
                series_id=str(entry.get("series_id") or ""),
                filename=entry.get("filename"),
                series_type=entry.get("series_type"),
                moved_files=moved_pairs,
                raw=entry,
            )
        )
        if len(decisions) >= DELETE_DECISION_LIMIT:
            break
    return decisions


def undo_delete_decision(dataset_id: str, decision_id: str) -> ReviewApplyResponse:
    settings = get_settings()
    if not settings.allow_data_mutations:
        raise PermissionError(
            "Review apply is disabled. Set ALLOW_DATA_MUTATIONS=true to enable dataset mutations."
        )

    dataset_path = validate_workspace_dataset_id(dataset_id)
    lock = _dataset_lock(dataset_id)
    applied_at = _now_iso()
    batch_id = _build_batch_id()

    with lock:
        decisions_path = workspace_file("decisions.json")
        payload = _load_json_payload(decisions_path, default=[])
        if not isinstance(payload, list):
            raise RuntimeError(f"Invalid decisions payload in '{decisions_path}'")

        target_entry = None
        for entry in payload:
            if isinstance(entry, dict) and entry.get("decision_id") == decision_id:
                target_entry = entry
                break

        if target_entry is None:
            raise FileNotFoundError(f"Delete decision '{decision_id}' not found")
        if target_entry.get("action") != "delete" or target_entry.get("status") != "applied":
            raise ValueError(f"Decision '{decision_id}' is not an applied delete decision")
        if any(
            isinstance(entry, dict)
            and entry.get("action") == "undo_delete"
            and entry.get("undoes_decision_id") == decision_id
            for entry in payload
        ):
            raise RuntimeError(f"Delete decision '{decision_id}' was already undone")

        move_pairs = [
            ReviewMovedFile.model_validate(item)
            for item in target_entry.get("moved_file_pairs", [])
            if isinstance(item, dict)
        ]
        if len(move_pairs) == 0:
            raise RuntimeError(f"Delete decision '{decision_id}' has no restorable file mapping")

        candidates: list[tuple[Path, Path]] = []
        for pair in move_pairs:
            source = _ensure_within(dataset_path / pair.destination, dataset_path)
            destination = _ensure_within(dataset_path / pair.source, dataset_path)
            if not source.exists():
                raise FileNotFoundError(f"Deleted file not found for undo: {pair.destination}")
            if destination.exists():
                raise RuntimeError(f"Original destination already exists: {pair.source}")
            candidates.append((source, destination))

        moved_files, moved_pairs = _execute_moves(candidates, dataset_path)
        metadata_updated = False
        filename = str(target_entry.get("filename") or "")
        if target_entry.get("series_type") == "nifti" and filename:
            metadata_updated = restore_converter_deleted(
                dataset_path,
                filename,
                _nifti_restored_relative(moved_pairs),
            )
        message = "delete restored from recycle bin"
        if metadata_updated:
            message = f"{message}; converter metadata updated"
        result = ReviewApplyResult(
            patient_id=str(target_entry.get("patient_id") or ""),
            series_id=str(target_entry.get("series_id") or ""),
            action="delete",
            target_phase=None,
            status="applied",
            message=message,
            moved_files=moved_files,
            manifest_updated=False,
            metadata_updated=metadata_updated,
        )
        payload.append(
            {
                "decision_id": uuid.uuid4().hex,
                "batch_id": batch_id,
                "applied_at": applied_at,
                "dataset_id": dataset_id,
                "patient_id": result.patient_id,
                "series_id": result.series_id,
                "action": "undo_delete",
                "undoes_decision_id": decision_id,
                "status": result.status,
                "message": result.message,
                "moved_files": [entry.model_dump() for entry in moved_files],
                "moved_file_pairs": moved_pairs,
                "metadata_updated": result.metadata_updated,
                "filename": target_entry.get("filename"),
                "series_type": target_entry.get("series_type"),
            }
        )
        _atomic_write_json(decisions_path, payload)
        reset_runtime_caches()

    return ReviewApplyResponse(
        batch_id=batch_id,
        applied_at=applied_at,
        summary=ReviewApplySummary(requested=1, applied=1, skipped=0, failed=0),
        results=[result],
    )


def _dataset_lock(dataset_id: str) -> RLock:
    with _DATASET_LOCKS_GUARD:
        lock = _DATASET_LOCKS.get(dataset_id)
        if lock is None:
            lock = RLock()
            _DATASET_LOCKS[dataset_id] = lock
        return lock


def _load_json_payload(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON payload in '{path}'") from exc
    except OSError as exc:
        raise RuntimeError(f"Unable to read '{path}'") from exc


def _atomic_write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with NamedTemporaryFile(
            "w",
            dir=path.parent,
            prefix=path.stem + ".",
            suffix=".tmp",
            encoding="utf-8",
            delete=False,
        ) as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            temp_path = Path(handle.name)
        temp_path.replace(path)
    except OSError as exc:
        raise RuntimeError(f"Unable to write '{path}'") from exc


def _atomic_write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with NamedTemporaryFile(
            "w",
            dir=path.parent,
            prefix=path.stem + ".",
            suffix=".tmp",
            encoding="utf-8",
            newline="",
            delete=False,
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
            temp_path = Path(handle.name)
        temp_path.replace(path)
    except OSError as exc:
        raise RuntimeError(f"Unable to write '{path}'") from exc


def _ensure_within(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    root_resolved = root.resolve()
    if not resolved.is_relative_to(root_resolved):
        raise RuntimeError(f"Path '{resolved}' resolves outside '{root_resolved}'")
    return resolved


def _increment_summary(summary: ReviewApplySummary, status: str) -> None:
    if status == "applied":
        summary.applied += 1
    elif status == "skipped":
        summary.skipped += 1
    else:
        summary.failed += 1


def _build_batch_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}_{uuid.uuid4().hex[:8]}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
