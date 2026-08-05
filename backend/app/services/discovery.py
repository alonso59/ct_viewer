from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from threading import RLock
from typing import Any

from app.models.dataset import DatasetSummary, PatientSummary, SeriesInfo, SeriesSource
from app.services.converter_metadata import (
    canonical_scan_key,
    read_voi_catalog_rows,
    metadata_rows_by_scan_key,
    metadata_rows_by_filename,
    phase_overrides_by_scan_key,
    resolve_curated_phase,
    select_converter_phase,
    text_value,
)


CASE_ID_PATTERN = re.compile(r"(case_\d{5})")
LATERALITY_PATTERN = re.compile(r"_(?:side)?([LR])$", re.IGNORECASE)
NIFTI_SUFFIXES = (".nii.gz", ".nii")
PHASE_ORDER = {
    "NP": 0,
    "CMP": 1,
    "NC": 2,
    "DELAY": 3,
    "UNDEFINED": 4,
    "DELETED": 5,
}
PHASE_NORMALIZATION = {
    "nc": "NC",
    "noncontrast": "NC",
    "art": "CMP",
    "arterial": "CMP",
    "cmp": "CMP",
    "ven": "NP",
    "venous": "NP",
    "np": "NP",
    "nephrographic": "NP",
    "delay": "DELAY",
    "delayed": "DELAY",
    "ep": "DELAY",
    "ex": "DELAY",
    "exc": "DELAY",
    "excretory": "DELAY",
    "unknown": "UNDEFINED",
    "unk": "UNDEFINED",
    "undefined": "UNDEFINED",
    "deleted": "DELETED",
}


@dataclass
class DatasetIndex:
    dataset_path: Path
    patient_summaries: list[PatientSummary]
    series_by_patient: dict[str, list[SeriesInfo]]
    source_by_id: dict[tuple[str, str], list[SeriesSource]]
    source_by_storage_key: dict[tuple[str, str, str | None], SeriesSource]


_DISCOVERY_INDEX: dict[str, DatasetIndex] = {}
_DISCOVERY_LOCK = RLock()


def resolve_dataset_path(data_root: Path | str, dataset_id: str) -> Path:
    root = Path(data_root).expanduser().resolve()
    dataset_path = (root / dataset_id).resolve()

    if not dataset_path.is_relative_to(root):
        raise ValueError(f"Dataset '{dataset_id}' resolves outside DATA_ROOT")
    if not dataset_path.is_dir():
        raise FileNotFoundError(f"Dataset '{dataset_id}' not found")

    return dataset_path


def reset_discovery_index() -> None:
    with _DISCOVERY_LOCK:
        _DISCOVERY_INDEX.clear()


def list_datasets(data_root: Path | str) -> list[DatasetSummary]:
    root = Path(data_root).expanduser().resolve()
    if not root.exists():
        return []

    dataset_candidates: list[Path]
    if any((root / marker).exists() for marker in ("nifti", "seg", "voi", "metadata.jsonl")):
        dataset_candidates = [root]
    else:
        dataset_candidates = sorted(
            (path for path in root.iterdir() if path.is_dir() and path.name.startswith("Dataset")),
            key=lambda path: path.name,
        )

    datasets: list[DatasetSummary] = []
    for dataset_path in dataset_candidates:
        has_nifti = (dataset_path / "nifti").is_dir()
        has_seg = (dataset_path / "seg").is_dir()
        has_voi = (dataset_path / "voi").is_dir()
        has_metadata = (dataset_path / "metadata.jsonl").is_file()
        has_voi_catalog = (dataset_path / "voi" / "voi_catalog.jsonl").is_file()

        try:
            patient_count = len(_get_dataset_index(dataset_path).patient_summaries)
        except Exception:
            patient_count = 0

        datasets.append(
            DatasetSummary(
                dataset_id=dataset_path.name,
                patient_count=patient_count,
                has_nifti=has_nifti,
                has_seg=has_seg,
                has_voi=has_voi,
                has_metadata=has_metadata,
                has_voi_catalog=has_voi_catalog,
            )
        )

    return datasets


def discover_patients(dataset_path: Path | str) -> list[PatientSummary]:
    index = _get_dataset_index(dataset_path)
    return list(index.patient_summaries)


def discover_series(dataset_path: Path | str, patient_id: str) -> list[SeriesInfo]:
    index = _get_dataset_index(dataset_path)
    return list(index.series_by_patient.get(patient_id, []))

