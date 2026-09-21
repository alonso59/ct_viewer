from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

from app.models.database import (
    CaseDossier,
    CaseInventoryRow,
    CaseLoadSource,
    CaseSummary,
    CanonicalPhase,
    PathStatus,
    PhaseStatus,
    QCWarning,
    RequiredColumnStatus,
    Scope,
)
from app.services.converter_metadata import (
    canonical_scan_key,
    has_converter_metadata,
    is_intentionally_skipped_metadata_row,
    metadata_filename,
    phase_overrides_by_scan_key,
    read_voi_catalog_rows,
    read_converter_metadata_rows,
    resolve_curated_phase,
    select_converter_phase,
    text_value,
)
from app.services.path_resolver import path_exists, path_is_unreadable, resolve_database_path


PHASE_PRIORITY: tuple[CanonicalPhase, ...] = ("NP", "CMP", "NC", "DELAY", "UNK")
PHASE_MAPPING: dict[str, CanonicalPhase] = {
    "NC": "NC",
    "NONCONTRAST": "NC",
    "NON-CONTRAST": "NC",
    "ART": "CMP",
    "ARTERIAL": "CMP",
    "CMP": "CMP",
    "CORTICOMEDULLARY": "CMP",
    "VEN": "NP",
    "VENOUS": "NP",
    "NP": "NP",
    "NEPHROGRAPHIC": "NP",
    "DELAY": "DELAY",
    "DELAYED": "DELAY",
    "EP": "DELAY",
    "EX": "DELAY",
    "EXC": "DELAY",
    "EXCRETORY": "DELAY",
}
MISSING_PHASE_VALUES = {"", "UNDEFINED", "UNKNOWN", "UNK", "N/A", "NA", "NONE", "NULL"}
VALID_SIDES = {"L", "R"}
NIFTI_SUFFIXES = (".nii", ".nii.gz")


@dataclass(frozen=True)
class DatabaseRow:
    index: int
    raw: dict[str, str]
    row_id: str
    source_row_id: str | None
    case_id: str
    patient_id: str | None
    group: str | None
    raw_phase: str | None
    canonical_phase: CanonicalPhase
    phase_status: PhaseStatus
    scan_idx: str | None
    side: str | None
    nifti_path: PathStatus
    seg_path: PathStatus
    voi_image_path: PathStatus
    voi_mask_path: PathStatus
    has_seg: bool
    has_voi_image: bool
    has_voi_mask: bool
    qc_warnings: tuple[QCWarning, ...]

    @property
    def has_complete_scope(self) -> bool:
        return self.raw.get("source_index") != "voi/voi_catalog.jsonl" and path_exists(self.nifti_path)

    @property
    def has_voi_scope(self) -> bool:
        return path_exists(self.voi_image_path)

    @property
    def is_intentionally_skipped(self) -> bool:
        return (
            self.raw.get("source_index") == "metadata.jsonl"
            and is_intentionally_skipped_metadata_row(self.raw)
        )


@dataclass(frozen=True)
class DatabaseIndex:
    dataset_id: str
    dataset_path: Path
    has_database: bool
    source_file: str | None
    fieldnames: tuple[str, ...]
    rows: tuple[DatabaseRow, ...]


_DATABASE_CACHE: dict[str, DatabaseIndex] = {}
_DATABASE_LOCK = RLock()


def reset_database_index() -> None:
    with _DATABASE_LOCK:
        _DATABASE_CACHE.clear()


def has_database(dataset_path: Path | str) -> bool:
    resolved = Path(dataset_path).expanduser().resolve()
    return (resolved / "database.csv").is_file() or has_converter_metadata(resolved)


def get_database_index(dataset_path: Path | str) -> DatabaseIndex:
    resolved = Path(dataset_path).expanduser().resolve()
    key = str(resolved)
    with _DATABASE_LOCK:
        cached = _DATABASE_CACHE.get(key)
        if cached is not None:
            return cached
        index = _load_database_index(resolved)
        _DATABASE_CACHE[key] = index
        return index


