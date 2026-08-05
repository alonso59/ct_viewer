from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock, RLock
import uuid
from typing import Any

from app.config import get_settings
from app.models.metadata_sync import (
    MetadataSyncApplyResponse,
    MetadataSyncChange,
    MetadataSyncPreviewResponse,
    MetadataSyncSummary,
)
from app.services.converter_metadata import (
    canonical_scan_key,
    metadata_filename,
    read_converter_metadata_rows,
    read_voi_catalog_rows,
    scan_key,
    select_converter_phase,
    text_value,
)
from app.services.runtime_cache import reset_runtime_caches
from app.services.path_policy import file_access_status
from app.services.workspace import validate_workspace_dataset_id, workspace_file


DELETE_KEEP_VALUES = {"0", "false", "no", "delete", "deleted", "trash", "recycle"}
MISSING_PHASE_VALUES = {"", "UNDEFINED", "UNKNOWN", "UNK", "N/A", "NA", "NONE", "NULL"}
NIFTI_SUFFIXES = (".nii.gz", ".nii")
SEG_SUFFIXES = (".nii.gz", ".nii")

_DATASET_LOCKS: dict[str, RLock] = {}
_DATASET_LOCKS_GUARD = Lock()


def preview_metadata_sync(dataset_id: str) -> MetadataSyncPreviewResponse:
    dataset_path = validate_workspace_dataset_id(dataset_id)
    rows = read_converter_metadata_rows(dataset_path)
    phase_rows = _phase_rows(dataset_path)
    phase_by_key, phase_by_filename = _phase_indexes(phase_rows)
    decisions_by_filename = _decisions_by_filename()
    changes: list[MetadataSyncChange] = []

    for index, row in enumerate(rows):
        changes.extend(
            _metadata_row_changes(
                dataset_path=dataset_path,
                row=row,
                row_index=index,
                phase_by_key=phase_by_key,
                phase_by_filename=phase_by_filename,
                decisions_by_filename=decisions_by_filename,
            )
        )

    voi_rows = read_voi_catalog_rows(dataset_path)
    for index, row in enumerate(voi_rows):
        changes.extend(_voi_row_changes(dataset_path, row, index))

    return MetadataSyncPreviewResponse(
        dataset_id=dataset_id,
        summary=_summary(changes, total_rows=len(rows) + len(voi_rows)),
        changes=changes,
    )


def apply_metadata_sync(dataset_id: str) -> MetadataSyncApplyResponse:
    settings = get_settings()
    if not settings.allow_data_mutations:
        raise PermissionError(
            "Metadata sync is disabled. Set ALLOW_DATA_MUTATIONS=true to update metadata.jsonl."
        )

    dataset_path = validate_workspace_dataset_id(dataset_id)
    lock = _dataset_lock(dataset_id)
    batch_id = _build_batch_id()
    applied_at = _now_iso()

    with lock:
        preview = preview_metadata_sync(dataset_id)
        if preview.summary.conflicts:
            raise RuntimeError("Metadata sync has conflicts. Resolve them before applying.")

        metadata_updated = _apply_metadata_rows(dataset_path, batch_id, applied_at, preview.changes)
        voi_updated = _apply_voi_catalog_rows(dataset_path, batch_id, applied_at, preview.changes)
        phase_json_neutralized = _neutralize_phase_json(dataset_path, batch_id, applied_at)
        _append_sync_log(
            batch_id=batch_id,
            applied_at=applied_at,
            dataset_id=dataset_id,
            preview=preview,
            metadata_updated=metadata_updated,
            voi_catalog_updated=voi_updated,
            phase_json_neutralized=phase_json_neutralized,
        )
        reset_runtime_caches()

    return MetadataSyncApplyResponse(
        dataset_id=dataset_id,
        batch_id=batch_id,
        applied_at=applied_at,
        summary=preview.summary,
        changes=preview.changes,
        metadata_updated=metadata_updated or voi_updated,
        phase_json_neutralized=phase_json_neutralized,
    )


