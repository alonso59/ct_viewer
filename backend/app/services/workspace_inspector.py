from __future__ import annotations

import csv
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

import nibabel as nib
import numpy as np

from app.models.workspace import (
    DatasetKind,
    InspectionSeverity,
    WorkspaceInspection,
    WorkspaceInspectionSummary,
    WorkspaceInspectionWarning,
    WorkspaceMarkers,
    WorkspaceStateInspection,
)
from app.services.path_policy import (
    dataset_key,
    file_access_status,
    is_path_allowed,
    is_path_value_valid,
    resolve_dataset_path_input,
)
from app.services.state_dir import dataset_state_dir


MAX_INSPECTION_ENTRIES = 100_000
MAX_INSPECTION_DEPTH = 6
MAX_WARNING_DETAILS = 100
NIFTI_SUFFIXES = (".nii.gz", ".nii")
VOLUME_REFERENCE_FIELDS = ("nifti_path", "nifti_original_volume_path", "nifti_file")


class InspectionLimitExceeded(RuntimeError):
    pass


@dataclass
class _ScanBudget:
    entries: int = 0

    def consume(self) -> None:
        self.entries += 1
        if self.entries > MAX_INSPECTION_ENTRIES:
            raise InspectionLimitExceeded


@dataclass
class _WarningCollector:
    details: list[WorkspaceInspectionWarning] = field(default_factory=list)
    total: int = 0

    def add(
        self,
        code: str,
        message: str,
        severity: InspectionSeverity = "warning",
    ) -> None:
        self.total += 1
        if len(self.details) < MAX_WARNING_DETAILS:
            self.details.append(
                WorkspaceInspectionWarning(code=code, message=message, severity=severity)
            )


@dataclass
class _Inventory:
    case_ids: set[str] = field(default_factory=set)
    nifti_paths: set[Path] = field(default_factory=set)
    nifti_by_name: dict[str, Path] = field(default_factory=dict)
    voi_image_paths: set[Path] = field(default_factory=set)
    segmentation_paths: set[Path] = field(default_factory=set)
    voi_mask_paths: set[Path] = field(default_factory=set)
    canonical_paths: set[Path] = field(default_factory=set)
    converter_paths: set[Path] = field(default_factory=set)
    legacy_paths: set[Path] = field(default_factory=set)
    invalid_paths: set[Path] = field(default_factory=set)

    @property
    def volume_paths(self) -> set[Path]:
        return self.nifti_paths | self.voi_image_paths