def resolve_series_source(
    dataset_path: Path | str,
    patient_id: str,
    series_id: str,
    storage_path: str | None = None,
) -> SeriesSource:
    index = _get_dataset_index(dataset_path)
    if storage_path is not None:
        source = index.source_by_storage_key.get((patient_id, series_id, storage_path))
        if source is not None:
            return source
    else:
        sources = index.source_by_id.get((patient_id, series_id), [])
        if sources:
            return sources[0]

    raise FileNotFoundError(
        f"Series '{series_id}' for patient '{patient_id}' was not found in {Path(dataset_path).expanduser().resolve().name}"
    )


def _get_dataset_index(dataset_path: Path | str) -> DatasetIndex:
    resolved = Path(dataset_path).expanduser().resolve()
    cache_key = str(resolved)
    with _DISCOVERY_LOCK:
        cached = _DISCOVERY_INDEX.get(cache_key)
        if cached is not None:
            return cached
        index = _build_dataset_index(resolved)
        _DISCOVERY_INDEX[cache_key] = index
        return index


def _build_dataset_index(dataset_path: Path) -> DatasetIndex:
    entries = _collect_series_entries(dataset_path)
    patients: dict[str, dict[str, Any]] = {}
    series_by_patient: dict[str, list[SeriesInfo]] = {}
    source_by_id: dict[tuple[str, str], list[SeriesSource]] = {}
    source_by_storage_key: dict[tuple[str, str, str | None], SeriesSource] = {}

    for entry in entries:
        patient = patients.setdefault(
            entry["patient_id"],
            {
                "patient_id": entry["patient_id"],
                "source_patient_id": None,
                "group": None,
                "phases": set(),
                "series_count": 0,
                "seg_count": 0,
                "voi_count": 0,
                "has_deleted": False,
                "deleted_series_count": 0,
            },
        )
        patient["series_count"] += 1
        if entry["type"] == "nifti":
            patient["seg_count"] += int(entry["has_seg"])
        else:
            patient["voi_count"] += 1
        patient["has_deleted"] = patient["has_deleted"] or bool(entry.get("deleted"))
        patient["deleted_series_count"] += int(bool(entry.get("deleted")))
        _merge_patient_metadata(patient, entry)

        series_info = SeriesInfo(
            series_id=entry["series_id"],
            patient_id=entry["patient_id"],
            type=entry["type"],
            case_id=entry.get("case_id"),
            scan_idx=entry.get("scan_idx"),
            voi_id=entry.get("voi_id"),
            group=entry["group"],
            phase=entry["phase"],
            phase_source=entry.get("phase_source"),
            laterality=entry.get("laterality"),
            side=entry.get("side"),
            filename=entry["filename"],
            image_path=entry.get("image_path"),
            mask_path=entry.get("mask_path"),
            has_seg=entry["has_seg"],
            deleted=bool(entry.get("deleted")),
            storage_path=entry.get("storage_path"),
        )
        series_by_patient.setdefault(entry["patient_id"], []).append(series_info)

        source = SeriesSource(
            series_id=entry["series_id"],
            patient_id=entry["patient_id"],
            type=entry["type"],
            case_id=entry.get("case_id"),
            scan_idx=entry.get("scan_idx"),
            voi_id=entry.get("voi_id"),
            group=entry["group"],
            phase=entry["phase"],
            phase_source=entry.get("phase_source"),
            laterality=entry.get("laterality"),
            side=entry.get("side"),
            filename=entry["filename"],
            image_path=entry["image_path"],
            mask_path=entry["mask_path"],
            has_seg=entry["has_seg"],
            deleted=bool(entry.get("deleted")),
            storage_path=entry.get("storage_path"),
        )
        source_by_id.setdefault((entry["patient_id"], entry["series_id"]), []).append(source)
        source_by_storage_key[
            (entry["patient_id"], entry["series_id"], entry.get("storage_path"))
        ] = source

    patient_summaries = [
        PatientSummary(
            patient_id=patient["patient_id"],
            source_patient_id=patient["source_patient_id"],
            group=patient["group"],
            phases=sorted(patient["phases"], key=_phase_sort_key),
            series_count=patient["series_count"],
            seg_count=patient["seg_count"],
            voi_count=patient["voi_count"],
            has_deleted=patient["has_deleted"],
            deleted_series_count=patient["deleted_series_count"],
        )
        for patient in sorted(patients.values(), key=lambda item: item["patient_id"])
    ]

    return DatasetIndex(
        dataset_path=dataset_path,
        patient_summaries=patient_summaries,
        series_by_patient=series_by_patient,
        source_by_id=source_by_id,
        source_by_storage_key=source_by_storage_key,
    )


