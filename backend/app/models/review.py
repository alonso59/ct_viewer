from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


ReviewAction = Literal["reclassify", "delete", "restore"]
PhaseDecision = Literal["NC", "CMP", "NP", "DELAY", "UNK"]
ReviewResultStatus = Literal["applied", "skipped", "failed"]
LEGACY_PHASE_DECISIONS = {
    "ART": "CMP",
    "ARTERIAL": "CMP",
    "VEN": "NP",
    "VENOUS": "NP",
    "EX": "DELAY",
    "EXC": "DELAY",
    "EXCRETORY": "DELAY",
    "UNKNOWN": "UNK",
    "UNDEFINED": "UNK",
}


class ReviewOperation(BaseModel):
    patient_id: str
    series_id: str
    action: ReviewAction
    target_phase: PhaseDecision | None = None

    @field_validator("target_phase", mode="before")
    @classmethod
    def normalize_target_phase(cls, value):
        if value is None:
            return None
        key = str(value).strip().upper().replace(" ", "").replace("_", "-")
        return LEGACY_PHASE_DECISIONS.get(key, key)

    @model_validator(mode="after")
    def validate_target_phase(self) -> "ReviewOperation":
        if self.action == "reclassify" and self.target_phase is None:
            raise ValueError("target_phase is required for reclassify action")
        if self.action in {"delete", "restore"} and self.target_phase is not None:
            raise ValueError("target_phase must be omitted for delete/restore actions")
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
    moved_files: list["ReviewMovedFile"] = Field(default_factory=list)
    metadata_updated: bool = False


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


class ReviewMovedFile(BaseModel):
    source: str
    destination: str


class ReviewDeleteDecision(BaseModel):
    decision_id: str
    applied_at: str
    patient_id: str
    series_id: str
    filename: str | None = None
    series_type: str | None = None
    moved_files: list[ReviewMovedFile] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)