def inspect_workspace_dataset_path(raw_path: str) -> WorkspaceInspection:
    dataset_path = resolve_dataset_path_input(raw_path)
    markers = WorkspaceMarkers(
        database_csv=(dataset_path / "database.csv").is_file(),
        metadata_jsonl=(dataset_path / "metadata.jsonl").is_file(),
        manifest_csv=(dataset_path / "manifest.csv").is_file(),
        nifti=(dataset_path / "nifti").is_dir(),
        seg=(dataset_path / "seg").is_dir(),
        voi=(dataset_path / "voi").is_dir(),
    )
    warnings = _WarningCollector()
    inventory = _Inventory()
    budget = _ScanBudget()
    limit_exceeded = False

    try:
        if markers.database_csv:
            _inspect_database_csv(dataset_path, inventory, warnings, budget)
        if markers.metadata_jsonl:
            _inspect_metadata_jsonl(dataset_path, inventory, warnings, budget)
        if markers.manifest_csv:
            _inspect_manifest_csv(dataset_path, inventory, warnings, budget)

        root_nifti = _inspect_direct_volumes(
            dataset_path,
            inventory,
            warnings,
            budget,
            volume_kind="nifti",
        )
        markers.nifti = markers.nifti or root_nifti > 0
        if (dataset_path / "nifti").is_dir():
            _inspect_direct_volumes(
                dataset_path / "nifti",
                inventory,
                warnings,
                budget,
                volume_kind="nifti",
            )
        if markers.seg:
            _inspect_direct_masks(
                dataset_path / "seg",
                inventory.segmentation_paths,
                inventory,
                warnings,
                budget,
            )
        if markers.voi:
            _inspect_voi_tree(dataset_path, inventory, warnings, budget)
    except InspectionLimitExceeded:
        limit_exceeded = True
        warnings.add(
            "inspection_limit_exceeded",
            f"Inspection exceeded the limit of {MAX_INSPECTION_ENTRIES:,} entries or rows.",
            "error",
        )

    dataset_kind = _classify_dataset(markers, inventory)
    if dataset_kind == "incomplete":
        warnings.add(
            "no_visualizable_volume",
            "Recognized dataset content was found, but no readable visualizable volume could be resolved.",
            "error",
        )
    elif dataset_kind == "unsupported":
        warnings.add(
            "unsupported_dataset",
            "No supported dataset structure or visualizable volume was found.",
            "error",
        )

    valid = dataset_kind not in {"incomplete", "unsupported"} and not limit_exceeded
    state_path = dataset_state_dir(dataset_path)
    summary = WorkspaceInspectionSummary(
        case_count=len(inventory.case_ids),
        volume_count=len(inventory.volume_paths),
        nifti_count=len(inventory.nifti_paths),
        voi_image_count=len(inventory.voi_image_paths),
        segmentation_count=len(inventory.segmentation_paths),
        voi_mask_count=len(inventory.voi_mask_paths),
        warning_count=warnings.total,
        warnings_truncated=warnings.total > len(warnings.details),
    )
    return WorkspaceInspection(
        valid=valid,
        dataset_path=str(dataset_path),
        dataset_id=dataset_path.name,
        dataset_key=dataset_key(dataset_path),
        dataset_kind=dataset_kind,
        markers=markers,
        summary=summary,
        state=WorkspaceStateInspection(
            path=str(state_path),
            exists=state_path.is_dir(),
            writable=_can_write_state_without_creating(state_path),
        ),
        warnings=warnings.details,
    )


def _inspect_database_csv(
    dataset_path: Path,
    inventory: _Inventory,
    warnings: _WarningCollector,
    budget: _ScanBudget,
) -> None:
    path = dataset_path / "database.csv"
    readable_path = _allowed_readable_file(path, warnings)
    if readable_path is None:
        return
    try:
        with readable_path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                budget.consume()
                case_id = (row.get("case_id") or row.get("patient_id") or "").strip()
                if case_id:
                    inventory.case_ids.add(case_id)
                volume_references = list(_database_volume_references(row))
                if volume_references:
                    resolved = _resolve_reference_options(
                        dataset_path,
                        volume_references,
                        warnings,
                    )
                    if resolved and _add_volume(resolved, "nifti", inventory, warnings):
                        inventory.canonical_paths.add(resolved)
                raw_voi = (row.get("voi_image_path") or "").strip()
                if raw_voi:
                    resolved = _resolve_reference(dataset_path, raw_voi, warnings)
                    if resolved and _add_volume(resolved, "voi", inventory, warnings):
                        inventory.canonical_paths.add(resolved)
                _inspect_referenced_masks(dataset_path, row, inventory, warnings)
    except (OSError, UnicodeError, csv.Error) as exc:
        warnings.add("invalid_database_csv", f"database.csv could not be read: {exc}", "error")


def _inspect_metadata_jsonl(
    dataset_path: Path,
    inventory: _Inventory,
    warnings: _WarningCollector,
    budget: _ScanBudget,
) -> None:
    path = dataset_path / "metadata.jsonl"
    readable_path = _allowed_readable_file(path, warnings)
    if readable_path is None:
        return
    try:
        with readable_path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                budget.consume()
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    warnings.add(
                        "invalid_metadata_jsonl",
                        f"metadata.jsonl contains invalid JSON at line {line_number}.",
                        "error",
                    )
                    continue
                if not isinstance(row, dict):
                    continue
                case_id = _text(row.get("case_id")) or _text(row.get("patient_id"))
                if case_id:
                    inventory.case_ids.add(case_id)
                raw_options = [
                    _text(row.get("relative_path")),
                    _text(row.get("nifti_file")),
                ]
                if filename := _text(row.get("filename")):
                    raw_options.append(f"nifti/{filename}")
                if any(raw_options):
                    resolved = _resolve_reference_options(dataset_path, raw_options, warnings)
                    if resolved and _add_volume(resolved, "nifti", inventory, warnings):
                        inventory.converter_paths.add(resolved)
                _inspect_referenced_masks(dataset_path, row, inventory, warnings)
    except (OSError, UnicodeError) as exc:
        warnings.add("invalid_metadata_jsonl", f"metadata.jsonl could not be read: {exc}", "error")