def _merge_patient_metadata(patient: dict[str, Any], entry: dict[str, Any]) -> None:
    if entry.get("group"):
        patient["group"] = patient["group"] or entry["group"]
    if entry.get("source_patient_id"):
        patient["source_patient_id"] = patient["source_patient_id"] or entry["source_patient_id"]
    if entry.get("phase"):
        patient["phases"].add(entry["phase"])


def _series_sort_key(entry: dict[str, Any]) -> tuple[int, int, str]:
    series_type_order = 0 if entry["type"] == "nifti" else 1
    deleted_order = 1 if entry.get("deleted") else 0
    return (deleted_order, series_type_order, _phase_sort_key(entry.get("phase")), entry["filename"])


def _phase_sort_key(phase: str | None) -> tuple[int, str]:
    normalized = _normalize_phase(phase)
    return (PHASE_ORDER.get(normalized, 99), normalized)


def _normalize_phase(value: str | None) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        return "UNDEFINED"
    if ";" in cleaned:
        cleaned = cleaned.split(";", 1)[0].strip()
    key = cleaned.lower().replace(" ", "").replace("_", "-")
    return PHASE_NORMALIZATION.get(key, cleaned.upper())


def _extract_patient_id(case_name: str) -> str:
    match = CASE_ID_PATTERN.search(case_name)
    return match.group(1) if match else case_name


def _extract_laterality(name: str) -> str | None:
    match = LATERALITY_PATTERN.search(name)
    if not match:
        return None
    return match.group(1).upper()


def _strip_nifti_suffix(filename: str) -> str:
    for suffix in NIFTI_SUFFIXES:
        if filename.endswith(suffix):
            return filename[: -len(suffix)]
    return Path(filename).stem


def _nifti_files(nifti_dir: Path, patient_filter: str | None = None) -> list[Path]:
    if patient_filter:
        files = [
            path
            for path in nifti_dir.glob(f"*{patient_filter}*")
            if path.is_file() and any(path.name.endswith(suffix) for suffix in NIFTI_SUFFIXES)
        ]
        return sorted(files, key=lambda path: path.name)

    files: list[Path] = []
    for path in nifti_dir.iterdir():
        if path.is_file() and any(path.name.endswith(suffix) for suffix in NIFTI_SUFFIXES):
            files.append(path)
    return sorted(files, key=lambda path: path.name)


def _find_seg_path(dataset_path: Path, image_stem: str) -> Path | None:
    seg_dir = dataset_path / "seg"
    if not seg_dir.is_dir():
        return None

    seg_stem = re.sub(r"_0000$", "", image_stem)
    for suffix in NIFTI_SUFFIXES:
        candidate = seg_dir / f"{seg_stem}{suffix}"
        if candidate.exists():
            return candidate
    return None


def _relative_storage_path(dataset_path: Path, file_path: Path) -> str:
    return str(file_path.resolve().relative_to(dataset_path.resolve()))


def _collect_nifti_entries(
    dataset_path: Path,
    patient_filter: str | None = None,
) -> list[dict[str, Any]]:
    nifti_dir = dataset_path / "nifti"
    if not nifti_dir.is_dir():
        return []

    metadata_index = metadata_rows_by_filename(dataset_path)
    phase_overrides = phase_overrides_by_scan_key(dataset_path)
    entries: list[dict[str, Any]] = []
    for image_path in _nifti_files(nifti_dir, patient_filter=patient_filter):
        filename = image_path.name
        image_stem = _strip_nifti_suffix(filename)
        metadata_row = metadata_index.get(filename, {})
        case_id = text_value(metadata_row.get("case_id")) or _extract_patient_id(image_stem)
        scan_idx = text_value(metadata_row.get("scan_idx"))
        curated_phase = resolve_curated_phase(phase_overrides, case_id, scan_idx)
        if curated_phase:
            phase_value, phase_source = curated_phase, "phase.json"
        else:
            phase_value, phase_source = select_converter_phase(metadata_row)
        patient_id = (
            text_value(metadata_row.get("case_id"))
            or _extract_patient_id(image_stem)
        )
        if patient_filter and patient_id != patient_filter:
            continue
        source_patient_id = text_value(metadata_row.get("patient_id")) or None
        group = text_value(metadata_row.get("group")) or "NG"
        phase = _normalize_phase(phase_value)
        seg_path = _find_seg_path(dataset_path, image_stem)

        entries.append(
            {
                "series_id": f"nifti:{image_stem}",
                "patient_id": patient_id,
                "case_id": patient_id,
                "scan_idx": scan_idx or None,
                "voi_id": None,
                "source_patient_id": source_patient_id,
                "type": "nifti",
                "group": group,
                "phase": phase,
                "phase_source": phase_source or None,
                "laterality": None,
                "side": None,
                "filename": filename,
                "image_path": str(image_path),
                "mask_path": str(seg_path) if seg_path else None,
                "has_seg": seg_path is not None,
                "deleted": False,
                "storage_path": _relative_storage_path(dataset_path, image_path),
            }
        )

    return entries


