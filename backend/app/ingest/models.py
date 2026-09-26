"""Index records (DATA_MODEL.md §Item, §Case summary; INPUT_METADATA.md §QC warning codes)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.core.ids import Scope, Side
from app.curation.models import ReviewState, RollupStatus
from app.imaging.header import VolumeFormat
from app.ingest.codes import QcCode, Severity

Phase = str  # a code from the project's phase vocabulary (PRJ-12), or a raw value (`none`)
# "phase.json" | "curated_phase" | "canonical_phase" | "phase" | "analyzer:{run_id}" (ANZ-04)
# | "phase_guess" | "catalog" | "none"; "manual" = a native phase selection joined on read (PHS-03)
PhaseSource = str
ItemStatus = Literal["active", "excluded_upstream", "missing"]
IndexState = Literal["empty", "running", "ready", "failed", "cancelled", "interrupted"]


class PhaseInfo(BaseModel):
    canonical: Phase
    raw: str | None = None
    source: PhaseSource = "none"
    # Set only on read when a native selection overrides the index (PHS-03): the index-time
    # resolution it replaces. Never stored in the index.
    resolved: PhaseInfo | None = None


class VolumeRef(BaseModel):
    ref: str  # ALIAS:rel (PRJ-04)
    format: VolumeFormat = "nifti"
    fp: str | None = None  # quick fingerprint; None when missing/unreadable
    # Full SHA-256 (IMP-09) from `index/hashes.json`, attached on load while `fp` matches.
    sha256: str | None = None


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
    # Input `modality` (e.g. CT, MR); None when absent. Also kept in `extra` for variables.
    modality: str | None = None
    phase: PhaseInfo
    image: VolumeRef | None = None
    # seg_id → mask (ADR-0015); `imported` holds the masks found at import.
    masks: dict[str, VolumeRef] = Field(default_factory=dict)
    # Deprecated for P7b (ADR-0015 §6): `masks[default_seg]`, filled on load, never stored.
    mask: VolumeRef | None = None
    geometry: Geometry | None = None
    labels_present: list[int] = Field(default_factory=list)
    status: ItemStatus = "active"
    warning_codes: list[QcCode] = Field(default_factory=list)
    import_id: str
    extra: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _v1_mask(cls, raw: Any) -> Any:
        """A format_version 1 index record: `mask` → `masks.imported` (PRJ-11)."""
        if isinstance(raw, dict) and "masks" not in raw and raw.get("mask") is not None:
            raw = {**raw, "masks": {"imported": raw["mask"]}}
        return raw

    def mask_for(self, seg_id: str | None) -> VolumeRef | None:
        """The mask of one set; None = the deprecated default (`mask`)."""
        return self.mask if seg_id is None else self.masks.get(seg_id)

    def volumes(self) -> list[VolumeRef]:
        """Image and every mask (hashing, relink)."""
        return [v for v in (self.image, *self.masks.values()) if v is not None]


class QcWarning(BaseModel):
    code: QcCode
    severity: Severity
    item_id: str | None = None
    case_id: str | None = None
    seg_id: str | None = None  # mask warnings: the segmentation set (ADR-0015)
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
    curation_status: RollupStatus = "not_reviewed"  # CUR-08 rollup; query-time join
    # CUR-08: reviewed = every active item has a decision; progress counts only those
    review_state: ReviewState = "not_reviewed"
    n_items_reviewed: int = 0  # active items with a decision
    n_items_active: int = 0
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
    n_items: int = 0  # items not excluded upstream (AUD-A2-08)
    n_excluded_upstream: int = 0
    n_warnings: int = 0
    error: str | None = None