def _inspect_manifest_csv(
    dataset_path: Path,
    inventory: _Inventory,
    warnings: _WarningCollector,
    budget: _ScanBudget,
) -> None:
    path = dataset_path / "manifest.csv"
    readable_path = _allowed_readable_file(path, warnings)
    if readable_path is None:
        return
    try:
        with readable_path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                budget.consume()
                case_id = (row.get("case_id") or row.get("patient_id") or "").strip()
                if case_id:
                    inventory.case_ids.add(case_id)
                raw_options = [
                    (row.get("nifti_path") or "").strip(),
                    (row.get("nifti_file") or "").strip(),
                ]
                if filename := (row.get("filename") or "").strip():
                    existing = inventory.nifti_by_name.get(filename)
                    if existing and not any(raw_options):
                        inventory.legacy_paths.add(existing)
                        _inspect_referenced_masks(dataset_path, row, inventory, warnings)
                        continue
                    raw_options.append(f"nifti/{filename}")
                if any(raw_options):
                    resolved = _resolve_reference_options(dataset_path, raw_options, warnings)
                    if resolved and _add_volume(resolved, "nifti", inventory, warnings):
                        inventory.legacy_paths.add(resolved)
                _inspect_referenced_masks(dataset_path, row, inventory, warnings)
    except (OSError, UnicodeError, csv.Error) as exc:
        warnings.add("invalid_manifest_csv", f"manifest.csv could not be read: {exc}", "error")


def _database_volume_references(row: dict[str, str | None]) -> Iterable[str]:
    for field_name in VOLUME_REFERENCE_FIELDS:
        raw = (row.get(field_name) or "").strip()
        if raw:
            yield raw
    if filename := (row.get("filename") or "").strip():
        yield f"nifti/{filename}"


def _inspect_referenced_masks(
    dataset_path: Path,
    row: Mapping[str, object],
    inventory: _Inventory,
    warnings: _WarningCollector,
) -> None:
    for field_name, destination in (
        ("seg_path", inventory.segmentation_paths),
        ("voi_mask_path", inventory.voi_mask_paths),
    ):
        raw_value = _text(row.get(field_name))
        if not raw_value:
            continue
        resolved = _resolve_reference(dataset_path, raw_value, warnings)
        if resolved:
            _add_mask(resolved, destination, inventory, warnings)


def _inspect_direct_volumes(
    root: Path,
    inventory: _Inventory,
    warnings: _WarningCollector,
    budget: _ScanBudget,
    *,
    volume_kind: str,
) -> int:
    if _authorized_directory(root, warnings) is None:
        return 0
    discovered = 0
    try:
        for path in root.iterdir():
            budget.consume()
            if path.is_file() and _is_nifti(path):
                discovered += 1
                if _add_volume(path, volume_kind, inventory, warnings):
                    inventory.case_ids.add(_case_id_from_filename(path.name))
    except OSError as exc:
        warnings.add("unreadable_directory", f"Directory '{root.name}' could not be read: {exc}")
    return discovered


def _inspect_direct_masks(
    root: Path,
    destination: set[Path],
    inventory: _Inventory,
    warnings: _WarningCollector,
    budget: _ScanBudget,
) -> None:
    if _authorized_directory(root, warnings) is None:
        return
    try:
        for path in root.iterdir():
            budget.consume()
            if path.is_file() and (_is_nifti(path) or path.suffix.lower() == ".npy"):
                _add_mask(path, destination, inventory, warnings)
    except OSError as exc:
        warnings.add("unreadable_directory", f"Directory '{root.name}' could not be read: {exc}")