def list_case_summaries(dataset_path: Path | str) -> list[CaseSummary]:
    index = get_database_index(dataset_path)
    cases: dict[str, list[DatabaseRow]] = {}
    for row in index.rows:
        cases.setdefault(row.case_id, []).append(row)

    summaries: list[CaseSummary] = []
    for case_id, rows in sorted(cases.items(), key=lambda item: item[0]):
        phases = sorted(
            {
                row.canonical_phase
                for row in rows
                if row.has_complete_scope or row.has_voi_scope
            },
            key=lambda phase: PHASE_PRIORITY.index(phase)
            if phase in PHASE_PRIORITY
            else len(PHASE_PRIORITY),
        )
        scans = {
            (row.canonical_phase, row.scan_idx or "")
            for row in rows
            if row.has_complete_scope or row.has_voi_scope
        }
        summaries.append(
            CaseSummary(
                case_id=case_id,
                patient_id=_first_value(row.patient_id for row in rows),
                group=_first_value(row.group for row in rows),
                available_phases=phases,
                scan_count=len(scans),
                skipped_count=sum(row.is_intentionally_skipped for row in rows),
                seg_count=len({row.seg_path.resolved for row in rows if path_exists(row.seg_path)}),
                voi_image_count=len(
                    {row.voi_image_path.resolved for row in rows if path_exists(row.voi_image_path)}
                ),
                voi_mask_count=len(
                    {row.voi_mask_path.resolved for row in rows if path_exists(row.voi_mask_path)}
                ),
                voi_sides=sorted(
                    {row.side for row in rows if row.side in VALID_SIDES},
                    key=lambda value: ("L", "R").index(value),
                ),
                warning_count=sum(len(row.qc_warnings) for row in rows),
            )
        )
    return summaries


def list_case_inventory(dataset_path: Path | str, case_id: str) -> list[CaseInventoryRow]:
    rows = [row for row in get_database_index(dataset_path).rows if row.case_id == case_id]
    return [_inventory_row(row) for row in sorted(rows, key=_row_sort_key)]


def get_case_dossier(dataset_path: Path | str, case_id: str) -> CaseDossier:
    rows = [row for row in get_database_index(dataset_path).rows if row.case_id == case_id]
    if not rows:
        raise FileNotFoundError(f"Case '{case_id}' not found in dataset index")

    return CaseDossier(
        case_id=case_id,
        core=_project_fields(
            rows,
            {
                "dataset_id",
                "case_id",
                "patient_id",
                "group",
                "scan_key",
                "scan_idx",
                "filename",
                "phase",
                "raw_phase",
                "canonical_phase",
                "phase_source",
                "phase_confidence",
                "phase_guess",
                "phase_guess_confidence",
                "phase_guess_evidence",
                "phase_guess_conflict",
                "curated_phase",
                "curated_keep",
                "curated_quality",
                "include_guess",
                "output_role",
                "exclude_reason",
                "analysis_readiness",
                "analysis_readiness_reasons",
                "notes",
                "side",
                "laterality",
                "tumor_laterality",
            },
        ),
        acquisition=_project_fields(
            rows,
            {
                "modality",
                "series_description",
                "study_date",
                "study_time",
                "manufacturer",
                "manufacturer_model",
                "protocol",
                "scan_plane",
                "image_orientation",
                "kvp",
                "contrast_agent",
                "spacing_x",
                "spacing_y",
                "spacing_z",
                "dim_x",
                "dim_y",
                "dim_z",
                "slice_thickness",
                "num_slices",
            },
        ),
        segmentation_voi=_project_fields(
            rows,
            {
                "nifti_path",
                "nifti_original_volume_path",
                "seg_path",
                "voi_image_path",
                "voi_mask_path",
                "has_seg",
                "has_voi_image",
                "has_voi_mask",
                "voi_status",
                "has_tumor",
            },
        ),
        preprocessing_qc=_project_prefixed_fields(
            rows,
            prefixes=("preprocess", "spacing_quality", "validation", "voi_status"),
        ),
        external_research=_project_prefixed_fields(
            rows,
            prefixes=("external__", "radiomics", "vessel__", "source_"),
        ),
        advanced_raw_fields=[
            {
                "row_id": row.row_id,
                "source_row_id": row.source_row_id,
                "raw": row.raw,
            }
            for row in rows
        ],
    )


