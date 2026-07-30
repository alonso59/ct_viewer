from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Iterable

from app.config import get_settings
from app.models.database import RequiredColumnStatus
from app.models.dataset_browser import (
    DatasetBrowserEntry,
    DatasetBrowserListResponse,
    DatasetBrowserRoot,
    SelectionValidationMessage,
    ValidationSeverity,
    WorkspaceSelectionSummary,
    WorkspaceSelectionValidationRequest,
    WorkspaceSelectionValidationResponse,
)
from app.services.database import required_column_status
from app.services.path_resolver import resolve_database_path
from app.services.workspace import set_workspace_selection


DATASET_MARKERS = ("database.csv", "nifti", "seg", "voi", "manifest.csv")
PATH_COLUMNS = (
    "nifti_path",
    "nifti_original_volume_path",
    "filename",
    "seg_path",
    "voi_image_path",
    "voi_mask_path",
)
SAMPLE_ROW_LIMIT = 40
SAMPLE_FILE_LIMIT = 80


def dataset_browser_roots() -> list[DatasetBrowserRoot]:
    settings = get_settings()
    candidates: list[tuple[str, str, str, bool]] = []

    if settings.dataset_dir:
        candidates.append(("DATASET_DIR", "Configured DATASET_DIR", settings.dataset_dir, False))

    for index, root in enumerate(_split_roots(settings.dataset_roots), start=1):
        candidates.append(("DATASET_ROOTS", f"Configured root {index}", root, False))

    candidates.append(("DATA_ROOT", "Portable dataset root", settings.data_root, True))

    data_mount = Path("/data")
    if data_mount.is_dir():
        candidates.append(("/data", "Container dataset mount", str(data_mount), True))

    candidates.append(("home", "Home", str(Path.home()), True))

    for source, label, path in _detect_drives_and_mounts():
        candidates.append((source, label, path, True))

    candidates.append(("filesystem", "Full filesystem", "/", False))

    return _dedupe_roots(candidates)


def _detect_drives_and_mounts() -> list[tuple[str, str, str]]:
    import platform
    import string as _string

    result: list[tuple[str, str, str]] = []
    system = platform.system()

    if system == "Windows":
        for letter in _string.ascii_uppercase:
            drive = f"{letter}:\\"
            if Path(drive).exists():
                result.append(("drive", f"Drive {letter}:", drive))
    elif system == "Darwin":
        volumes = Path("/Volumes")
        if volumes.is_dir():
            try:
                for vol in sorted(volumes.iterdir()):
                    if vol.is_dir() and vol.name != "Macintosh HD":
                        result.append(("volume", vol.name, str(vol)))
            except OSError:
                pass
    else:  # Linux
        for mount_root in ("/media", "/mnt"):
            mount_path = Path(mount_root)
            if not mount_path.is_dir():
                continue
            try:
                for child in sorted(mount_path.iterdir()):
                    if child.is_dir():
                        result.append(("mount", child.name, str(child)))
            except OSError:
                pass
        run_media = Path("/run/media")
        if run_media.is_dir():
            try:
                for user_dir in run_media.iterdir():
                    if user_dir.is_dir():
                        try:
                            for vol in sorted(user_dir.iterdir()):
                                if vol.is_dir():
                                    result.append(("mount", vol.name, str(vol)))
                        except OSError:
                            pass
            except OSError:
                pass

    return result


