from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


DatasetKind = Literal[
    "canonical",
    "converter_output",
    "legacy",
    "nifti_collection",
    "voi_collection",
    "incomplete",
    "unsupported",
]
InspectionSeverity = Literal["info", "warning", "error"]


class RecentDataset(BaseModel):
    dataset_path: str
    display_name: str
    dataset_key: str
    dataset_kind: DatasetKind | None = None
    last_opened_at: str


class WorkspaceMarkers(BaseModel):
    database_csv: bool = False
    metadata_jsonl: bool = False
    phase_json: bool = False
    voi_catalog_jsonl: bool = False
    nifti: bool = False
    seg: bool = False
    voi: bool = False


class WorkspaceInspectionSummary(BaseModel):
    case_count: int = 0
    volume_count: int = 0
    nifti_count: int = 0
    voi_image_count: int = 0
    segmentation_count: int = 0
    voi_mask_count: int = 0
    warning_count: int = 0
    warnings_truncated: bool = False


class WorkspaceStateInspection(BaseModel):
    path: str
    exists: bool
    writable: bool


class WorkspaceInspectionWarning(BaseModel):
    code: str
    message: str
    severity: InspectionSeverity = "warning"


class WorkspaceInspection(BaseModel):
    valid: bool
    dataset_path: str
    dataset_id: str
    dataset_key: str
    dataset_kind: DatasetKind
    markers: WorkspaceMarkers
    summary: WorkspaceInspectionSummary
    state: WorkspaceStateInspection
    warnings: list[WorkspaceInspectionWarning] = Field(default_factory=list)


class WorkspaceStatus(BaseModel):
    configured: bool
    dataset_id: str | None = None
    dataset_key: str | None = None
    dataset_kind: DatasetKind | None = None
    dataset_path: str | None = None
    workspace_dir: str | None = None
    recent_datasets: list[RecentDataset] = Field(default_factory=list)


class WorkspaceUpdateRequest(BaseModel):
    dataset_path: str