def get_case_load_source(
    dataset_path: Path | str,
    case_id: str,
    row_id: str,
    scope: Scope,
    row_index: int | None = None,
) -> CaseLoadSource:
    index = get_database_index(dataset_path)
    if row_index is None:
        row = next((entry for entry in index.rows if entry.case_id == case_id and entry.row_id == row_id), None)
    else:
        row = next(
            (
                entry
                for entry in index.rows
                if entry.case_id == case_id and entry.row_id == row_id and entry.index == row_index
            ),
            None,
        )
    if row is None:
        raise FileNotFoundError(f"Row '{row_id}' was not found for case '{case_id}'")

    if scope == "complete":
        if not path_exists(row.nifti_path):
            raise FileNotFoundError(f"Complete scan is not available for row '{row_id}'")
        image_path = row.nifti_path.resolved
        mask_path = row.seg_path.resolved if path_exists(row.seg_path) else None
        source_type = "nifti"
    else:
        if not path_exists(row.voi_image_path):
            raise FileNotFoundError(f"VOI image is not available for row '{row_id}'")
        image_path = row.voi_image_path.resolved
        mask_path = row.voi_mask_path.resolved if path_exists(row.voi_mask_path) else None
        source_type = "voi_numpy" if _is_numpy_path(image_path or "") else "voi_nifti"

    if image_path is None:
        raise FileNotFoundError(f"Image path is missing for row '{row_id}'")

    return CaseLoadSource(
        dataset_id=index.dataset_id,
        case_id=case_id,
        row_index=row.index,
        row_id=row.row_id,
        scope=scope,
        series_id=f"{scope}:{row.index}:{row.row_id}",
        image_path=image_path,
        mask_path=mask_path,
        source_type=source_type,
    )


def required_column_status(fieldnames: tuple[str, ...]) -> list[RequiredColumnStatus]:
    fields = set(fieldnames)
    required: list[tuple[str, tuple[str, ...]]] = [
        ("case_id", ("case_id",)),
        ("patient_id", ("patient_id",)),
        ("group", ("group",)),
        ("phase", ("canonical_phase", "phase")),
        ("scan_idx", ("scan_idx",)),
        ("side", ("side",)),
        ("nifti_path", ("nifti_path", "nifti_original_volume_path", "filename")),
        ("seg_path", ("seg_path",)),
        ("voi_image_path", ("voi_image_path",)),
        ("voi_mask_path", ("voi_mask_path",)),
        ("has_seg", ("has_seg",)),
        ("has_voi_image", ("has_voi_image",)),
        ("has_voi_mask", ("has_voi_mask",)),
    ]
    return [
        RequiredColumnStatus(
            name=name,
            present=any(candidate in fields for candidate in alternatives),
            alternatives=list(alternatives),
        )
        for name, alternatives in required
    ]


def normalize_phase(value: str | None) -> tuple[CanonicalPhase, PhaseStatus]:
    cleaned = (value or "").strip()
    if ";" in cleaned:
        mapped, status = normalize_phase(cleaned.split(";", 1)[0])
        return (mapped, "ambiguous") if mapped != "UNK" else (mapped, status)

    key = _phase_key(cleaned)
    if key in MISSING_PHASE_VALUES:
        return "UNK", "missing"
    mapped = PHASE_MAPPING.get(key)
    if mapped is None:
        return "UNK", "ambiguous"
    return mapped, "normalized"


def _load_database_index(dataset_path: Path) -> DatabaseIndex:
    metadata_path = dataset_path / "metadata.jsonl"
    if metadata_path.is_file():
        return _load_converter_metadata_index(dataset_path)

    database_path = dataset_path / "database.csv"
    if database_path.is_file():
        with database_path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            fieldnames = tuple(reader.fieldnames or ())
            rows = tuple(
                _normalize_row(dataset_path, index, _stringify_row(row))
                for index, row in enumerate(reader)
            )

        dataset_id = _first_value(row.raw.get("dataset_id") for row in rows) or dataset_path.name
        return DatabaseIndex(
            dataset_id=dataset_id,
            dataset_path=dataset_path,
            has_database=True,
            source_file="database.csv",
            fieldnames=fieldnames,
            rows=rows,
        )

    return DatabaseIndex(
        dataset_id=dataset_path.name,
        dataset_path=dataset_path,
        has_database=False,
        source_file=None,
        fieldnames=(),
        rows=(),
    )