def list_dataset_browser_path(raw_path: str) -> DatasetBrowserListResponse:
    # Reject empty paths and tilde-prefixed expressions before resolving.
    sanitized = (raw_path or "").strip()
    if not sanitized:
        raise ValueError("Path must not be empty")
    if sanitized.startswith("~"):
        raise PermissionError("Tilde-expanded paths are not permitted")
    roots = dataset_browser_roots()
    # Resolve without expanduser() so ~ cannot be used as an escape vector.
    candidate = Path(sanitized).resolve()
    root = _matching_root(candidate, roots)
    if root is None:
        raise PermissionError("Path is outside the configured dataset browser roots")
    if not candidate.exists():
        raise FileNotFoundError(f"Path '{candidate}' does not exist")
    if not candidate.is_dir():
        raise ValueError(f"Path '{candidate}' is not a directory")
    if not os.access(candidate, os.R_OK):
        raise PermissionError(f"Path '{candidate}' is not readable")

    entries: list[DatasetBrowserEntry] = []
    try:
        children = list(candidate.iterdir())
    except OSError as exc:
        raise PermissionError(f"Unable to list '{candidate}'") from exc

    for child in children:
        try:
            entry_type = "directory" if child.is_dir() else "file"
            is_database = child.is_file() and child.name == "database.csv"
            entries.append(
                DatasetBrowserEntry(
                    name=child.name,
                    path=str(child.resolve()),
                    type=entry_type,
                    is_database_csv=is_database,
                    maybe_has_dataset_structure=_maybe_has_dataset_structure(child),
                    readable=os.access(child, os.R_OK),
                )
            )
        except OSError:
            continue

    entries.sort(key=lambda item: (item.type != "directory", not item.is_database_csv, item.name.lower()))
    return DatasetBrowserListResponse(
        path=str(candidate),
        parent_path=_browser_parent(candidate, root),
        entries=entries,
    )


def validate_workspace_selection(
    payload: WorkspaceSelectionValidationRequest,
) -> WorkspaceSelectionValidationResponse:
    successes: list[SelectionValidationMessage] = []
    warnings: list[SelectionValidationMessage] = []
    errors: list[SelectionValidationMessage] = []
    summary = WorkspaceSelectionSummary()

    folder_path = _clean_path(payload.dataset_folder_path)
    csv_path = _clean_path(payload.database_csv_path)

    if not folder_path and not csv_path:
        errors.append(_message("missing_selection", "Select a dataset folder or database.csv file.", "error"))
        return _response(summary, successes, warnings, errors)

    dataset_root: Path | None = None
    database_path: Path | None = None

    if folder_path:
        dataset_root = _resolve(folder_path)
        _check_directory(dataset_root, errors, label="Dataset folder")
        if not errors:
            successes.append(
                _message("path_readable", "Dataset folder exists and is readable.", "success", dataset_root)
            )
            database_path = dataset_root / "database.csv"

    if csv_path:
        database_path = _resolve(csv_path)
        _check_database_file(database_path, errors)
        if not errors:
            successes.append(
                _message("database_selected", "Selected database.csv exists and is readable.", "success", database_path)
            )

    if errors:
        return _response(summary, successes, warnings, errors)

    if database_path is None:
        errors.append(_message("missing_database", "database.csv was not found.", "error"))
        return _response(summary, successes, warnings, errors)

    if dataset_root is None:
        inferred = _infer_dataset_root(database_path)
        if inferred is None:
            errors.append(
                _message(
                    "dataset_root_ambiguous",
                    "Could not infer the dataset root for this database.csv. Select the dataset folder instead.",
                    "error",
                    database_path,
                )
            )
            return _response(summary, successes, warnings, errors, requires_dataset_root=True)
        dataset_root = inferred
        successes.append(_message("root_inferred", "Dataset root was inferred from the selection.", "success", dataset_root))

    if not database_path.is_file():
        errors.append(
            _message(
                "missing_database",
                "database.csv was not found in the selected dataset folder.",
                "error",
                database_path,
            )
        )
        return _response(summary, successes, warnings, errors)

    summary = WorkspaceSelectionSummary(
        dataset_id=dataset_root.name,
        dataset_root=str(dataset_root),
        database_csv_path=str(database_path),
        has_database=True,
        has_nifti=(dataset_root / "nifti").is_dir(),
        has_seg=(dataset_root / "seg").is_dir(),
        has_voi=(dataset_root / "voi").is_dir(),
        has_manifest=(dataset_root / "manifest.csv").is_file(),
    )

    csv_result = _read_database_csv(database_path, dataset_root)
    summary = summary.model_copy(
        update={
            "row_count": csv_result.row_count,
            "case_count": csv_result.case_count,
            "sampled_rows": csv_result.sampled_rows,
            "sampled_referenced_files": csv_result.sampled_referenced_files,
            "sampled_existing_files": csv_result.sampled_existing_files,
            "has_nifti": summary.has_nifti or csv_result.has_nifti,
            "has_seg": summary.has_seg or csv_result.has_seg,
            "has_voi": summary.has_voi or csv_result.has_voi,
        }
    )
    successes.extend(csv_result.successes)
    warnings.extend(csv_result.warnings)
    errors.extend(csv_result.errors)

    if errors:
        return _response(summary, successes, warnings, errors)

    try:
        workspace = set_workspace_selection(str(dataset_root), database_path)
    except Exception as exc:
        errors.append(_message("workspace_activation_failed", str(exc), "error", dataset_root))
        return _response(summary, successes, warnings, errors)

    return WorkspaceSelectionValidationResponse(
        valid=True,
        activated=True,
        summary=summary,
        successes=successes,
        warnings=warnings,
        errors=errors,
        workspace=workspace,
    )