def _metadata_row_changes(
    *,
    dataset_path: Path,
    row: dict[str, Any],
    row_index: int,
    phase_by_key: dict[tuple[str, str], str],
    phase_by_filename: dict[str, str],
    decisions_by_filename: dict[str, dict[str, Any]],
) -> list[MetadataSyncChange]:
    filename = metadata_filename(row)
    if not filename:
        return [
            MetadataSyncChange(
                kind="conflicts",
                target="metadata",
                filename=f"metadata_row_{row_index}",
                row_index=row_index,
                message="Metadata row has no filename, relative_path, or nifti_file.",
            )
        ]

    case_id = text_value(row.get("case_id")) or None
    scan_idx = text_value(row.get("scan_idx")) or None
    active_image = dataset_path / "nifti" / filename
    deleted_image = dataset_path / "deleted" / "nifti" / filename
    active_exists = file_access_status(active_image) == "exists"
    deleted_exists = file_access_status(deleted_image) == "exists"
    current_relative = _metadata_relative_path(row, dataset_path, filename)
    metadata_deleted = _row_points_deleted(row)
    changes: list[MetadataSyncChange] = []

    if active_exists and deleted_exists:
        changes.append(
            MetadataSyncChange(
                kind="conflicts",
                target="metadata",
                filename=filename,
                case_id=case_id,
                scan_idx=scan_idx,
                row_index=row_index,
                current_relative_path=current_relative,
                message="Both active and deleted NIfTI files exist for this metadata row.",
            )
        )
    elif deleted_exists and not metadata_deleted:
        decision = decisions_by_filename.get(filename)
        changes.append(
            MetadataSyncChange(
                kind="delete_changes",
                target="metadata",
                filename=filename,
                case_id=case_id,
                scan_idx=scan_idx,
                row_index=row_index,
                current_relative_path=current_relative,
                target_relative_path=f"deleted/nifti/{filename}",
                message=_decision_message(decision, "NIfTI is in recycle bin; metadata must mark delete."),
            )
        )
    elif active_exists and metadata_deleted:
        decision = decisions_by_filename.get(filename)
        changes.append(
            MetadataSyncChange(
                kind="restore_changes",
                target="metadata",
                filename=filename,
                case_id=case_id,
                scan_idx=scan_idx,
                row_index=row_index,
                current_relative_path=current_relative,
                target_relative_path=f"nifti/{filename}",
                message=_decision_message(decision, "NIfTI is active again; metadata must mark restore."),
            )
        )
    elif not active_exists and not deleted_exists:
        changes.append(
            MetadataSyncChange(
                kind="conflicts",
                target="metadata",
                filename=filename,
                case_id=case_id,
                scan_idx=scan_idx,
                row_index=row_index,
                current_relative_path=current_relative,
                message="Neither active nor deleted NIfTI file exists for this metadata row.",
            )
        )

    target_phase = _target_phase_for_row(row, filename, phase_by_key, phase_by_filename)
    current_phase = text_value(row.get("curated_phase")) or text_value(row.get("phase"))
    if target_phase and _phase_differs(current_phase, target_phase):
        changes.append(
            MetadataSyncChange(
                kind="phase_changes",
                target="metadata",
                filename=filename,
                case_id=case_id,
                scan_idx=scan_idx,
                row_index=row_index,
                current_phase=current_phase or None,
                target_phase=target_phase,
                message="phase.json phase differs from metadata.jsonl.",
            )
        )
    elif not changes:
        changes.append(
            MetadataSyncChange(
                kind="already_consolidated",
                target="metadata",
                filename=filename,
                case_id=case_id,
                scan_idx=scan_idx,
                row_index=row_index,
                current_phase=current_phase or None,
                current_relative_path=current_relative,
                message="Metadata row already matches phase and file state.",
            )
        )

    return changes