def _load_converter_metadata_index(dataset_path: Path) -> DatabaseIndex:
    phase_overrides = phase_overrides_by_scan_key(dataset_path)
    projected_rows: list[dict[str, Any]] = [
        _metadata_to_database_row(dataset_path, index, row, phase_overrides)
        for index, row in enumerate(read_converter_metadata_rows(dataset_path))
    ]
    metadata_phase_by_key = _metadata_phase_index(projected_rows)
    projected_rows.extend(
        row
        for index, catalog_row in enumerate(read_voi_catalog_rows(dataset_path), start=len(projected_rows))
        if (
            row := _voi_catalog_to_database_row(
                dataset_path,
                index,
                catalog_row,
                phase_overrides,
                metadata_phase_by_key,
            )
        )
        is not None
    )
    fieldnames = tuple(dict.fromkeys(field for row in projected_rows for field in row))
    rows = tuple(
        _normalize_row(dataset_path, index, _stringify_row(row))
        for index, row in enumerate(projected_rows)
    )
    dataset_id = _first_value(row.raw.get("dataset_id") for row in rows) or dataset_path.name
    return DatabaseIndex(
        dataset_id=dataset_id,
        dataset_path=dataset_path,
        has_database=True,
        source_file="metadata.jsonl",
        fieldnames=fieldnames,
        rows=rows,
    )


def _metadata_to_database_row(
    dataset_path: Path,
    index: int,
    row: dict[str, Any],
    phase_overrides: dict[tuple[str, str], str],
) -> dict[str, Any]:
    intentionally_skipped = is_intentionally_skipped_metadata_row(row)
    filename = metadata_filename(row)
    if not filename and not intentionally_skipped:
        filename = f"metadata_row_{index:06d}.nii.gz"
    filename = filename or ""
    case_id = text_value(row.get("case_id")) or _extract_case_id(filename)
    scan_idx = text_value(row.get("scan_idx"))
    curated_phase = resolve_curated_phase(phase_overrides, case_id, scan_idx)
    if curated_phase:
        phase, phase_source = curated_phase, "phase.json"
    else:
        phase, phase_source = select_converter_phase(row)
    nifti_path = (
        "" if intentionally_skipped else _metadata_nifti_path(dataset_path, row, filename)
    )
    seg_path = "" if intentionally_skipped else _metadata_seg_path(dataset_path, filename)
    has_seg = path_exists(resolve_database_path(dataset_path, seg_path))
    row_identity = (
        text_value(row.get("relative_path"))
        or filename
        or text_value(row.get("source_row_id"))
        or text_value(row.get("series_uid"))
        or text_value(row.get("study_uid"))
        or f"row_{index:06d}"
    )

    projected = {
        **row,
        "row_id": f"metadata:{row_identity}",
        "source_row_id": _first_value(
            [
                text_value(row.get("source_row_id")),
                text_value(row.get("series_uid")),
                text_value(row.get("study_uid")),
            ]
        ),
        "dataset_id": text_value(row.get("dataset_id")) or dataset_path.name,
        "case_id": case_id,
        "patient_id": text_value(row.get("patient_id")),
        "group": text_value(row.get("group")) or "NG",
        "raw_phase": phase,
        "phase": phase,
        "phase_source": phase_source,
        "phase_confidence": text_value(row.get("phase_guess_confidence")),
        "scan_idx": scan_idx,
        "side": _metadata_side(row),
        "filename": filename,
        "nifti_path": nifti_path,
        "nifti_original_volume_path": nifti_path,
        "seg_path": seg_path,
        "voi_image_path": "",
        "voi_mask_path": "",
        "has_seg": str(has_seg).lower(),
        "has_voi_image": "false",
        "has_voi_mask": "false",
        "source_index": "metadata.jsonl",
    }
    return projected


