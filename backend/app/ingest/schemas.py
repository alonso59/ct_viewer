"""Import / case / item payloads. Index records live in `models`."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.ingest.models import CaseSummary, IndexStatus, Item, PhaseInfo, QcWarning
from app.ingest.parsers import FileKind

DEFAULT_ALIAS = "DATA"


Adapter = Literal["metadata-v1", "nifti-files"]


class PreviewRequest(BaseModel):
    """`root` may be one file."""

    root: str
    detect: bool = True
    alias: str = DEFAULT_ALIAS
    adapter: Adapter | None = None  # None: metadata-v1, or nifti-files for one NIfTI file
    options: dict[str, Any] = Field(default_factory=dict)
    # "Add to project…": kept next to the project's other sources
    add: bool = False


class SourceInfo(BaseModel):
    """`sources/{import_id}/source.json`."""

    adapter: Adapter
    adapter_version: str
    options: dict[str, Any] = Field(default_factory=dict)
    detected_at: str


class InputFile(BaseModel):
    kind: FileKind
    name: str
    source: Literal["detected", "uploaded", "generated"]
    sha256: str
    rows: int


class ImportCounts(BaseModel):
    scan_rows: int = 0
    voi_rows: int = 0
    cases: int = 0  # cases with a row that is not excluded upstream
    excluded_upstream: int = 0  # scan rows excluded upstream
    excluded_cases: int = 0  # cases whose every row is excluded upstream (not in `cases`)


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


class ParsedFile(BaseModel):
    """`nifti-files` preview row."""

    file: str
    case_id: str
    scan_idx: str
    modality: str | None = None
    phase: str | None = None
    channel: str | None = None
    mask: str | None = None
    matched: bool


class ImportPreview(BaseModel):
    preview_id: str
    root: str
    alias: str
    files: list[InputFile]
    counts: ImportCounts
    errors: list[PreviewError]
    n_errors: int
    field_mapping: FieldMapping
    adapter: Adapter = "metadata-v1"
    options: dict[str, Any] = Field(default_factory=dict)
    # nifti-files: parsed columns of the first 50 files, names the pattern missed, masks
    # without an image, ignored extensions
    sample: list[ParsedFile] = Field(default_factory=list)
    unmatched: list[str] = Field(default_factory=list)
    orphan_masks: list[str] = Field(default_factory=list)
    ignored: dict[str, int] = Field(default_factory=dict)
    source_key: str | None = None  # None: `{adapter}:{alias}`


class CommitRequest(BaseModel):
    preview_id: str


class CommitResult(BaseModel):
    job_id: str
    import_id: str


class ImportRecord(BaseModel):
    """One line of `sources/imports.jsonl`."""

    import_id: str
    at: str
    alias: str
    root: str
    files: list[InputFile]
    counts: ImportCounts
    adapter: Adapter = "metadata-v1"
    source_key: str | None = None

    @property
    def key(self) -> str:
        """The index keeps the latest snapshot per key."""
        return self.source_key or f"{self.adapter}:{self.alias}"


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
    image_path: str | None = None  # absolute; null if unresolvable
    mask_path: str | None = None


class ItemDetail(Item):
    advanced: ItemAdvanced
    warnings: list[QcWarning] = Field(default_factory=list)
