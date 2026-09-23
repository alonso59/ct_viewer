from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Callable


METADATA_FILENAME = "metadata.jsonl"
PHASE_FILENAME = "phase.json"
VOI_CATALOG_FILENAME = "voi/voi_catalog.jsonl"
CURATION_FILENAME = "curation.csv"
DELETE_KEEP_VALUES = {"0", "false", "no", "delete", "deleted", "trash", "recycle"}
MISSING_PHASE_VALUES = {"", "UNDEFINED", "UNKNOWN", "UNK", "N/A", "NA", "NONE", "NULL"}
EXPLICIT_FALSE_VALUES = {"0", "false", "no", "off"}


def has_converter_metadata(dataset_path: Path | str) -> bool:
    return _metadata_path(dataset_path).is_file()


def read_converter_metadata_rows(dataset_path: Path | str) -> list[dict[str, Any]]:
    path = _metadata_path(dataset_path)
    if not path.is_file():
        return []

    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL in {path} at line {line_number}: {exc}") from exc
            if isinstance(value, dict):
                rows.append(value)
    return rows


def metadata_rows_by_filename(dataset_path: Path | str) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in read_converter_metadata_rows(dataset_path):
        filename = metadata_filename(row)
        if filename:
            rows[filename] = row
    return rows


def metadata_rows_by_scan_key(dataset_path: Path | str) -> dict[tuple[str, str], dict[str, Any]]:
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for row in read_converter_metadata_rows(dataset_path):
        key = scan_key(row)
        if key is not None:
            rows[key] = row
    return rows


def read_voi_catalog_rows(dataset_path: Path | str) -> list[dict[str, Any]]:
    path = Path(dataset_path).expanduser().resolve() / VOI_CATALOG_FILENAME
    if not path.is_file():
        return []

    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL in {path} at line {line_number}: {exc}") from exc
            if isinstance(value, dict):
                rows.append(value)
    return rows


def phase_overrides_by_scan_key(dataset_path: Path | str) -> dict[tuple[str, str], str]:
    payload = _read_phase_payload(dataset_path)
    if not payload:
        return {}

    rows = _phase_payload_rows(payload)
    overrides: dict[tuple[str, str], str] = {}
    for row in rows:
        key = scan_key(row)
        phase = text_value(row.get("phase"))
        if key is not None and phase:
            overrides[key] = phase
    return overrides


def resolve_curated_phase(
    phase_overrides: dict[tuple[str, str], str],
    case_id: str | None,
    scan_idx: str | None,
) -> str | None:
    key = canonical_scan_key(case_id, scan_idx)
    if key is None:
        return None
    phase = text_value(phase_overrides.get(key))
    if not phase or _phase_is_missing(phase):
        return None
    return phase


def scan_key(row: dict[str, Any]) -> tuple[str, str] | None:
    return canonical_scan_key(row.get("case_id"), row.get("scan_idx"))


def canonical_scan_key(case_id: Any, scan_idx: Any) -> tuple[str, str] | None:
    case = text_value(case_id)
    scan = text_value(scan_idx)
    if not case or not scan:
        return None
    return case, scan


def metadata_filename(row: dict[str, Any]) -> str | None:
    filename = text_value(row.get("filename"))
    if filename:
        return filename
    for key in ("relative_path", "nifti_file"):
        value = text_value(row.get(key))
        if value:
            return Path(value).name
    return None


def is_intentionally_skipped_metadata_row(row: dict[str, Any]) -> bool:
    return (
        text_value(row.get("status")).lower() == "skipped"
        and text_value(row.get("planned_conversion")).lower() in EXPLICIT_FALSE_VALUES
        and all(not text_value(row.get(key)) for key in ("filename", "relative_path", "nifti_file"))
    )