def _voi_catalog_to_database_row(
    dataset_path: Path,
    index: int,
    row: dict[str, Any],
    phase_overrides: dict[tuple[str, str], str],
    metadata_phase_by_key: dict[tuple[str, str], str],
) -> dict[str, Any] | None:
    case_id = text_value(row.get("case_id"))
    scan_idx = text_value(row.get("scan_idx"))
    phase = resolve_curated_phase(phase_overrides, case_id, scan_idx)
    if not phase:
        key = canonical_scan_key(case_id, scan_idx)
        phase = metadata_phase_by_key.get(key) if key is not None else None
    image_path = _catalog_voi_path(dataset_path, _catalog_image_path_value(row))
    mask_path = _catalog_voi_path(dataset_path, _catalog_mask_path_value(row))
    if not case_id or not scan_idx or not phase or not image_path:
        return None

    side = _normalize_side(text_value(row.get("side"))) or ""
    filename = (
        text_value(row.get("filename"))
        or text_value(row.get("metadata_filename"))
        or Path(image_path).name
        or f"voi_row_{index:06d}.npy"
    )
    voi_id = text_value(row.get("voi_id")) or f"{case_id}/{scan_idx}/{side or Path(filename).stem}"

    return {
        **row,
        "row_id": f"voi:{voi_id}",
        "source_row_id": text_value(row.get("series_uid")),
        "dataset_id": text_value(row.get("dataset_id")) or dataset_path.name,
        "case_id": case_id,
        "patient_id": text_value(row.get("patient_id")),
        "group": text_value(row.get("group")) or "NG",
        "raw_phase": phase,
        "phase": phase,
        "phase_source": "phase.json",
        "phase_confidence": "",
        "scan_idx": scan_idx,
        "side": side,
        "filename": filename,
        "nifti_path": text_value(row.get("nifti_path")) or text_value(row.get("metadata_relative_path")),
        "nifti_original_volume_path": text_value(row.get("nifti_path")) or text_value(row.get("metadata_relative_path")),
        "seg_path": text_value(row.get("seg_path")) or _metadata_seg_path(dataset_path, filename),
        "voi_image_path": image_path,
        "voi_mask_path": mask_path,
        "has_seg": str(path_exists(resolve_database_path(dataset_path, text_value(row.get("seg_path"))))).lower(),
        "has_voi_image": str(path_exists(resolve_database_path(dataset_path, image_path))).lower(),
        "has_voi_mask": str(path_exists(resolve_database_path(dataset_path, mask_path))).lower(),
        "source_index": "voi/voi_catalog.jsonl",
        "voi_id": voi_id,
    }


def _metadata_phase_index(rows: list[dict[str, Any]]) -> dict[tuple[str, str], str]:
    phases: dict[tuple[str, str], str] = {}
    for row in rows:
        key = canonical_scan_key(row.get("case_id"), row.get("scan_idx"))
        phase = text_value(row.get("phase")) or text_value(row.get("curated_phase"))
        if key is not None and phase:
            phases[key] = phase
    return phases


def _catalog_voi_path(dataset_path: Path, raw_path: str) -> str:
    if not raw_path:
        return ""
    normalized = raw_path.replace("\\", "/")
    if not normalized.startswith("voi/") and not normalized.startswith("deleted/"):
        normalized = f"voi/{normalized}"
    if path_exists(resolve_database_path(dataset_path, normalized)):
        return normalized
    deleted_path = _deleted_voi_path(normalized)
    if deleted_path and path_exists(resolve_database_path(dataset_path, deleted_path)):
        return deleted_path
    return normalized


def _deleted_voi_path(path: str) -> str:
    if path.startswith("voi/deleted/"):
        return path
    if path.startswith("voi/images/"):
        return "voi/deleted/images/" + path.removeprefix("voi/images/")
    if path.startswith("voi/mask/"):
        return "voi/deleted/mask/" + path.removeprefix("voi/mask/")
    if path.startswith("voi/segmentation/"):
        return "voi/deleted/mask/" + path.removeprefix("voi/segmentation/")
    return ""


def _catalog_image_path_value(row: dict[str, Any]) -> str:
    return text_value(row.get("voi_image_path")) or text_value(row.get("image_path"))


def _catalog_mask_path_value(row: dict[str, Any]) -> str:
    return text_value(row.get("voi_mask_path")) or text_value(row.get("mask_path"))