class _CsvValidationResult:
    def __init__(self) -> None:
        self.row_count = 0
        self.case_count = 0
        self.sampled_rows = 0
        self.sampled_referenced_files = 0
        self.sampled_existing_files = 0
        self.has_nifti = False
        self.has_seg = False
        self.has_voi = False
        self.successes: list[SelectionValidationMessage] = []
        self.warnings: list[SelectionValidationMessage] = []
        self.errors: list[SelectionValidationMessage] = []


def _read_database_csv(database_path: Path, dataset_root: Path) -> _CsvValidationResult:
    result = _CsvValidationResult()
    sample_rows: list[dict[str, str]] = []
    case_ids: set[str] = set()

    try:
        with database_path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            fieldnames = tuple(reader.fieldnames or ())
            if not fieldnames:
                result.errors.append(_message("csv_missing_header", "database.csv has no header row.", "error", database_path))
                return result

            missing_columns = [status for status in required_column_status(fieldnames) if not status.present]
            if missing_columns:
                result.errors.extend(_missing_column_messages(missing_columns, database_path))
            else:
                result.successes.append(
                    _message("columns_ok", "Required database.csv columns are present.", "success", database_path)
                )

            for row in reader:
                result.row_count += 1
                case_id = (row.get("case_id") or "").strip()
                if case_id:
                    case_ids.add(case_id)
                if len(sample_rows) < SAMPLE_ROW_LIMIT:
                    sample_rows.append({key: value or "" for key, value in row.items()})
    except csv.Error as exc:
        result.errors.append(_message("csv_parse_error", f"database.csv could not be parsed: {exc}", "error", database_path))
        return result
    except OSError as exc:
        result.errors.append(_message("csv_read_error", f"database.csv could not be read: {exc}", "error", database_path))
        return result

    result.case_count = len(case_ids)
    result.sampled_rows = len(sample_rows)

    if result.row_count == 0:
        result.errors.append(_message("csv_empty", "database.csv contains no data rows.", "error", database_path))
    else:
        result.successes.append(_message("csv_rows", f"Read {result.row_count} database rows.", "success", database_path))

    if result.case_count == 0:
        result.errors.append(_message("missing_case_ids", "No case_id values were found.", "error", database_path))
    else:
        result.successes.append(_message("case_count", f"Found {result.case_count} unique cases.", "success", database_path))

    _sample_referenced_files(result, dataset_root, sample_rows)
    return result