def _inspect_voi_tree(
    dataset_path: Path,
    inventory: _Inventory,
    warnings: _WarningCollector,
    budget: _ScanBudget,
) -> None:
    voi_root = dataset_path / "voi"
    image_root = voi_root / "images"
    if image_root.is_dir():
        for path in _bounded_files(image_root, budget, warnings):
            if path.suffix.lower() != ".npy":
                continue
            if _add_volume(path, "voi", inventory, warnings):
                inventory.legacy_paths.add(path.resolve(strict=False))
                relative = path.relative_to(image_root)
                if len(relative.parts) >= 2:
                    inventory.case_ids.add(relative.parts[1])

    for name in ("mask", "segmentation"):
        mask_root = voi_root / name
        if not mask_root.is_dir():
            continue
        for path in _bounded_files(mask_root, budget, warnings):
            if path.suffix.lower() != ".npy":
                continue
            _add_mask(path, inventory.voi_mask_paths, inventory, warnings)


def _bounded_files(
    root: Path,
    budget: _ScanBudget,
    warnings: _WarningCollector,
) -> Iterable[Path]:
    stack: list[tuple[Path, int]] = [(root, 0)]
    visited: set[Path] = set()
    while stack:
        directory, depth = stack.pop()
        try:
            resolved_directory = directory.resolve(strict=True)
        except OSError:
            warnings.add("unreadable_directory", "A dataset directory could not be resolved.")
            continue
        if not is_path_allowed(resolved_directory):
            warnings.add(
                "forbidden_directory",
                "A discovered directory resolves outside the allowed data roots.",
                "error",
            )
            continue
        if resolved_directory in visited:
            continue
        visited.add(resolved_directory)
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    budget.consume()
                    path = Path(entry.path)
                    if entry.is_file(follow_symlinks=True):
                        yield path
                    elif entry.is_dir(follow_symlinks=True):
                        if depth >= MAX_INSPECTION_DEPTH:
                            raise InspectionLimitExceeded
                        stack.append((path, depth + 1))
        except OSError:
            warnings.add("unreadable_directory", "A dataset directory is not readable.")


def _resolve_reference(
    dataset_path: Path,
    raw_value: str,
    warnings: _WarningCollector,
) -> Path | None:
    return _resolve_reference_options(dataset_path, [raw_value], warnings)


def _resolve_reference_options(
    dataset_path: Path,
    raw_values: Iterable[str],
    warnings: _WarningCollector,
) -> Path | None:
    cleaned_values = [value.strip() for value in raw_values if value.strip()]
    candidates: list[Path] = []
    invalid_reference = False
    for raw_value in cleaned_values:
        if not is_path_value_valid(raw_value):
            invalid_reference = True
            warnings.add(
                "invalid_reference",
                "A referenced path contains a null character or exceeds the maximum length.",
                "error",
            )
            continue
        raw_path = Path(raw_value).expanduser()
        if raw_path.is_absolute():
            candidates.append(raw_path)
            continue
        candidates.append(dataset_path / raw_path)
        candidates.extend(
            parent / raw_path for parent in dataset_path.parents if is_path_allowed(parent)
        )
        if is_path_allowed(Path.cwd()):
            candidates.append(Path.cwd() / raw_path)

    if invalid_reference and not candidates:
        return None

    forbidden = False
    unreadable = False
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=False)
        except OSError:
            continue
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        status = file_access_status(resolved)
        if status == "exists":
            return resolved
        forbidden = forbidden or status == "forbidden"
        unreadable = unreadable or status == "unreadable"

    if unreadable:
        warnings.add("unreadable_reference", "A referenced file is not readable.", "error")
    elif forbidden:
        warnings.add(
            "forbidden_reference",
            "A referenced file resolves outside the allowed data roots.",
            "error",
        )
    else:
        missing_name = Path(cleaned_values[0]).name if cleaned_values else "unknown"
        warnings.add("missing_reference", f"Referenced file was not found: {missing_name}")
    return None