def _metadata_nifti_path(dataset_path: Path, row: dict[str, Any], filename: str) -> str:
    raw_path = (
        text_value(row.get("relative_path"))
        or text_value(row.get("nifti_file"))
        or f"nifti/{filename}"
    )
    if path_exists(resolve_database_path(dataset_path, raw_path)):
        return raw_path
    deleted_path = f"deleted/nifti/{filename}"
    if path_exists(resolve_database_path(dataset_path, deleted_path)):
        return deleted_path
    return raw_path


def _metadata_seg_path(dataset_path: Path, filename: str) -> str:
    stem = _strip_nifti_suffix(filename)
    seg_stem = stem[:-5] if stem.endswith("_0000") else stem
    for suffix in (".nii.gz", ".nii"):
        candidate = dataset_path / "seg" / f"{seg_stem}{suffix}"
        if candidate.exists():
            return f"seg/{seg_stem}{suffix}"
        deleted_candidate = dataset_path / "deleted" / "seg" / f"{seg_stem}{suffix}"
        if deleted_candidate.exists():
            return f"deleted/seg/{seg_stem}{suffix}"
    return f"seg/{seg_stem}.nii.gz"


def _metadata_side(row: dict[str, Any]) -> str:
    for value in (
        text_value(row.get("side")),
        text_value(row.get("laterality")),
    ):
        if value.upper() in VALID_SIDES:
            return value.upper()
    return ""


def _extract_case_id(filename: str) -> str:
    stem = _strip_nifti_suffix(filename)
    parts = stem.split("_")
    for index, part in enumerate(parts[:-1]):
        if part == "case" and parts[index + 1].isdigit():
            return f"case_{parts[index + 1]}"
    return stem


def _strip_nifti_suffix(filename: str) -> str:
    for suffix in (".nii.gz", ".nii"):
        if filename.endswith(suffix):
            return filename[: -len(suffix)]
    return Path(filename).stem

def _normalize_row(dataset_path: Path, index: int, raw: dict[str, str]) -> DatabaseRow:
    source_row_id = _first_value(
        [
            raw.get("source_row_id"),
            raw.get("source_row_indices"),
            raw.get("source_preprocess_row_index"),
        ]
    )
    row_id = _first_value([raw.get("row_id"), raw.get("source_row_id")]) or f"row_{index:06d}"
    case_id = (raw.get("case_id") or "").strip() or f"case_row_{index:06d}"
    patient_id = _blank_to_none(raw.get("patient_id"))
    group = _blank_to_none(raw.get("group"))
    raw_phase = _blank_to_none(raw.get("raw_phase")) or _blank_to_none(raw.get("phase"))
    canonical_raw = _blank_to_none(raw.get("canonical_phase")) or _blank_to_none(raw.get("phase"))
    canonical_phase, phase_status = normalize_phase(canonical_raw or raw_phase)
    scan_idx = _blank_to_none(raw.get("scan_idx"))
    side = _normalize_side(raw.get("side"))

    nifti_path = _select_first_existing(
        dataset_path,
        raw.get("nifti_path"),
        raw.get("nifti_original_volume_path"),
        f"nifti/{raw.get('filename', '').strip()}" if raw.get("filename") else None,
    )
    seg_path = resolve_database_path(dataset_path, raw.get("seg_path"))
    voi_image_path = resolve_database_path(dataset_path, raw.get("voi_image_path"))
    voi_mask_path = resolve_database_path(dataset_path, raw.get("voi_mask_path"))
    has_seg = _parse_bool(raw.get("has_seg"), default=path_exists(seg_path))
    has_voi_image = _parse_bool(raw.get("has_voi_image"), default=path_exists(voi_image_path))
    has_voi_mask = _parse_bool(raw.get("has_voi_mask"), default=path_exists(voi_mask_path))

    base = DatabaseRow(
        index=index,
        raw=raw,
        row_id=row_id,
        source_row_id=source_row_id,
        case_id=case_id,
        patient_id=patient_id,
        group=group,
        raw_phase=raw_phase,
        canonical_phase=canonical_phase,
        phase_status=phase_status,
        scan_idx=scan_idx,
        side=side,
        nifti_path=nifti_path,
        seg_path=seg_path,
        voi_image_path=voi_image_path,
        voi_mask_path=voi_mask_path,
        has_seg=has_seg,
        has_voi_image=has_voi_image,
        has_voi_mask=has_voi_mask,
        qc_warnings=(),
    )
    return DatabaseRow(**{**base.__dict__, "qc_warnings": tuple(_row_warnings(base))})


