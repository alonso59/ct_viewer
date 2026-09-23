"""Import / case / item payloads (API-11..14, API-20..22). Index records live in `models`."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.ingest.models import CaseSummary, IndexStatus, Item, PhaseInfo, QcWarning
from app.ingest.parsers import FileKind

DEFAULT_ALIAS = "DATA"


class PreviewRequest(BaseModel):
    """API-11 JSON body (IMP-01/02)."""

    root: str
    detect: bool = True
    alias: str = DEFAULT_ALIAS


class InputFile(BaseModel):
    kind: FileKind
    name: str
    source: Literal["detected", "uploaded"]
    sha256: str
    rows: int


class ImportCounts(BaseModel):
    scan_rows: int = 0
    voi_rows: int = 0
    cases: int = 0
    excluded_upstream: int = 0


class PreviewError(BaseModel):
    file: str
    line: int | None = None
    field: str | None = None
    message: str


class FieldMapping(BaseModel):
    image: str | None = None  # first image field present (relative_path | nifti_file | filename)
    seg: Literal["seg_path", "convention"] | None = None
    phase: list[str] = Field(default_factory=list)  # present fields, in resolution order
    side: str | None = None


class ImportPreview(BaseModel):
    preview_id: str
    root: str
    alias: str
    files: list[InputFile]
    counts: ImportCounts
    errors: list[PreviewError]
    n_errors: int
    field_mapping: FieldMapping


class CommitRequest(BaseModel):
    preview_id: str


class CommitResult(BaseModel):
    job_id: str
    import_id: str


class ImportRecord(BaseModel):
    """One line of `sources/imports.jsonl` (IMP-04)."""

    import_id: str
    at: str
    alias: str
    root: str
    files: list[InputFile]
    counts: ImportCounts


class ImportHistory(BaseModel):
    items: list[ImportRecord]
    next_cursor: str | None = None
    total: int
    index: IndexStatus


class ScanGroup(BaseModel):
    scan_idx: str
    phase: PhaseInfo
    items: list[Item]


class CaseDetail(BaseModel):
    case: CaseSummary
    scans: list[ScanGroup]
    warnings: list[QcWarning]


class ItemAdvanced(BaseModel):
    image_path: str | None = None  # absolute (DATA_MODEL §Conventions); null if unresolvable
    mask_path: str | None = None


class ItemDetail(Item):
    advanced: ItemAdvanced
    warnings: list[QcWarning] = Field(default_factory=list)