def _add_volume(
    path: Path,
    volume_kind: str,
    inventory: _Inventory,
    warnings: _WarningCollector,
) -> bool:
    resolved = _allowed_readable_file(path, warnings)
    if resolved is None:
        return False
    if resolved in inventory.volume_paths:
        return True
    if resolved in inventory.invalid_paths:
        return False
    if not _valid_volume_header(resolved, warnings):
        inventory.invalid_paths.add(resolved)
        return False
    if volume_kind == "voi":
        inventory.voi_image_paths.add(resolved)
    else:
        inventory.nifti_paths.add(resolved)
        inventory.nifti_by_name.setdefault(resolved.name, resolved)
    return True


def _add_mask(
    path: Path,
    destination: set[Path],
    inventory: _Inventory,
    warnings: _WarningCollector,
) -> bool:
    resolved = _allowed_readable_file(path, warnings)
    if resolved is None:
        return False
    if resolved in destination:
        return True
    if resolved in inventory.invalid_paths:
        return False
    if not _valid_array_header(resolved, "invalid_mask", "Mask", warnings):
        inventory.invalid_paths.add(resolved)
        return False
    destination.add(resolved)
    return True


def _authorized_directory(root: Path, warnings: _WarningCollector) -> Path | None:
    try:
        resolved = root.resolve(strict=True)
    except OSError:
        warnings.add("unreadable_directory", "A dataset directory could not be resolved.")
        return None
    if not is_path_allowed(resolved):
        warnings.add(
            "forbidden_directory",
            "A discovered directory resolves outside the allowed data roots.",
            "error",
        )
        return None
    if not resolved.is_dir() or not os.access(resolved, os.R_OK | os.X_OK):
        warnings.add("unreadable_directory", "A dataset directory is not readable.")
        return None
    return root


def _allowed_readable_file(path: Path, warnings: _WarningCollector) -> Path | None:
    status = file_access_status(path)
    if status == "forbidden":
        warnings.add("forbidden_file", "A discovered file resolves outside the allowed data roots.", "error")
        return None
    if status == "unreadable":
        warnings.add("unreadable_file", f"File is not readable: {path.name}")
        return None
    if status != "exists":
        return None
    return path.resolve(strict=True)


def _valid_volume_header(path: Path, warnings: _WarningCollector) -> bool:
    return _valid_array_header(path, "invalid_volume", "Volume", warnings)


def _valid_array_header(
    path: Path,
    warning_code: str,
    label: str,
    warnings: _WarningCollector,
) -> bool:
    try:
        if path.suffix.lower() == ".npy":
            array = np.load(path, mmap_mode="r", allow_pickle=False)
            shape = array.shape
        else:
            shape = nib.load(str(path)).shape
        if len(shape) < 3 or any(int(size) <= 0 for size in shape[:3]):
            raise ValueError("expected at least three non-empty dimensions")
        return True
    except Exception as exc:
        warnings.add(
            warning_code,
            f"{label} header is invalid for '{path.name}': {exc}",
            "error",
        )
        return False


def _classify_dataset(markers: WorkspaceMarkers, inventory: _Inventory) -> DatasetKind:
    if markers.database_csv and inventory.canonical_paths:
        return "canonical"
    if markers.metadata_jsonl and inventory.converter_paths:
        return "converter_output"
    if markers.manifest_csv and (inventory.legacy_paths or inventory.volume_paths):
        return "legacy"
    if inventory.nifti_paths:
        return "nifti_collection"
    if inventory.voi_image_paths:
        return "voi_collection"
    if any(markers.model_dump().values()):
        return "incomplete"
    return "unsupported"


def _can_write_state_without_creating(state_path: Path) -> bool:
    probe = state_path
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    return probe.is_dir() and os.access(probe, os.W_OK | os.X_OK)


def _case_id_from_filename(filename: str) -> str:
    match = re.search(r"(case_\d{5})", filename)
    if match:
        return match.group(1)
    for suffix in NIFTI_SUFFIXES:
        if filename.endswith(suffix):
            return filename[: -len(suffix)]
    return Path(filename).stem


def _is_nifti(path: Path) -> bool:
    return any(path.name.lower().endswith(suffix) for suffix in NIFTI_SUFFIXES)


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()