def _row_warnings(row: DatabaseRow) -> list[QCWarning]:
    warnings: list[QCWarning] = []
    intentionally_skipped = row.is_intentionally_skipped
    if not intentionally_skipped:
        _append_path_warning(warnings, row, "nifti_path", row.nifti_path, "complete")
        _append_path_warning(
            warnings,
            row,
            "seg_path",
            row.seg_path,
            "complete",
            expected=row.has_seg,
        )
    _append_path_warning(warnings, row, "voi_image_path", row.voi_image_path, "voi", expected=row.has_voi_image)
    _append_path_warning(warnings, row, "voi_mask_path", row.voi_mask_path, "voi", expected=row.has_voi_mask)

    if not intentionally_skipped and not row.has_seg:
        warnings.append(
            QCWarning(
                code="missing_seg",
                message="SEG is marked unavailable.",
                row_id=row.row_id,
                scope="complete",
                path_field="seg_path",
            )
        )
    elif not intentionally_skipped and not path_exists(row.seg_path):
        warnings.append(
            QCWarning(
                code="missing_seg",
                message="SEG is expected but missing or unreadable.",
                row_id=row.row_id,
                scope="complete",
                path_field="seg_path",
            )
        )
    if not row.has_voi_image:
        if _should_warn_missing_voi(row, row.voi_image_path):
            warnings.append(
                QCWarning(
                    code="missing_voi_image",
                    message="VOI image is marked unavailable.",
                    row_id=row.row_id,
                    scope="voi",
                    path_field="voi_image_path",
                )
            )
    elif not path_exists(row.voi_image_path):
        warnings.append(
            QCWarning(
                code="missing_voi_image",
                message="VOI image is expected but missing or unreadable.",
                row_id=row.row_id,
                scope="voi",
                path_field="voi_image_path",
            )
        )
    if not row.has_voi_mask:
        if _should_warn_missing_voi(row, row.voi_mask_path):
            warnings.append(
                QCWarning(
                    code="missing_voi_mask",
                    message="VOI mask is marked unavailable.",
                    row_id=row.row_id,
                    scope="voi",
                    path_field="voi_mask_path",
                )
            )
    elif not path_exists(row.voi_mask_path):
        warnings.append(
            QCWarning(
                code="missing_voi_mask",
                message="VOI mask is expected but missing or unreadable.",
                row_id=row.row_id,
                scope="voi",
                path_field="voi_mask_path",
            )
        )
    if row.phase_status != "normalized":
        warnings.append(
            QCWarning(
                code="ambiguous_phase",
                message=f"Phase '{row.raw_phase or ''}' maps to {row.canonical_phase}.",
                row_id=row.row_id,
            )
        )
    if (row.has_voi_image or path_exists(row.voi_image_path)) and row.side not in VALID_SIDES:
        warnings.append(
            QCWarning(
                code="ambiguous_side",
                message="VOI row has no explicit L/R side.",
                row_id=row.row_id,
                scope="voi",
            )
        )
    return warnings



def _should_warn_missing_voi(row: DatabaseRow, status: PathStatus) -> bool:
    return not (row.raw.get("source_index") == "metadata.jsonl" and status.status == "not_provided")

def _append_path_warning(
    warnings: list[QCWarning],
    row: DatabaseRow,
    field: str,
    status: PathStatus,
    scope: Scope,
    *,
    expected: bool = True,
) -> None:
    if not expected and status.status == "not_provided":
        return
    if status.status == "missing":
        warnings.append(
            QCWarning(
                code="missing_path",
                message=f"{field} does not resolve to an existing readable file.",
                row_id=row.row_id,
                scope=scope,
                path_field=field,
            )
        )
    elif path_is_unreadable(status):
        warnings.append(
            QCWarning(
                code="unreadable_file",
                message=f"{field} exists but is not readable.",
                row_id=row.row_id,
                scope=scope,
                path_field=field,
            )
        )