def _sample_referenced_files(
    result: _CsvValidationResult,
    dataset_root: Path,
    sample_rows: list[dict[str, str]],
) -> None:
    checked = 0
    existing = 0
    missing = 0
    unreadable = 0

    for row in sample_rows:
        for column in PATH_COLUMNS:
            if checked >= SAMPLE_FILE_LIMIT:
                break
            raw_value = _path_value(column, row)
            if not raw_value:
                continue
            checked += 1
            status = resolve_database_path(dataset_root, raw_value)
            if column.startswith("nifti") or column == "filename":
                result.has_nifti = result.has_nifti or status.status == "exists"
            elif column.startswith("seg"):
                result.has_seg = result.has_seg or status.status == "exists"
            elif column.startswith("voi"):
                result.has_voi = result.has_voi or status.status == "exists"

            if status.status == "exists":
                existing += 1
            elif status.status == "unreadable":
                unreadable += 1
            elif status.status == "missing":
                missing += 1
        if checked >= SAMPLE_FILE_LIMIT:
            break

    result.sampled_referenced_files = checked
    result.sampled_existing_files = existing

    if checked == 0:
        result.warnings.append(
            _message("no_sample_paths", "No referenced CT/SEG/VOI paths were present in the sampled rows.", "warning")
        )
        return

    result.successes.append(
        _message(
            "sample_complete",
            f"Sampled {checked} referenced paths without loading image volumes.",
            "success",
        )
    )
    if missing:
        result.warnings.append(
            _message(
                "sample_missing_paths",
                f"{missing} sampled referenced paths did not resolve on the backend filesystem.",
                "warning",
            )
        )
    if unreadable:
        result.warnings.append(
            _message(
                "sample_unreadable_paths",
                f"{unreadable} sampled referenced paths exist but are not readable.",
                "warning",
            )
        )
    if existing == 0:
        result.warnings.append(
            _message(
                "sample_no_existing_paths",
                "No sampled referenced CT/SEG/VOI files were found. Check that host paths are mounted as backend paths.",
                "warning",
            )
        )

    if not result.has_nifti:
        result.warnings.append(_message("nifti_not_seen", "NIfTI availability was not confirmed in the sample.", "warning"))
    if not result.has_seg:
        result.warnings.append(_message("seg_not_seen", "SEG availability was not confirmed in the sample.", "warning"))
    if not result.has_voi:
        result.warnings.append(_message("voi_not_seen", "VOI availability was not confirmed in the sample.", "warning"))


def _missing_column_messages(
    statuses: list[RequiredColumnStatus],
    path: Path,
) -> list[SelectionValidationMessage]:
    messages: list[SelectionValidationMessage] = []
    for status in statuses:
        alternatives = ", ".join(status.alternatives)
        messages.append(
            _message(
                "missing_required_column",
                f"Required column '{status.name}' is missing. Accepted field names: {alternatives}.",
                "error",
                path,
            )
        )
    return messages


def _path_value(column: str, row: dict[str, str]) -> str | None:
    value = (row.get(column) or "").strip()
    if not value:
        return None
    if column == "filename":
        return f"nifti/{value}"
    return value


def _check_directory(path: Path, errors: list[SelectionValidationMessage], *, label: str) -> None:
    if not path.exists():
        errors.append(_message("path_missing", f"{label} does not exist.", "error", path))
    elif not path.is_dir():
        errors.append(_message("path_not_directory", f"{label} is not a directory.", "error", path))
    elif not os.access(path, os.R_OK):
        errors.append(_message("path_unreadable", f"{label} is not readable.", "error", path))


def _check_database_file(path: Path, errors: list[SelectionValidationMessage]) -> None:
    if path.name != "database.csv":
        errors.append(_message("not_database_csv", "Select a file named database.csv.", "error", path))
    elif not path.exists():
        errors.append(_message("database_missing", "database.csv does not exist.", "error", path))
    elif not path.is_file():
        errors.append(_message("database_not_file", "Selected database.csv path is not a file.", "error", path))
    elif not os.access(path, os.R_OK):
        errors.append(_message("database_unreadable", "database.csv is not readable.", "error", path))


def _infer_dataset_root(database_path: Path) -> Path | None:
    parent = database_path.parent.resolve()
    candidates = _candidate_dataset_roots(parent)
    if not candidates:
        return parent if parent.is_dir() and os.access(parent, os.R_OK) else None

    sample_paths = _sample_database_path_values(database_path)
    scored: list[tuple[Path, int]] = [
        (candidate, _candidate_path_score(candidate, sample_paths))
        for candidate in candidates
    ]
    best_score = max(score for _candidate, score in scored)

    if best_score > 0:
        winners = [candidate for candidate, score in scored if score == best_score]
        return winners[0] if len(winners) == 1 else None

    if _candidate_has_dataset_marker(parent):
        return parent

    exact_root_matches = [
        candidate
        for candidate in candidates
        if (candidate / "database.csv").resolve(strict=False) == database_path
    ]
    if len(exact_root_matches) == 1:
        return exact_root_matches[0]
    return parent if parent.is_dir() and os.access(parent, os.R_OK) else None