def select_converter_phase(
    row: dict[str, Any],
    fallback: dict[str, Any] | None = None,
    phase_override: str | None = None,
    *,
    include_phase_guess: bool = False,
) -> tuple[str, str]:
    missing_candidate: tuple[str, str] | None = None
    candidates = [
        ("phase_json", phase_override),
        ("phase", row.get("phase")),
        ("curated_phase", row.get("curated_phase")),
        ("canonical_phase", row.get("canonical_phase")),
    ]
    if include_phase_guess:
        candidates.append(("phase_guess", row.get("phase_guess")))
    for source, candidate in candidates:
        value = text_value(candidate)
        if value:
            if source != "phase_json" and _phase_is_missing(value):
                missing_candidate = missing_candidate or (value, source)
                continue
            return value, source
    return missing_candidate or ("", "")


def update_converter_phase(dataset_path: Path | str, filename: str, target_phase: str) -> bool:
    return update_phase_override(dataset_path, filename, target_phase)


def update_phase_override(dataset_path: Path | str, filename: str, target_phase: str) -> bool:
    dataset = Path(dataset_path).expanduser().resolve()
    path = _phase_path(dataset)
    payload = _read_phase_payload(dataset) or _initial_phase_payload(dataset)
    rows = _phase_payload_rows(payload)
    now = _now_iso()
    metadata_index = metadata_rows_by_filename(dataset)
    metadata_row = metadata_index.get(filename, {})
    target_key = scan_key(metadata_row)
    if target_key is None:
        return False

    matched = False
    for row in rows:
        if scan_key(row) != target_key:
            continue
        row["phase"] = target_phase
        row["updated_at"] = now
        row["updated_by"] = "webui"
        matched = True

    if not matched:
        rows.append(
            {
                "filename": filename,
                "relative_path": text_value(metadata_row.get("relative_path")),
                "nifti_file": text_value(metadata_row.get("nifti_file")),
                "case_id": target_key[0],
                "patient_id": text_value(metadata_row.get("patient_id")),
                "scan_idx": target_key[1],
                "phase": target_phase,
                "source_phase": "",
                "source_phase_source": "manual",
                "updated_at": now,
                "updated_by": "webui",
            }
        )
        matched = True

    if isinstance(payload, dict):
        payload["schema_version"] = payload.get("schema_version") or 1
        payload["updated_at"] = now
        payload["phases"] = rows
        _atomic_write_json(path, payload)
    else:
        _atomic_write_json(path, {"schema_version": 1, "updated_at": now, "phases": rows})
    return matched


def mark_converter_deleted(
    dataset_path: Path | str,
    filename: str,
    destination_relative_path: str | None,
) -> bool:
    dataset = Path(dataset_path).expanduser().resolve()

    def update_row(row: dict[str, Any]) -> None:
        row["curated_keep"] = "no"
        if destination_relative_path:
            row["relative_path"] = destination_relative_path
            row["nifti_file"] = str((dataset / destination_relative_path).resolve())

    metadata_updated = _update_metadata_rows(dataset, filename, update_row)

    def update_curation_row(row: dict[str, str]) -> None:
        row["curated_keep"] = "no"
        if destination_relative_path:
            row["nifti_file"] = str((dataset / destination_relative_path).resolve())

    curation_updated = _update_curation_rows(dataset, filename, update_curation_row)
    return metadata_updated or curation_updated


def restore_converter_deleted(
    dataset_path: Path | str,
    filename: str,
    restored_relative_path: str | None,
) -> bool:
    dataset = Path(dataset_path).expanduser().resolve()

    def update_row(row: dict[str, Any]) -> None:
        if restored_relative_path:
            row["relative_path"] = restored_relative_path
            row["nifti_file"] = str((dataset / restored_relative_path).resolve())
        if text_value(row.get("curated_keep")).lower() in DELETE_KEEP_VALUES:
            row["curated_keep"] = ""

    metadata_updated = _update_metadata_rows(dataset, filename, update_row)

    def update_curation_row(row: dict[str, str]) -> None:
        if restored_relative_path:
            row["nifti_file"] = str((dataset / restored_relative_path).resolve())
        if text_value(row.get("curated_keep")).lower() in DELETE_KEEP_VALUES:
            row["curated_keep"] = ""

    curation_updated = _update_curation_rows(dataset, filename, update_curation_row)
    return metadata_updated or curation_updated


def text_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip()


def _metadata_path(dataset_path: Path | str) -> Path:
    return Path(dataset_path).expanduser().resolve() / METADATA_FILENAME


