"""Input parsers: `metadata.jsonl`, `phase.json` (both forms), `voi_catalog.jsonl` (IMP-02/03).

Parsers never raise on bad input: every problem becomes a line-numbered `ParseError` and the
offending row is dropped. Unknown fields are kept in `Row.extra` (INPUT_METADATA.md).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from app.core.ids import CASE_ID_RE

FileKind = Literal["metadata", "phase", "voi_catalog"]
FILE_NAMES: dict[FileKind, str] = {
    "metadata": "metadata.jsonl",
    "phase": "phase.json",
    "voi_catalog": "voi_catalog.jsonl",
}
SCAN_IDX_RE = re.compile(r"^[A-Za-z0-9_-]+$")

METADATA_FIELDS = frozenset(
    {
        "case_id", "scan_idx", "filename", "relative_path", "nifti_file", "patient_id",
        "dataset_id", "study_uid", "series_uid", "phase", "curated_phase", "canonical_phase",
        "phase_guess", "phase_guess_confidence", "seg_path", "status", "planned_conversion",
        "curated_keep",
    }
)  # fmt: skip
CATALOG_FIELDS = frozenset(
    {"voi_id", "case_id", "scan_idx", "side", "image_path", "mask_path", "phase"}
)
IMAGE_FIELDS = ("relative_path", "nifti_file", "filename")


@dataclass(frozen=True)
class ParseError:
    file: str
    line: int | None
    field: str | None
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {"file": self.file, "line": self.line, "field": self.field, "message": self.message}


@dataclass
class Row:
    """One parsed input row: known fields in `data`, unknown ones in `extra`."""

    line: int
    data: dict[str, Any]
    extra: dict[str, Any] = field(default_factory=dict)

    def text(self, key: str) -> str | None:
        """The field as a stripped string; None when absent, null or empty."""
        v = self.data.get(key)
        if v is None or isinstance(v, (dict, list)):
            return None
        s = (("true" if v else "false") if isinstance(v, bool) else f"{v}").strip()
        return s or None

    @property
    def case_id(self) -> str:
        return self.text("case_id") or ""

    @property
    def scan_idx(self) -> str:
        return self.text("scan_idx") or ""


@dataclass
class PhaseOverrides:
    by_scan: dict[tuple[str, str], str] = field(default_factory=dict)
    by_filename: dict[str, str] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.by_scan) + len(self.by_filename)

    def lookup(self, case_id: str, scan_idx: str, filename: str | None) -> str | None:
        v = self.by_scan.get((case_id, scan_idx))
        if v is None and filename:
            v = self.by_filename.get(filename)
        return v


FALSY = frozenset({"false", "0", "no", "n", "f"})


def is_excluded(row: Row) -> bool:
    """Skipped or excluded upstream (IMP-07)."""
    if (row.text("status") or "").lower() == "skipped":
        return True
    return any((row.text(f) or "").lower() in FALSY for f in ("planned_conversion", "curated_keep"))


def _reject_constant(name: str) -> Any:
    raise ValueError(f"non-standard JSON constant {name}")


def _loads(text: str) -> Any:
    return json.loads(text, parse_constant=_reject_constant)


def _jsonl_objects(
    data: bytes, file: str
) -> tuple[list[tuple[int, dict[str, Any]]], list[ParseError]]:
    out: list[tuple[int, dict[str, Any]]] = []
    errors: list[ParseError] = []
    for n, raw in enumerate(data.split(b"\n"), 1):
        line = raw.strip()
        if not line:
            continue
        try:
            obj = _loads(line.decode("utf-8"))
        except UnicodeDecodeError:
            errors.append(ParseError(file, n, None, "line is not valid UTF-8"))
            continue
        except (ValueError, RecursionError) as exc:
            errors.append(ParseError(file, n, None, f"invalid JSON: {exc}"[:200]))
            continue
        if not isinstance(obj, dict):
            errors.append(ParseError(file, n, None, "line is not a JSON object"))
            continue
        out.append((n, obj))
    return out, errors


def _by_line(errors: list[ParseError]) -> list[ParseError]:
    return sorted(errors, key=lambda e: e.line or 0)


def _check_ids(row: Row, file: str, errors: list[ParseError]) -> bool:
    ok = True
    case_id, scan_idx = row.text("case_id"), row.text("scan_idx")
    if case_id is None:
        errors.append(ParseError(file, row.line, "case_id", "required field missing"))
        ok = False
    elif not CASE_ID_RE.match(case_id):
        errors.append(ParseError(file, row.line, "case_id", r"must match case_\d{5}"))
        ok = False
    if scan_idx is None:
        errors.append(ParseError(file, row.line, "scan_idx", "required field missing"))
        ok = False
    elif not SCAN_IDX_RE.match(scan_idx):
        errors.append(ParseError(file, row.line, "scan_idx", "must match [A-Za-z0-9_-]+"))
        ok = False
    if ok:
        row.data["case_id"], row.data["scan_idx"] = case_id, scan_idx
    return ok


def _split(n: int, obj: dict[str, Any], known: frozenset[str]) -> Row:
    return Row(
        n,
        {k: v for k, v in obj.items() if k in known},
        {k: v for k, v in obj.items() if k not in known},
    )


def parse_metadata(data: bytes, file: str = "metadata.jsonl") -> tuple[list[Row], list[ParseError]]:
    objs, errors = _jsonl_objects(data, file)
    rows: list[Row] = []
    for n, obj in objs:
        row = _split(n, obj, METADATA_FIELDS)
        if not _check_ids(row, file, errors):
            continue
        if not is_excluded(row) and not any(row.text(f) for f in IMAGE_FIELDS):
            errors.append(
                ParseError(file, n, "filename", "one of filename/relative_path/nifti_file required")
            )
            continue
        rows.append(row)
    return rows, _by_line(errors)


def parse_voi_catalog(
    data: bytes, file: str = "voi_catalog.jsonl"
) -> tuple[list[Row], list[ParseError]]:
    objs, errors = _jsonl_objects(data, file)
    rows: list[Row] = []
    for n, obj in objs:
        row = _split(n, obj, CATALOG_FIELDS)
        if not _check_ids(row, file, errors):
            continue
        missing = [f for f in ("side", "image_path") if row.text(f) is None]
        for f in missing:
            errors.append(ParseError(file, n, f, "required field missing"))
        if not missing:
            rows.append(row)
    return rows, _by_line(errors)


def parse_phase_json(
    data: bytes, file: str = "phase.json"
) -> tuple[PhaseOverrides, list[ParseError]]:
    """`{"phases": [{case_id, scan_idx, phase}]}` or legacy `{"phase_by_filename": {...}}`."""
    out = PhaseOverrides()
    errors: list[ParseError] = []
    try:
        obj = _loads(data.decode("utf-8"))
    except UnicodeDecodeError:
        return out, [ParseError(file, None, None, "file is not valid UTF-8")]
    except (ValueError, RecursionError) as exc:
        return out, [ParseError(file, None, None, f"invalid JSON: {exc}"[:200])]
    if not isinstance(obj, dict):
        return out, [ParseError(file, None, None, "top level must be a JSON object")]
    phases, legacy = obj.get("phases"), obj.get("phase_by_filename")
    if phases is None and legacy is None:
        return out, [ParseError(file, None, "phases", "expected 'phases' or 'phase_by_filename'")]
    if phases is not None:
        if not isinstance(phases, list):
            errors.append(ParseError(file, None, "phases", "must be a list"))
            phases = []
        for i, entry in enumerate(phases):
            where = f"phases[{i}]"
            if not isinstance(entry, dict):
                errors.append(ParseError(file, None, where, "entry must be an object"))
                continue
            row = Row(i, entry)
            ph = row.text("phase")
            sub: list[ParseError] = []
            if not _check_ids(row, file, sub) or ph is None:
                msg = "; ".join(f"{e.field}: {e.message}" for e in sub) or "phase: required"
                errors.append(ParseError(file, None, where, msg))
                continue
            out.by_scan[(row.case_id, row.scan_idx)] = ph
    if legacy is not None:
        if not isinstance(legacy, dict):
            errors.append(ParseError(file, None, "phase_by_filename", "must be an object"))
        else:
            for name, ph in legacy.items():
                if isinstance(ph, str) and ph.strip():
                    out.by_filename[str(name)] = ph.strip()
                else:
                    errors.append(
                        ParseError(file, None, f"phase_by_filename[{name}]", "must be a string")
                    )
    return out, errors


@dataclass
class ParsedInputs:
    metadata: list[Row] = field(default_factory=list)
    catalog: list[Row] = field(default_factory=list)
    overrides: PhaseOverrides = field(default_factory=PhaseOverrides)
    errors: list[ParseError] = field(default_factory=list)


def parse_inputs(files: dict[FileKind, bytes]) -> ParsedInputs:
    out = ParsedInputs()
    if "metadata" in files:
        out.metadata, errs = parse_metadata(files["metadata"])
        out.errors += errs
    if "phase" in files:
        out.overrides, errs = parse_phase_json(files["phase"])
        out.errors += errs
    if "voi_catalog" in files:
        out.catalog, errs = parse_voi_catalog(files["voi_catalog"])
        out.errors += errs
    return out
