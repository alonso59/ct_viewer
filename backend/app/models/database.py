from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


CanonicalPhase = Literal["NC", "CMP", "NP", "DELAY", "UNK"]
PhaseStatus = Literal["normalized", "ambiguous", "missing"]
PathStatusValue = Literal["not_provided", "exists", "missing", "unreadable"]
Scope = Literal["complete", "voi"]


class RequiredColumnStatus(BaseModel):
    name: str
    present: bool
    alternatives: list[str] = Field(default_factory=list)


class PathStatus(BaseModel):
    raw: str | None = None
    resolved: str | None = None
    status: PathStatusValue = "not_provided"


class QCWarning(BaseModel):
    code: str
    message: str
    severity: Literal["info", "warning", "error"] = "warning"
    row_id: str | None = None
    scope: Scope | None = None
    path_field: str | None = None


class DatabaseValidationReport(BaseModel):
    dataset_id: str
    has_database: bool
    row_count: int = 0
    case_count: int = 0
    required_columns: list[RequiredColumnStatus] = Field(default_factory=list)
    missing_paths: list[QCWarning] = Field(default_factory=list)
    unreadable_files: list[QCWarning] = Field(default_factory=list)
    duplicate_row_identities: list[QCWarning] = Field(default_factory=list)
    duplicate_scope_combinations: list[QCWarning] = Field(default_factory=list)
    missing_seg: list[QCWarning] = Field(default_factory=list)
    missing_voi_image: list[QCWarning] = Field(default_factory=list)
    missing_voi_mask: list[QCWarning] = Field(default_factory=list)
    ambiguous_phase: list[QCWarning] = Field(default_factory=list)
    ambiguous_side: list[QCWarning] = Field(default_factory=list)
    warnings: list[QCWarning] = Field(default_factory=list)


class CaseSummary(BaseModel):
    case_id: str
    patient_id: str | None = None
    group: str | None = None
    available_phases: list[CanonicalPhase] = Field(default_factory=list)
    scan_count: int = 0
    seg_count: int = 0
    voi_image_count: int = 0
    voi_mask_count: int = 0
    voi_sides: list[str] = Field(default_factory=list)
    latest_curation_status: str | None = None
    warning_count: int = 0
    has_comments: bool = False


class CaseInventoryRow(BaseModel):
    row_id: str
    source_row_id: str | None = None
    case_id: str
    patient_id: str | None = None
    group: str | None = None
    raw_phase: str | None = None
    canonical_phase: CanonicalPhase
    phase_status: PhaseStatus
    scan_idx: str | None = None
    side: str | None = None
    scope_availability: dict[Scope, bool] = Field(default_factory=dict)
    nifti_path: PathStatus
    seg_path: PathStatus
    voi_image_path: PathStatus
    voi_mask_path: PathStatus
    has_seg: bool = False
    has_voi_image: bool = False
    has_voi_mask: bool = False
    qc_warnings: list[QCWarning] = Field(default_factory=list)
    latest_curation_status: str | None = None


class CaseDossier(BaseModel):
    case_id: str
    core: dict[str, Any] = Field(default_factory=dict)
    acquisition: dict[str, Any] = Field(default_factory=dict)
    segmentation_voi: dict[str, Any] = Field(default_factory=dict)
    preprocessing_qc: dict[str, Any] = Field(default_factory=dict)
    external_research: dict[str, Any] = Field(default_factory=dict)
    advanced_raw_fields: list[dict[str, Any]] = Field(default_factory=list)


class CaseLoadSource(BaseModel):
    dataset_id: str
    case_id: str
    row_id: str
    scope: Scope
    series_id: str
    image_path: str
    mask_path: str | None = None
    source_type: Literal["nifti", "voi_nifti", "voi_numpy"]
    spacing: list[float] | None = None