def _candidate_dataset_roots(parent: Path) -> list[Path]:
    candidates: list[Path] = []
    if parent.is_dir() and os.access(parent, os.R_OK):
        candidates.append(parent)

    for root in dataset_browser_roots():
        if not root.exists or not root.readable:
            continue
        root_path = _resolve(root.path)
        candidates.append(root_path)
        try:
            children = list(root_path.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_dir() and os.access(child, os.R_OK) and _candidate_has_dataset_marker(child):
                candidates.append(child.resolve())

    return _dedupe_paths(candidates)


def _sample_database_path_values(database_path: Path) -> list[str]:
    values: list[str] = []
    try:
        with database_path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            for row_index, row in enumerate(reader):
                if row_index >= SAMPLE_ROW_LIMIT or len(values) >= SAMPLE_FILE_LIMIT:
                    break
                for column in PATH_COLUMNS:
                    raw = _path_value(column, {key: value or "" for key, value in row.items()})
                    if raw:
                        values.append(raw)
                        if len(values) >= SAMPLE_FILE_LIMIT:
                            break
    except (csv.Error, OSError):
        return []
    return values


def _candidate_path_score(candidate: Path, sample_paths: list[str]) -> int:
    if not sample_paths:
        return 0
    score = 0
    for raw_value in sample_paths:
        if resolve_database_path(candidate, raw_value).status == "exists":
            score += 1
    return score


def _candidate_has_dataset_marker(path: Path) -> bool:
    return any((path / marker).exists() for marker in DATASET_MARKERS)


def _maybe_has_dataset_structure(path: Path) -> bool:
    if path.is_file():
        return path.name == "database.csv" or path.name == "manifest.csv"
    if not path.is_dir() or not os.access(path, os.R_OK):
        return False
    return any((path / marker).exists() for marker in DATASET_MARKERS)


def _browser_parent(path: Path, root: DatasetBrowserRoot) -> str | None:
    root_path = _resolve(root.path)
    if path == root_path:
        return None
    parent = path.parent.resolve()
    return str(parent) if _is_within(parent, root_path) else None


def _matching_root(path: Path, roots: Iterable[DatasetBrowserRoot]) -> DatasetBrowserRoot | None:
    for root in roots:
        if not root.exists or not root.readable:
            continue
        root_path = _resolve(root.path)
        if _is_within(path, root_path):
            return root
    return None


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _dedupe_roots(candidates: list[tuple[str, str, str, bool]]) -> list[DatasetBrowserRoot]:
    seen: set[str] = set()
    roots: list[DatasetBrowserRoot] = []
    for source, label, raw_path, require_exists in candidates:
        if not raw_path:
            continue
        path = _resolve(raw_path)
        exists = path.is_dir()
        if require_exists and not exists:
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        roots.append(
            DatasetBrowserRoot(
                label=label,
                path=key,
                source=source,
                exists=exists,
                readable=exists and os.access(path, os.R_OK),
            )
        )
    return roots


def _split_roots(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []
    roots: list[str] = []
    for chunk in raw_value.replace("\n", ",").split(","):
        if os.pathsep in chunk:
            roots.extend(part.strip() for part in chunk.split(os.pathsep) if part.strip())
        elif chunk.strip():
            roots.append(chunk.strip())
    return roots


def _resolve(raw_path: str | Path) -> Path:
    return Path(raw_path).expanduser().resolve()


def _clean_path(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    deduped: list[Path] = []
    for path in paths:
        key = str(path.resolve(strict=False))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path.resolve(strict=False))
    return deduped


def _message(
    code: str,
    message: str,
    severity: ValidationSeverity,
    path: Path | None = None,
) -> SelectionValidationMessage:
    return SelectionValidationMessage(
        code=code,
        message=message,
        severity=severity,
        path=str(path) if path is not None else None,
    )


def _response(
    summary: WorkspaceSelectionSummary,
    successes: list[SelectionValidationMessage],
    warnings: list[SelectionValidationMessage],
    errors: list[SelectionValidationMessage],
    *,
    requires_dataset_root: bool = False,
) -> WorkspaceSelectionValidationResponse:
    return WorkspaceSelectionValidationResponse(
        valid=not errors,
        activated=False,
        requires_dataset_root=requires_dataset_root,
        summary=summary,
        successes=successes,
        warnings=warnings,
        errors=errors,
    )