def _voi_row_changes(dataset_path: Path, row: dict[str, Any], row_index: int) -> list[MetadataSyncChange]:
    image_path = _catalog_path(dataset_path, _catalog_image_path_value(row), expected_root="images")
    if image_path is None:
        return []

    case_id = text_value(row.get("case_id")) or None
    scan_idx = text_value(row.get("scan_idx")) or None
    side = text_value(row.get("side")) or None
    filename = image_path.name
    pair = _voi_active_deleted_pair(dataset_path, image_path, "images")
    if pair is None:
        return [
            MetadataSyncChange(
                kind="conflicts",
                target="voi_catalog",
                filename=filename,
                case_id=case_id,
                scan_idx=scan_idx,
                side=side,
                row_index=row_index,
                current_relative_path=_relative_or_raw(dataset_path, image_path),
                message="VOI catalog path is outside the active and deleted VOI roots.",
            )
        ]
    active_image, deleted_image = pair
    active_exists = file_access_status(active_image) == "exists"
    deleted_exists = file_access_status(deleted_image) == "exists"
    row_deleted = _path_points_deleted(_catalog_image_path_value(row))

    if active_exists and deleted_exists:
        return [
            MetadataSyncChange(
                kind="conflicts",
                target="voi_catalog",
                filename=filename,
                case_id=case_id,
                scan_idx=scan_idx,
                side=side,
                row_index=row_index,
                current_relative_path=_relative_or_raw(dataset_path, image_path),
                message="Both active and deleted VOI image files exist for this catalog row.",
            )
        ]
    if deleted_exists and not row_deleted:
        return [
            MetadataSyncChange(
                kind="delete_changes",
                target="voi_catalog",
                filename=filename,
                case_id=case_id,
                scan_idx=scan_idx,
                side=side,
                row_index=row_index,
                current_relative_path=_relative_or_raw(dataset_path, image_path),
                target_relative_path=str(deleted_image.relative_to(dataset_path)),
                message="VOI image is in recycle bin; voi_catalog.jsonl must mark delete.",
            )
        ]
    if active_exists and row_deleted:
        return [
            MetadataSyncChange(
                kind="restore_changes",
                target="voi_catalog",
                filename=filename,
                case_id=case_id,
                scan_idx=scan_idx,
                side=side,
                row_index=row_index,
                current_relative_path=_relative_or_raw(dataset_path, image_path),
                target_relative_path=str(active_image.relative_to(dataset_path)),
                message="VOI image is active again; voi_catalog.jsonl must mark restore.",
            )
        ]
    return []


def _apply_metadata_rows(
    dataset_path: Path,
    batch_id: str,
    applied_at: str,
    changes: list[MetadataSyncChange],
) -> bool:
    path = dataset_path / "metadata.jsonl"
    if file_access_status(path) != "exists":
        return False

    actionable = [
        change
        for change in changes
        if change.target == "metadata" and change.kind in {"phase_changes", "delete_changes", "restore_changes"}
    ]
    if not actionable:
        return False

    changes_by_row: dict[int, list[MetadataSyncChange]] = {}
    for change in actionable:
        if change.row_index is None:
            continue
        changes_by_row.setdefault(change.row_index, []).append(change)

    rows = read_converter_metadata_rows(dataset_path)
    for row_index, row_changes in changes_by_row.items():
        if row_index < 0 or row_index >= len(rows):
            continue
        row = dict(rows[row_index])
        actions: list[str] = []
        _stamp_previous_values(row)
        for change in row_changes:
            if change.kind == "phase_changes" and change.target_phase:
                row["phase"] = change.target_phase
                row["curated_phase"] = change.target_phase
                actions.append("phase")
            elif change.kind in {"delete_changes", "restore_changes"}:
                _apply_metadata_path_state(dataset_path, row, change)
                actions.append("delete" if change.kind == "delete_changes" else "restore")
        row["webui_metadata_batch_id"] = batch_id
        row["webui_metadata_updated_at"] = applied_at
        row["webui_metadata_actions"] = ",".join(dict.fromkeys(actions))
        rows[row_index] = row

    _atomic_write_jsonl(path, rows)
    return True


