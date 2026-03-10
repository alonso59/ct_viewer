from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from tempfile import NamedTemporaryFile
from threading import Lock, RLock
import uuid

from app.config import get_settings
from app.models.review import (
    ReviewApplyResponse,
    ReviewApplyResult,
    ReviewApplySummary,
    ReviewOperation,
)
from app.services.discovery import resolve_dataset_path, resolve_series_source


_DATASET_LOCKS: dict[str, RLock] = {}
_DATASET_LOCKS_GUARD = Lock()


def apply_review_operations(
    dataset_id: str,
    operations: list[ReviewOperation],
) -> ReviewApplyResponse:
    settings = get_settings()
    if not settings.allow_data_mutations:
        raise PermissionError(
            "Review apply is disabled. Set ALLOW_DATA_MUTATIONS=true to enable dataset mutations."
        )

    dataset_path = resolve_dataset_path(settings.data_root, dataset_id)
    lock = _dataset_lock(dataset_id)
    batch_id = _build_batch_id()
    applied_at = _now_iso()

    with lock:
        summary = ReviewApplySummary(requested=len(operations))
        results: list[ReviewApplyResult] = []
        decisions_path = dataset_path / "decisions.json"
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
                dataset_path / "reclassification_log.json",
                batch_id=batch_id,
                applied_at=applied_at,
                entries=reclassification_entries,
            )
        if deletion_entries:
            _append_batch_log(
                dataset_path / "deletion_log.json",
                batch_id=batch_id,
                applied_at=applied_at,
                entries=deletion_entries,
            )

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
            },
        )

    metadata = {
        "dataset_id": dataset_id,
        "series_type": source.type,
        "group": source.group,
        "phase": source.phase,
        "filename": source.filename,
    }

    if operation.action == "reclassify":
        return _apply_reclassify(dataset_path, operation, source), metadata
    return _apply_delete(dataset_path, operation, source), metadata


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
        manifest_updated = _update_manifest_phase(dataset_path, source.filename, target_phase)
        return ReviewApplyResult(
            patient_id=operation.patient_id,
            series_id=operation.series_id,
            action=operation.action,
            target_phase=target_phase,
            status="applied",
            message="manifest updated" if manifest_updated else "manifest row not found",
            moved_files=[],
            manifest_updated=manifest_updated,
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
    )


def _apply_delete(dataset_path: Path, operation: ReviewOperation, source) -> ReviewApplyResult:
    if source.type == "nifti":
        moved_files, message, status = _move_nifti_to_recycle(
            dataset_path=dataset_path,
            image_path=Path(source.image_path),
            mask_path=Path(source.mask_path) if source.mask_path else None,
        )
    else:
        moved_files, message, status = _move_voi_to_recycle(
            dataset_path=dataset_path,
            image_path=Path(source.image_path),
            mask_path=Path(source.mask_path) if source.mask_path else None,
        )

    return ReviewApplyResult(
        patient_id=operation.patient_id,
        series_id=operation.series_id,
        action=operation.action,
        target_phase=None,
        status=status,
        message=message,
        moved_files=moved_files,
        manifest_updated=False,
    )


def _move_nifti_to_recycle(
    dataset_path: Path,
    image_path: Path,
    mask_path: Path | None,
) -> tuple[list[str], str, str]:
    recycle_nifti_root = dataset_path / "deleted" / "nifti"
    recycle_seg_root = dataset_path / "deleted" / "seg"

    candidates: list[tuple[Path, Path]] = []
    image_resolved = _ensure_within(image_path, dataset_path)
    if not image_resolved.exists():
        return [], f"Source image not found: {image_resolved.name}", "skipped"
    candidates.append((image_resolved, recycle_nifti_root / image_resolved.name))

    if mask_path is not None:
        mask_resolved = _ensure_within(mask_path, dataset_path)
        if not mask_resolved.exists():
            return [], f"Source mask not found: {mask_resolved.name}", "skipped"
        candidates.append((mask_resolved, recycle_seg_root / mask_resolved.name))

    collision = _first_collision(candidates)
    if collision is not None:
        return [], f"Destination already exists: {collision}", "skipped"

    moved = _execute_moves(candidates, dataset_path)
    return moved, "moved to recycle bin", "applied"


def _move_voi_to_phase(
    dataset_path: Path,
    image_path: Path,
    mask_path: Path | None,
    target_phase: str,
) -> tuple[list[str], str, str]:
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

    moved = _execute_moves(candidates, dataset_path)
    return moved, "moved to target phase", "applied"


def _move_voi_to_recycle(
    dataset_path: Path,
    image_path: Path,
    mask_path: Path | None,
) -> tuple[list[str], str, str]:
    image_root = dataset_path / "voi" / "images"
    recycle_image_root = dataset_path / "voi" / "deleted" / "images"
    recycle_mask_root = dataset_path / "voi" / "deleted" / "mask"

    image_resolved = _ensure_within(image_path, image_root)
    if not image_resolved.exists():
        return [], f"Source image not found: {image_resolved.name}", "skipped"

    try:
        image_relative = image_resolved.relative_to(image_root)
    except ValueError:
        return [], "VOI image path is outside expected root", "failed"

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
            return [], "VOI mask path is outside expected roots", "failed"
        if not mask_resolved.exists():
            return [], f"Source mask not found: {mask_resolved.name}", "skipped"
        candidates.append((mask_resolved, recycle_mask_root / selected_relative))

    collision = _first_collision(candidates)
    if collision is not None:
        return [], f"Destination already exists: {collision}", "skipped"

    moved = _execute_moves(candidates, dataset_path)
    return moved, "moved to recycle bin", "applied"


def _update_manifest_phase(dataset_path: Path, filename: str, target_phase: str) -> bool:
    manifest_path = dataset_path / "manifest.csv"
    if not manifest_path.is_file():
        return False

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
        return False

    _atomic_write_csv(manifest_path, fieldnames, rows)
    return True


def _decision_entry(
    batch_id: str,
    applied_at: str,
    dataset_id: str,
    operation: ReviewOperation,
    result: ReviewApplyResult,
    metadata: dict,
) -> dict:
    return {
        "batch_id": batch_id,
        "applied_at": applied_at,
        "dataset_id": dataset_id,
        "patient_id": operation.patient_id,
        "series_id": operation.series_id,
        "action": operation.action,
        "target_phase": operation.target_phase,
        "status": result.status,
        "message": result.message,
        "moved_files": list(result.moved_files),
        "manifest_updated": result.manifest_updated,
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
        "moved_files": list(result.moved_files),
        "manifest_updated": result.manifest_updated,
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


def _execute_moves(candidates: list[tuple[Path, Path]], dataset_path: Path) -> list[str]:
    moved_files: list[str] = []
    for source_path, destination_path in candidates:
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source_path), str(destination_path))
        moved_files.append(
            f"{source_path.relative_to(dataset_path)} -> {destination_path.relative_to(dataset_path)}"
        )
    return moved_files


def _first_collision(candidates: list[tuple[Path, Path]]) -> str | None:
    for _source, destination in candidates:
        if destination.exists():
            return str(destination)
    return None


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