def _resolve_voi_catalog_path(dataset_path: Path, raw_path: str | None) -> Path | None:
    value = text_value(raw_path)
    if not value:
        return None
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    if candidate.parts and candidate.parts[0] == "voi":
        return dataset_path / candidate
    return dataset_path / "voi" / candidate


def _catalog_image_path_value(row: dict[str, Any]) -> str:
    return text_value(row.get("voi_image_path")) or text_value(row.get("image_path"))


def _catalog_mask_path_value(row: dict[str, Any]) -> str:
    return text_value(row.get("voi_mask_path")) or text_value(row.get("mask_path"))


def _collect_voi_entries(
    dataset_path: Path,
    patient_filter: str | None = None,
) -> list[dict[str, Any]]:
    phase_overrides = phase_overrides_by_scan_key(dataset_path)
    metadata_rows = metadata_rows_by_scan_key(dataset_path)
    entries: list[dict[str, Any]] = []
    for row in read_voi_catalog_rows(dataset_path):
        case_id = text_value(row.get("case_id"))
        scan_idx = text_value(row.get("scan_idx"))
        if not case_id or not scan_idx or (patient_filter and case_id != patient_filter):
            continue
        phase_value = resolve_curated_phase(phase_overrides, case_id, scan_idx)
        if not phase_value:
            key = canonical_scan_key(case_id, scan_idx)
            metadata_row = metadata_rows.get(key, {}) if key is not None else {}
            phase_value, _phase_source = select_converter_phase(metadata_row)
        if not phase_value:
            continue
        image_path = _resolve_voi_catalog_path(dataset_path, _catalog_image_path_value(row))
        if image_path is None or not image_path.exists():
            continue
        mask_path = _resolve_voi_catalog_path(dataset_path, _catalog_mask_path_value(row))
        filename = image_path.name
        stem = image_path.stem
        side = text_value(row.get("side")) or _extract_laterality(stem)
        group = text_value(row.get("group")) or "NG"
        voi_id = text_value(row.get("voi_id")) or f"{case_id}/{scan_idx}/{side or stem}"

        entries.append(
            {
                "series_id": f"voi:{voi_id}",
                "patient_id": case_id,
                "case_id": case_id,
                "scan_idx": scan_idx,
                "voi_id": voi_id,
                "source_patient_id": text_value(row.get("patient_id")) or None,
                "type": "voi",
                "group": group,
                "phase": _normalize_phase(phase_value),
                "phase_source": "phase.json",
                "laterality": side,
                "side": side,
                "filename": filename,
                "image_path": str(image_path),
                "mask_path": str(mask_path) if mask_path and mask_path.exists() else None,
                "has_seg": bool(mask_path and mask_path.exists()),
                "deleted": False,
                "storage_path": _relative_storage_path(dataset_path, image_path),
            }
        )

    return entries


def _collect_deleted_nifti_entries(
    dataset_path: Path,
    patient_filter: str | None = None,
) -> list[dict[str, Any]]:
    deleted_nifti_dir = dataset_path / "deleted" / "nifti"
    if not deleted_nifti_dir.is_dir():
        return []

    metadata_index = metadata_rows_by_filename(dataset_path)
    phase_overrides = phase_overrides_by_scan_key(dataset_path)
    entries: list[dict[str, Any]] = []
    for image_path in _nifti_files(deleted_nifti_dir, patient_filter=patient_filter):
        filename = image_path.name
        image_stem = _strip_nifti_suffix(filename)
        metadata_row = metadata_index.get(filename, {})
        case_id = text_value(metadata_row.get("case_id")) or _extract_patient_id(image_stem)
        scan_idx = text_value(metadata_row.get("scan_idx"))
        curated_phase = resolve_curated_phase(phase_overrides, case_id, scan_idx)
        if curated_phase:
            phase_value, phase_source = curated_phase, "phase.json"
        else:
            phase_value, phase_source = select_converter_phase(metadata_row)
        patient_id = (
            text_value(metadata_row.get("case_id"))
            or _extract_patient_id(image_stem)
        )
        if patient_filter and patient_id != patient_filter:
            continue
        source_patient_id = text_value(metadata_row.get("patient_id")) or None
        group = text_value(metadata_row.get("group")) or "NG"
        phase = _normalize_phase(phase_value)
        mask_path = next(
            (
                candidate
                for suffix in NIFTI_SUFFIXES
                for candidate in [dataset_path / "deleted" / "seg" / f"{re.sub(r'_0000$', '', image_stem)}{suffix}"]
                if candidate.exists()
            ),
            None,
        )
        entries.append(
            {
                "series_id": f"nifti:{image_stem}",
                "patient_id": patient_id,
                "case_id": patient_id,
                "scan_idx": scan_idx or None,
                "voi_id": None,
                "source_patient_id": source_patient_id,
                "type": "nifti",
                "group": group,
                "phase": phase,
                "phase_source": phase_source or None,
                "laterality": None,
                "side": None,
                "filename": filename,
                "image_path": str(image_path),
                "mask_path": str(mask_path) if mask_path else None,
                "has_seg": mask_path is not None,
                "deleted": True,
                "storage_path": _relative_storage_path(dataset_path, image_path),
            }
        )
    return entries