def _phase_path(dataset_path: Path | str) -> Path:
    return Path(dataset_path).expanduser().resolve() / PHASE_FILENAME


def _curation_path(dataset_path: Path | str) -> Path:
    return Path(dataset_path).expanduser().resolve() / CURATION_FILENAME


def _read_phase_payload(dataset_path: Path | str) -> dict[str, Any] | list[Any] | None:
    path = _phase_path(dataset_path)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc
    if isinstance(payload, (dict, list)):
        return payload
    raise ValueError(f"Invalid phase payload in {path}: expected object or list")


def _phase_payload_rows(payload: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    for key in ("phases", "rows"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    mapping = payload.get("phase_by_filename")
    if isinstance(mapping, dict):
        return [
            {"filename": str(filename), "phase": text_value(phase)}
            for filename, phase in mapping.items()
        ]
    return [
        {"filename": str(filename), "phase": text_value(phase)}
        for filename, phase in payload.items()
        if filename not in {"schema_version", "source", "description", "updated_at"}
        and not isinstance(phase, (dict, list))
    ]


def _initial_phase_payload(dataset_path: Path | str) -> dict[str, Any]:
    dataset = Path(dataset_path).expanduser().resolve()
    rows: list[dict[str, Any]] = []
    for row in read_converter_metadata_rows(dataset):
        filename = metadata_filename(row)
        if not filename:
            continue
        phase, phase_source = select_converter_phase(row)
        source_phase, source_phase_source = select_converter_phase(row, include_phase_guess=True)
        rows.append(
            {
                "filename": filename,
                "relative_path": text_value(row.get("relative_path")),
                "nifti_file": text_value(row.get("nifti_file")),
                "case_id": text_value(row.get("case_id")),
                "patient_id": text_value(row.get("patient_id")),
                "scan_idx": text_value(row.get("scan_idx")),
                "phase": phase,
                "source_phase": source_phase,
                "source_phase_source": source_phase_source,
                "updated_at": "",
                "updated_by": "",
            }
        )
    return {
        "schema_version": 1,
        "source": METADATA_FILENAME,
        "description": "Mutable phase overrides for the WebUI. metadata.jsonl remains read-only for phase curation.",
        "created_at": _now_iso(),
        "updated_at": "",
        "phases": rows,
    }


def _update_metadata_rows(
    dataset_path: Path | str,
    filename: str,
    updater: Callable[[dict[str, Any]], None],
) -> bool:
    path = _metadata_path(dataset_path)
    if not path.is_file():
        return False

    rows = read_converter_metadata_rows(dataset_path)
    matched = False
    updated_rows: list[dict[str, Any]] = []
    for row in rows:
        next_row = dict(row)
        if _row_matches_filename(next_row, filename):
            matched = True
            updater(next_row)
        updated_rows.append(next_row)

    if matched:
        _atomic_write_jsonl(path, updated_rows)
    return matched


def _update_curation_rows(
    dataset_path: Path | str,
    filename: str,
    updater: Callable[[dict[str, str]], None],
) -> bool:
    path = _curation_path(dataset_path)
    if not path.is_file():
        return False

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]

    matched = False
    for row in rows:
        if not _row_matches_filename(row, filename):
            continue
        matched = True
        updater(row)

    if not matched:
        return False

    for required in ("curated_phase", "curated_keep", "nifti_file"):
        if any(required in row for row in rows) and required not in fieldnames:
            fieldnames.append(required)
    _atomic_write_csv(path, fieldnames, rows)
    return True


def _row_matches_filename(row: dict[str, Any], filename: str) -> bool:
    if not filename:
        return False
    row_filename = metadata_filename(row)
    return row_filename == filename


def _phase_is_missing(value: str) -> bool:
    return value.strip().upper().replace(" ", "").replace("_", "-") in MISSING_PHASE_VALUES


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


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w",
        dir=path.parent,
        prefix=path.stem + ".",
        suffix=".tmp",
        encoding="utf-8",
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=True, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


def _atomic_write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w",
        dir=path.parent,
        prefix=path.stem + ".",
        suffix=".tmp",
        encoding="utf-8",
        newline="",
        delete=False,
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
