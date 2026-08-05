from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


MetadataSyncKind = Literal[
    "phase_changes",
    "delete_changes",
    "restore_changes",
    "already_consolidated",
    "conflicts",
    "noop",
]


class MetadataSyncChange(BaseModel):
    kind: MetadataSyncKind
    target: Literal["metadata", "voi_catalog"] = "metadata"
    filename: str
    case_id: str | None = None
    scan_idx: str | None = None
    side: str | None = None
    row_index: int | None = None
    message: str
    current_phase: str | None = None
    target_phase: str | None = None
    current_relative_path: str | None = None
    target_relative_path: str | None = None


class MetadataSyncSummary(BaseModel):
    phase_changes: int = 0
    delete_changes: int = 0
    restore_changes: int = 0
    already_consolidated: int = 0
    conflicts: int = 0
    noop: int = 0
    voi_catalog_changes: int = 0
    total_rows: int = 0


class MetadataSyncPreviewResponse(BaseModel):
    dataset_id: str
    summary: MetadataSyncSummary
    changes: list[MetadataSyncChange] = Field(default_factory=list)


class MetadataSyncApplyResponse(MetadataSyncPreviewResponse):
    batch_id: str
    applied_at: str
    metadata_updated: bool = False
    phase_json_neutralized: bool = False