def _collect_deleted_voi_entries(
    dataset_path: Path,
    patient_filter: str | None = None,
) -> list[dict[str, Any]]:
    recycle_image_root = dataset_path / "voi" / "deleted" / "images"
    recycle_mask_root = dataset_path / "voi" / "deleted" / "mask"
    phase_overrides = phase_overrides_by_scan_key(dataset_path)
    metadata_rows = metadata_rows_by_scan_key(dataset_path)
    entries: list[dict[str, Any]] = []
    for row in read_voi_catalog_rows(dataset_path):
        case_id = text_value(row.get("case_id"))
        scan_idx = text_value(row.get("scan_idx"))
        if not case_id or not scan_idx or (patient_filter and case_id != patient_filter):
            continue
        phase_value = resolve_curated_phase(phase_overrides, case_id, scan_idx)
        if not phase_value:
            key = canonical_scan_key(case_id, scan_idx)
            metadata_row = metadata_rows.get(key, {}) if key is not None else {}
            phase_value, _phase_source = select_converter_phase(metadata_row)
        if not phase_value:
            continue
        active_image_path = _resolve_voi_catalog_path(dataset_path, _catalog_image_path_value(row))
        if active_image_path is None:
            continue
        try:
            active_relative = active_image_path.relative_to(dataset_path / "voi" / "images")
        except ValueError:
            continue
        image_path = recycle_image_root / active_relative
        if not image_path.exists():
            continue
        active_mask_path = _resolve_voi_catalog_path(dataset_path, _catalog_mask_path_value(row))
        mask_relative: Path | None = None
        if active_mask_path is not None:
            try:
                mask_relative = active_mask_path.relative_to(dataset_path / "voi" / "mask")
            except ValueError:
                mask_relative = None
        mask_path = recycle_mask_root / mask_relative if mask_relative is not None else None
        filename = image_path.name
        stem = image_path.stem
        side = text_value(row.get("side")) or _extract_laterality(stem)
        group = text_value(row.get("group")) or "NG"
        voi_id = text_value(row.get("voi_id")) or f"{case_id}/{scan_idx}/{side or stem}"
        entries.append(
            {
                "series_id": f"voi:{voi_id}",
                "patient_id": case_id,
                "case_id": case_id,
                "scan_idx": scan_idx,
                "voi_id": voi_id,
                "source_patient_id": text_value(row.get("patient_id")) or None,
                "type": "voi",
                "group": group,
                "phase": _normalize_phase(phase_value),
                "phase_source": "phase.json",
                "laterality": side,
                "side": side,
                "filename": filename,
                "image_path": str(image_path),
                "mask_path": str(mask_path) if mask_path and mask_path.exists() else None,
                "has_seg": bool(mask_path and mask_path.exists()),
                "deleted": True,
                "storage_path": _relative_storage_path(dataset_path, image_path),
            }
        )
    return entries


def _collect_series_entries(dataset_path: Path, patient_filter: str | None = None) -> list[dict[str, Any]]:
    nifti_entries = _collect_nifti_entries(dataset_path, patient_filter=patient_filter)
    voi_entries = _collect_voi_entries(dataset_path, patient_filter=patient_filter)
    deleted_nifti_entries = _collect_deleted_nifti_entries(dataset_path, patient_filter=patient_filter)
    deleted_voi_entries = _collect_deleted_voi_entries(dataset_path, patient_filter=patient_filter)
    return sorted(
        nifti_entries + voi_entries + deleted_nifti_entries + deleted_voi_entries,
        key=_series_sort_key,
    )
