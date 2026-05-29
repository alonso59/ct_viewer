from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


CurationTarget = Literal[
    "SEG",
    "tumor_mask",
    "kidney_mask",
    "cyst_mask",
    "VOI_mask",
    "phase_issue",
    "side_laterality_issue",
]
CurationStatus = Literal[
    "not_reviewed",
    "accepted",
    "needs_minor_correction",
    "needs_major_correction",
    "rejected",
    "missing",
    "wrong_phase_suspected",
    "wrong_side_suspected",
    "cannot_assess",
]
CurationPriority = Literal["low", "medium", "high"]
CurationScope = Literal["complete", "voi"]


CURATION_FIELDS = [
    "review_id",
    "dataset_id",
    "case_id",
    "patient_id",
    "source_row_id",
    "row_id",
    "scan_idx",
    "raw_phase",
    "canonical_phase",
    "proposed_phase",
    "side",
    "scope",
    "target",
    "status",
    "priority",
    "comment",
    "reviewer",
    "reviewed_at",
    "nifti_path",
    "seg_path",
    "voi_image_path",
    "voi_mask_path",
]


class CurationDecisionRequest(BaseModel):
    case_id: str
    row_id: str | None = None
    scope: CurationScope = "complete"
    target: CurationTarget
    status: CurationStatus
    priority: CurationPriority = "medium"
    comment: str = ""
    proposed_phase: str | None = None
    reviewer: str = ""
    add_to_queue: bool = False


class CurationDecision(BaseModel):
    review_id: str
    dataset_id: str
    case_id: str
    patient_id: str | None = None
    source_row_id: str | None = None
    row_id: str | None = None
    scan_idx: str | None = None
    raw_phase: str | None = None
    canonical_phase: str | None = None
    proposed_phase: str | None = None
    side: str | None = None
    scope: CurationScope
    target: CurationTarget
    status: CurationStatus
    priority: CurationPriority
    comment: str = ""
    reviewer: str = ""
    reviewed_at: str
    nifti_path: str | None = None
    seg_path: str | None = None
    voi_image_path: str | None = None
    voi_mask_path: str | None = None


class CorrectionQueueResponse(BaseModel):
    dataset_id: str
    items: list[CurationDecision] = Field(default_factory=list)


class PhaseCorrectionRequest(BaseModel):
    case_id: str
    scan_idx: str | None = None
    proposed_phase: str
    comment: str = ""
    reviewer: str = ""
    add_to_queue: bool = True


class PhaseCorrectionResponse(BaseModel):
    case_id: str
    scan_idx: str | None
    proposed_phase: str
    total_rows: int
    complete_rows: int
    voi_rows: int
    decisions: list[CurationDecision] = Field(default_factory=list)