def _apply_voi_catalog_rows(
    dataset_path: Path,
    batch_id: str,
    applied_at: str,
    changes: list[MetadataSyncChange],
) -> bool:
    path = dataset_path / "voi" / "voi_catalog.jsonl"
    if file_access_status(path) != "exists":
        return False

    actionable = [
        change
        for change in changes
        if change.target == "voi_catalog" and change.kind in {"delete_changes", "restore_changes"}
    ]
    if not actionable:
        return False

    changes_by_row = {
        change.row_index: change for change in actionable if change.row_index is not None
    }
    rows = read_voi_catalog_rows(dataset_path)
    for row_index, change in changes_by_row.items():
        if row_index is None or row_index < 0 or row_index >= len(rows):
            continue
        row = dict(rows[row_index])
        image_path = _catalog_path(dataset_path, _catalog_image_path_value(row), expected_root="images")
        mask_path = _catalog_path(dataset_path, _catalog_mask_path_value(row), expected_root="mask")
        if image_path is not None:
            pair = _voi_active_deleted_pair(dataset_path, image_path, "images")
            if pair is None:
                continue
            active_image, deleted_image = pair
            target_image = deleted_image if change.kind == "delete_changes" else active_image
            _set_catalog_path(row, image=True, value=str(target_image.relative_to(dataset_path)))
        if mask_path is not None:
            pair = _voi_active_deleted_pair(dataset_path, mask_path, "mask")
            if pair is None:
                continue
            active_mask, deleted_mask = pair
            target_mask = deleted_mask if change.kind == "delete_changes" else active_mask
            if file_access_status(target_mask) == "exists":
                _set_catalog_path(row, image=False, value=str(target_mask.relative_to(dataset_path)))
        row["webui_metadata_batch_id"] = batch_id
        row["webui_metadata_updated_at"] = applied_at
        row["webui_metadata_action"] = "delete" if change.kind == "delete_changes" else "restore"
        rows[row_index] = row

    _atomic_write_jsonl(path, rows)
    return True


def _apply_metadata_path_state(dataset_path: Path, row: dict[str, Any], change: MetadataSyncChange) -> None:
    filename = metadata_filename(row) or change.filename
    if change.kind == "delete_changes":
        relative_path = f"deleted/nifti/{filename}"
        row["curated_keep"] = "no"
    else:
        relative_path = f"nifti/{filename}"
        if text_value(row.get("curated_keep")).lower() in DELETE_KEEP_VALUES:
            row["curated_keep"] = ""

    row["relative_path"] = relative_path
    row["nifti_file"] = str((dataset_path / relative_path).resolve())