def _inventory_row(row: DatabaseRow) -> CaseInventoryRow:
    return CaseInventoryRow(
        row_index=row.index,
        row_id=row.row_id,
        source_row_id=row.source_row_id,
        series_id=_row_series_id(row),
        case_id=row.case_id,
        patient_id=row.patient_id,
        group=row.group,
        raw_phase=row.raw_phase,
        canonical_phase=row.canonical_phase,
        phase_status=row.phase_status,
        scan_idx=row.scan_idx,
        side=row.side,
        scope_availability={
            "complete": row.has_complete_scope,
            "voi": row.has_voi_scope,
        },
        nifti_path=row.nifti_path,
        seg_path=row.seg_path,
        voi_image_path=row.voi_image_path,
        voi_mask_path=row.voi_mask_path,
        has_seg=row.has_seg,
        has_voi_image=row.has_voi_image,
        has_voi_mask=row.has_voi_mask,
        deleted=_row_is_deleted(row),
        qc_warnings=list(row.qc_warnings),
    )


def _row_series_id(row: DatabaseRow) -> str | None:
    if row.raw.get("source_index") == "voi/voi_catalog.jsonl":
        voi_id = _blank_to_none(row.raw.get("voi_id"))
        return f"voi:{voi_id}" if voi_id else None
    return _nifti_series_id(row.nifti_path)


def _nifti_series_id(path_status: PathStatus) -> str | None:
    raw_path = path_status.raw or path_status.resolved
    if not raw_path:
        return None
    filename = Path(raw_path).name
    stem = _strip_nifti_suffix(filename)
    if not stem:
        return None
    return f"nifti:{stem}"


def _row_is_deleted(row: DatabaseRow) -> bool:
    return any(
        _path_status_is_deleted(status)
        for status in (row.nifti_path, row.seg_path, row.voi_image_path, row.voi_mask_path)
    )


def _path_status_is_deleted(status: PathStatus) -> bool:
    values = [status.raw, status.resolved]
    for value in values:
        if not value:
            continue
        normalized = value.replace("\\", "/")
        if "/deleted/" in normalized or normalized.startswith("deleted/"):
            return True
    return False


def _project_fields(rows: list[DatabaseRow], fields: set[str]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for field in sorted(fields):
        values = [_blank_to_none(row.raw.get(field)) for row in rows if field in row.raw]
        unique = [value for value in dict.fromkeys(values) if value is not None]
        if not unique:
            continue
        payload[field] = unique[0] if len(unique) == 1 else unique
    return payload


def _project_prefixed_fields(rows: list[DatabaseRow], prefixes: tuple[str, ...]) -> dict[str, Any]:
    fields = {
        field
        for row in rows
        for field in row.raw
        if any(field.startswith(prefix) or field == prefix for prefix in prefixes)
    }
    return _project_fields(rows, fields)


def _select_first_existing(dataset_path: Path, *raw_values: str | None) -> PathStatus:
    statuses = [
        resolve_database_path(dataset_path, value)
        for value in raw_values
        if (value or "").strip()
    ]
    for status in statuses:
        if path_exists(status):
            return status
    return statuses[0] if statuses else PathStatus()


def _parse_bool(value: str | None, default: bool = False) -> bool:
    cleaned = (value or "").strip().lower()
    if cleaned in {"1", "true", "yes", "y", "on"}:
        return True
    if cleaned in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _normalize_side(value: str | None) -> str | None:
    cleaned = (value or "").strip().upper()
    if cleaned in VALID_SIDES:
        return cleaned
    return None


def _phase_key(value: str | None) -> str:
    return (value or "").strip().upper().replace(" ", "").replace("_", "-")


def _blank_to_none(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def _first_value(values) -> str | None:
    for value in values:
        cleaned = _blank_to_none(value)
        if cleaned is not None:
            return cleaned
    return None


def _row_sort_key(row: DatabaseRow) -> tuple[int, int, str, str]:
    phase_rank = PHASE_PRIORITY.index(row.canonical_phase) if row.canonical_phase in PHASE_PRIORITY else 99
    try:
        scan_rank = int(row.scan_idx or "0")
    except ValueError:
        scan_rank = 0
    return (phase_rank, scan_rank, row.side or "", row.row_id)


def _stringify_row(row: dict[str, Any]) -> dict[str, str]:
    return {key: "" if value is None else str(value) for key, value in row.items()}


def _is_numpy_path(path: str) -> bool:
    return path.lower().endswith(".npy")
