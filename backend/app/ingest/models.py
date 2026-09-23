"""Index records (DATA_MODEL.md §Item, §Case summary; INPUT_METADATA.md §QC warning codes)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.ids import Scope, Side
from app.imaging.header import VolumeFormat
from app.ingest.codes import QcCode, Severity

Phase = str  # a code from the project's phase vocabulary (PRJ-12), or a raw value (`none`)
PhaseSource = Literal[
    "phase.json", "curated_phase", "canonical_phase", "phase", "phase_guess", "catalog", "none"
]
ItemStatus = Literal["active", "excluded_upstream", "missing"]
IndexState = Literal["empty", "running", "ready", "failed", "cancelled", "interrupted"]


class PhaseInfo(BaseModel):
    canonical: Phase
    raw: str | None = None
    source: PhaseSource = "none"


class VolumeRef(BaseModel):
    ref: str  # ALIAS:rel (PRJ-04)
    format: VolumeFormat = "nifti"
    fp: str | None = None  # quick fingerprint; None when missing/unreadable


class Geometry(BaseModel):
    shape: list[int]
    spacing: list[float]
    dtype: str
    orientation: str | None = None


class Item(BaseModel):
    item_id: str
    case_id: str
    scan_idx: str
    scope: Scope
    side: Side
    patient_id: str | None = None
    phase: PhaseInfo
    image: VolumeRef | None = None
    mask: VolumeRef | None = None
    geometry: Geometry | None = None
    labels_present: list[int] = Field(default_factory=list)
    status: ItemStatus = "active"
    warning_codes: list[QcCode] = Field(default_factory=list)
    import_id: str
    extra: dict[str, Any] = Field(default_factory=dict)


class QcWarning(BaseModel):
    code: QcCode
    severity: Severity
    item_id: str | None = None
    case_id: str | None = None
    field: str | None = None
    path_ref: str | None = None
    message: str
    detected_at: str


class CaseSummary(BaseModel):
    case_id: str
    patient_id: str | None = None
    phases: list[Phase] = Field(default_factory=list)
    n_scans: int = 0
    n_items: int = 0
    has_seg: bool = False
    has_voi_L: bool = False  # DATA_MODEL field names
    has_voi_R: bool = False
    n_warnings: int = 0
    curation_status: str = "not_reviewed"  # CUR-08 rollup; filled by curation (lane P4)
    last_reviewed_at: str | None = None
    # Best item for the case thumbnail (API-26): active `complete` item, by phase priority.
    thumb_item_id: str | None = None
    # Case-level visible variables (VAR-02/10) for explorer columns and colour; query-time join.
    variables: dict[str, float | str | None] = Field(default_factory=dict)


class IndexStatus(BaseModel):
    """`index/status.json`: persisted index job state (BE-06)."""

    state: IndexState = "empty"
    import_id: str | None = None
    job_id: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    n_items: int = 0
    n_warnings: int = 0
    error: str | None = None
