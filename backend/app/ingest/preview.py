"""Import preview: detect inputs, parse, count, map fields (IMP-02/03). No header reads."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.core.paths import open_source
from app.ingest.normalize import PHASE_FIELDS
from app.ingest.parsers import FILE_NAMES, IMAGE_FIELDS, FileKind, ParsedInputs, is_excluded
from app.ingest.schemas import FieldMapping, ImportCounts, InputFile, PreviewError

MAX_PREVIEW_ERRORS = 50
DETECT_PATHS: dict[FileKind, str] = {
    "metadata": "metadata.jsonl",
    "phase": "phase.json",
    "voi_catalog": "voi/voi_catalog.jsonl",
}


@dataclass(frozen=True)
class InputBlob:
    kind: FileKind
    name: str
    source: Literal["detected", "uploaded", "generated"]
    data: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


def detect_inputs(root: Path) -> dict[FileKind, InputBlob]:
    """IMP-02: known input files under the (already guarded) data root, read-only."""
    out: dict[FileKind, InputBlob] = {}
    for kind, rel in DETECT_PATHS.items():
        p = root / rel
        if p.is_file():
            with open_source(p) as fh:
                out[kind] = InputBlob(kind, FILE_NAMES[kind], "detected", fh.read())
    return out


def input_files(blobs: dict[FileKind, InputBlob], parsed: ParsedInputs) -> list[InputFile]:
    rows = {
        "metadata": len(parsed.metadata),
        "phase": len(parsed.overrides),
        "voi_catalog": len(parsed.catalog),
    }
    return [
        InputFile(kind=b.kind, name=b.name, source=b.source, sha256=b.sha256, rows=rows[b.kind])
        for b in blobs.values()
    ]


def counts(parsed: ParsedInputs) -> ImportCounts:
    cases = {r.case_id for r in parsed.metadata} | {r.case_id for r in parsed.catalog}
    return ImportCounts(
        scan_rows=len(parsed.metadata),
        voi_rows=len(parsed.catalog),
        cases=len(cases),
        excluded_upstream=sum(1 for r in parsed.metadata if is_excluded(r)),
    )


def field_mapping(parsed: ParsedInputs) -> FieldMapping:
    meta = parsed.metadata
    image = next((f for f in IMAGE_FIELDS if any(r.text(f) for r in meta)), None)
    seg: Literal["seg_path", "convention"] | None = None
    if meta:
        seg = "seg_path" if any(r.text("seg_path") for r in meta) else "convention"
    phase = ["phase.json"] if len(parsed.overrides) else []
    phase += [f for f in PHASE_FIELDS if any(r.text(f) for r in meta)]
    side = "side" if parsed.catalog else None
    return FieldMapping(image=image, seg=seg, phase=phase, side=side)


def errors(parsed: ParsedInputs) -> list[PreviewError]:
    return [PreviewError(**e.as_dict()) for e in parsed.errors[:MAX_PREVIEW_ERRORS]]
