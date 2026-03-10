from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


ReviewAction = Literal["reclassify", "delete"]
PhaseDecision = Literal["NC", "ART", "VEN"]
ReviewResultStatus = Literal["applied", "skipped", "failed"]


class ReviewOperation(BaseModel):
    patient_id: str
    series_id: str
    action: ReviewAction
    target_phase: PhaseDecision | None = None

    @model_validator(mode="after")
    def validate_target_phase(self) -> "ReviewOperation":
        if self.action == "reclassify" and self.target_phase is None:
            raise ValueError("target_phase is required for reclassify action")
        if self.action == "delete" and self.target_phase is not None:
            raise ValueError("target_phase must be omitted for delete action")
        return self


class ReviewApplyRequest(BaseModel):
    operations: list[ReviewOperation] = Field(default_factory=list)


class ReviewApplyResult(BaseModel):
    patient_id: str
    series_id: str
    action: ReviewAction
    target_phase: PhaseDecision | None = None
    status: ReviewResultStatus
    message: str
    moved_files: list[str] = Field(default_factory=list)
    manifest_updated: bool = False


class ReviewApplySummary(BaseModel):
    requested: int = 0
    applied: int = 0
    skipped: int = 0
    failed: int = 0


class ReviewApplyResponse(BaseModel):
    batch_id: str
    applied_at: str
    summary: ReviewApplySummary
    results: list[ReviewApplyResult] = Field(default_factory=list)