def _neutralize_phase_json(dataset_path: Path, batch_id: str, applied_at: str) -> bool:
    path = dataset_path / "phase.json"
    if file_access_status(path) != "exists":
        return False
    try:
        payload = json.loads(path.resolve(strict=True).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False

    archive_path = workspace_file(f"phase_json_consumed_{batch_id}.json", create=True)
    _atomic_write_json(archive_path, payload)
    neutral_payload = {
        "schema_version": 1,
        "source": "metadata.jsonl",
        "description": "Neutralized by WebUI metadata sync. metadata.jsonl is the source of truth.",
        "updated_at": applied_at,
        "batch_id": batch_id,
        "phases": [],
    }
    _atomic_write_json(path, neutral_payload)
    return True


def _append_sync_log(
    *,
    batch_id: str,
    applied_at: str,
    dataset_id: str,
    preview: MetadataSyncPreviewResponse,
    metadata_updated: bool,
    voi_catalog_updated: bool,
    phase_json_neutralized: bool,
) -> None:
    path = workspace_file("metadata_update_log.json", create=True)
    payload = _load_json_payload(path, default={"batches": []})
    if not isinstance(payload, dict) or not isinstance(payload.get("batches"), list):
        payload = {"batches": []}
    payload["batches"].append(
        {
            "batch_id": batch_id,
            "applied_at": applied_at,
            "dataset_id": dataset_id,
            "summary": preview.summary.model_dump(),
            "changes": [change.model_dump() for change in preview.changes if change.kind != "already_consolidated"],
            "metadata_updated": metadata_updated,
            "voi_catalog_updated": voi_catalog_updated,
            "phase_json_neutralized": phase_json_neutralized,
        }
    )
    _atomic_write_json(path, payload)


def _summary(changes: list[MetadataSyncChange], total_rows: int) -> MetadataSyncSummary:
    summary = MetadataSyncSummary(total_rows=total_rows)
    if not changes:
        summary.noop = total_rows
        return summary
    for change in changes:
        if change.kind == "phase_changes":
            summary.phase_changes += 1
        elif change.kind == "delete_changes":
            summary.delete_changes += 1
        elif change.kind == "restore_changes":
            summary.restore_changes += 1
        elif change.kind == "already_consolidated":
            summary.already_consolidated += 1
        elif change.kind == "conflicts":
            summary.conflicts += 1
        elif change.kind == "noop":
            summary.noop += 1
        if change.target == "voi_catalog" and change.kind in {"delete_changes", "restore_changes"}:
            summary.voi_catalog_changes += 1
    if (
        summary.phase_changes == 0
        and summary.delete_changes == 0
        and summary.restore_changes == 0
        and summary.conflicts == 0
    ):
        summary.noop = max(0, total_rows - summary.already_consolidated)
    return summary


def _target_phase_for_row(
    row: dict[str, Any],
    filename: str,
    phase_by_key: dict[tuple[str, str], str],
    phase_by_filename: dict[str, str],
) -> str:
    key = scan_key(row)
    phase = phase_by_key.get(key) if key is not None else None
    phase = phase or phase_by_filename.get(filename)
    if not phase or _phase_is_missing(phase):
        return ""
    return phase


def _phase_indexes(rows: list[dict[str, Any]]) -> tuple[dict[tuple[str, str], str], dict[str, str]]:
    by_key: dict[tuple[str, str], str] = {}
    by_filename: dict[str, str] = {}
    for row in rows:
        phase = text_value(row.get("phase"))
        key = canonical_scan_key(row.get("case_id"), row.get("scan_idx"))
        if key is not None and phase:
            by_key[key] = phase
        filename = text_value(row.get("filename")) or metadata_filename(row)
        if filename and phase:
            by_filename[filename] = phase
    return by_key, by_filename


def _phase_rows(dataset_path: Path) -> list[dict[str, Any]]:
    path = dataset_path / "phase.json"
    if file_access_status(path) != "exists":
        return []
    try:
        payload = json.loads(path.resolve(strict=True).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("phases", "rows"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []


def _decisions_by_filename() -> dict[str, dict[str, Any]]:
    path = workspace_file("decisions.json", create=False)
    payload = _load_json_payload(path, default=[])
    if not isinstance(payload, list):
        return {}
    decisions: dict[str, dict[str, Any]] = {}
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        filename = text_value(entry.get("filename"))
        if filename:
            decisions[filename] = entry
    return decisions


def _decision_message(decision: dict[str, Any] | None, fallback: str) -> str:
    if not decision:
        return fallback
    action = text_value(decision.get("action"))
    applied_at = text_value(decision.get("applied_at"))
    return f"{fallback} Last WebUI decision: {action} at {applied_at}."


def _metadata_relative_path(row: dict[str, Any], dataset_path: Path, filename: str) -> str:
    relative = text_value(row.get("relative_path"))
    if relative:
        return relative
    nifti_file = text_value(row.get("nifti_file"))
    if nifti_file:
        path = Path(nifti_file)
        try:
            return str(path.resolve().relative_to(dataset_path))
        except (OSError, ValueError):
            return nifti_file
    return f"nifti/{filename}"


def _row_points_deleted(row: dict[str, Any]) -> bool:
    if text_value(row.get("curated_keep")).lower() in DELETE_KEEP_VALUES:
        return True
    return any(
        _path_points_deleted(text_value(row.get(key)))
        for key in ("relative_path", "nifti_file", "nifti_path", "seg_path")
    )


def _path_points_deleted(value: str) -> bool:
    normalized = text_value(value).replace("\\", "/")
    return normalized.startswith("deleted/") or "/deleted/" in normalized or normalized.startswith("voi/deleted/")


def _phase_differs(current: str, target: str) -> bool:
    return text_value(current).upper() != text_value(target).upper()


def _phase_is_missing(value: str) -> bool:
    return text_value(value).upper().replace(" ", "").replace("_", "-") in MISSING_PHASE_VALUES


def _stamp_previous_values(row: dict[str, Any]) -> None:
    for key in ("phase", "curated_phase", "relative_path", "nifti_file", "curated_keep"):
        row[f"webui_previous_{key}"] = row.get(key, "")


def _catalog_image_path_value(row: dict[str, Any]) -> str:
    return text_value(row.get("voi_image_path")) or text_value(row.get("image_path"))


def _catalog_mask_path_value(row: dict[str, Any]) -> str:
    return text_value(row.get("voi_mask_path")) or text_value(row.get("mask_path"))


def _set_catalog_path(row: dict[str, Any], *, image: bool, value: str) -> None:
    preferred = "voi_image_path" if image else "voi_mask_path"
    fallback = "image_path" if image else "mask_path"
    if preferred in row:
        row[preferred] = value
    else:
        row[fallback] = value


def _catalog_path(dataset_path: Path, raw_path: str, *, expected_root: str) -> Path | None:
    value = text_value(raw_path)
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    if path.parts and path.parts[0] == "voi":
        return dataset_path / path
    if path.parts and path.parts[0] == "deleted":
        return dataset_path / "voi" / path
    return dataset_path / "voi" / expected_root / path


def _voi_active_deleted_pair(
    dataset_path: Path,
    path: Path,
    kind: str,
) -> tuple[Path, Path] | None:
    resolved = path.resolve(strict=False)
    active_root = (dataset_path / "voi" / kind).resolve()
    deleted_root = (dataset_path / "voi" / "deleted" / kind).resolve()
    if kind == "mask":
        alternate_active_roots = [(dataset_path / "voi" / "segmentation").resolve()]
    else:
        alternate_active_roots = []

    for root in [active_root, *alternate_active_roots]:
        try:
            relative = resolved.relative_to(root)
            return root / relative, deleted_root / relative
        except ValueError:
            continue

    try:
        relative = resolved.relative_to(deleted_root)
        return active_root / relative, deleted_root / relative
    except ValueError:
        return None


def _relative_or_raw(dataset_path: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(dataset_path))
    except ValueError:
        return str(path)


def _dataset_lock(dataset_id: str) -> RLock:
    with _DATASET_LOCKS_GUARD:
        lock = _DATASET_LOCKS.get(dataset_id)
        if lock is None:
            lock = RLock()
            _DATASET_LOCKS[dataset_id] = lock
        return lock


def _load_json_payload(path: Path, default):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w",
        dir=path.parent,
        prefix=path.stem + ".",
        suffix=".tmp",
        encoding="utf-8",
        delete=False,
    ) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True, default=str))
            handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


def _atomic_write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w",
        dir=path.parent,
        prefix=path.stem + ".",
        suffix=".tmp",
        encoding="utf-8",
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=True, indent=2, default=str)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


def _build_batch_id() -> str:
    return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
