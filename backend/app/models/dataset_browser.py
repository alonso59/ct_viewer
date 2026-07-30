from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.models.workspace import WorkspaceStatus


BrowserEntryType = Literal["directory", "file"]
ValidationSeverity = Literal["success", "warning", "error"]


class DatasetBrowserRoot(BaseModel):
    label: str
    path: str
    source: str
    exists: bool
    readable: bool


class DatasetBrowserEntry(BaseModel):
    name: str
    path: str
    type: BrowserEntryType
    is_database_csv: bool = False
    maybe_has_dataset_structure: bool = False
    readable: bool = False


class DatasetBrowserRootsResponse(BaseModel):
    roots: list[DatasetBrowserRoot] = Field(default_factory=list)


class DatasetBrowserListResponse(BaseModel):
    path: str
    parent_path: str | None = None
    entries: list[DatasetBrowserEntry] = Field(default_factory=list)


class WorkspaceSelectionValidationRequest(BaseModel):
    dataset_folder_path: str | None = None
    database_csv_path: str | None = None


class SelectionValidationMessage(BaseModel):
    code: str
    message: str
    severity: ValidationSeverity
    path: str | None = None


class WorkspaceSelectionSummary(BaseModel):
    dataset_id: str | None = None
    dataset_root: str | None = None
    database_csv_path: str | None = None
    has_database: bool = False
    row_count: int = 0
    case_count: int = 0
    sampled_rows: int = 0
    sampled_referenced_files: int = 0
    sampled_existing_files: int = 0
    has_nifti: bool = False
    has_seg: bool = False
    has_voi: bool = False
    has_manifest: bool = False


class WorkspaceSelectionValidationResponse(BaseModel):
    valid: bool
    activated: bool = False
    requires_dataset_root: bool = False
    summary: WorkspaceSelectionSummary = Field(default_factory=WorkspaceSelectionSummary)
    successes: list[SelectionValidationMessage] = Field(default_factory=list)
    warnings: list[SelectionValidationMessage] = Field(default_factory=list)
    errors: list[SelectionValidationMessage] = Field(default_factory=list)
    workspace: WorkspaceStatus | None = None
