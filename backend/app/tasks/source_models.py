"""Request and record models of a source operation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.reviewer import Origin
from app.ingest.schemas import ImportPreview
from app.jobs.types import JobInfo
from app.tasks.models import (
    TaskEstimate,
    TaskRunDetail,
    TaskRunStatus,
)
from app.tasks.workspace_runs import (
    WorkspaceRun,
)

if TYPE_CHECKING:
    pass


class SourceImportContext(BaseModel):
    """Import draft choices; Preview remains responsible for validating adapter options."""

    model_config = ConfigDict(extra="forbid")
    alias: str = Field(default="DATA", pattern=r"^[A-Z][A-Z0-9_]{0,15}$")
    adapter: str | None = Field(default=None, max_length=64)
    add: bool = False
    options: dict[str, Any] = Field(default_factory=dict)
    reconstruct: bool = False
    anonymize: bool = False
    step: Literal["detect", "previewing", "preview", "index"] = "detect"
    preview_id: str | None = None
    import_id: str | None = None
    job_id: str | None = None


class SourceOperationStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=8, max_length=128)
    project_id: str | None = None
    purpose: Literal["discover", "open", "convert"] = "convert"
    prepare_plan: bool = False
    import_context: SourceImportContext | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
    name: str | None = Field(default=None, max_length=200)
    destination: str | None = Field(default=None, min_length=1)  # parent of a workspace dataset
    folders: list[str] | None = Field(default=None, min_length=1, max_length=5000)


class SourceOperationControl(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    expected_attempt: int = Field(ge=1)
    expected_run_attempt: int | None = Field(default=None, ge=0)


class SourceImportCommit(SourceOperationControl):
    allow_incomplete: bool | None = None  # import a converter dataset that is not complete (DCM-34)


class SourceOperationEstimate(SourceOperationControl):
    settings: dict[str, Any] = Field(default_factory=dict)
    name: str | None = Field(default=None, max_length=200)
    destination: str | None = Field(default=None, min_length=1)


class SourceOperationConvert(SourceOperationControl):
    inventory_generation: str = Field(min_length=1)
    # project datasets: add series converted by the current readers next to committed series
    # from other reader versions (DCM-31)
    allow_mixed_versions: bool | None = None
    plan_attempt: int = Field(ge=1)
    name: str | None = Field(default=None, max_length=200)
    destination: str | None = Field(default=None, min_length=1)


class SourceImportUpdate(SourceOperationControl):
    project_id: str
    alias: str = Field(default="DATA", pattern=r"^[A-Z][A-Z0-9_]{0,15}$")
    adapter: str | None = Field(default=None, max_length=64)
    add: bool = False
    options: dict[str, Any] = Field(default_factory=dict)
    reconstruct: bool = False
    anonymize: bool = False


class PendingSourceControl(BaseModel):
    action: Literal["cancel", "resume", "retry_failed"]
    request: SourceOperationControl
    request_id: str
    run_attempt: int


class SourceOperation(BaseModel):
    import_context: SourceImportContext | None = None
    import_preview: ImportPreview | None = None
    import_job: JobInfo | None = None
    version: Literal[1] = 1
    operation_id: str
    source: str
    project_id: str | None
    purpose: Literal["discover", "open", "convert"]
    reviewer: str | None = None
    origin: Origin | None = None
    status: TaskRunStatus = "queued"
    stage: str = "discovering"
    revision: int = 0
    attempt: int = 1
    job_id: str | None = None
    created_at: str
    updated_at: str
    request_hash: str
    cleanup_verified: bool = True
    progress: dict[str, int] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    control: dict[str, Any] = Field(default_factory=dict)
    pending_control: PendingSourceControl | None = None
    work_kind: Literal["inventory", "estimate", "convert"] = "inventory"
    settings: dict[str, Any] = Field(default_factory=dict)
    estimate: TaskEstimate | None = None
    plan_attempt: int | None = None
    plan_total: int = 0
    progress_stage: str | None = None
    discovery_eta: dict[str, Any] | None = None
    error: str | None = None
    problem: dict[str, Any] | None = None
    conversion_run_id: str | None = None
    conversion_request: dict[str, Any] = Field(default_factory=dict)
    conversion_run: TaskRunDetail | WorkspaceRun | None = None
    phase_run: TaskRunDetail | WorkspaceRun | None = None
    prepare_plan: bool = False
    dataset_name: str | None = None
    dataset_destination: str | None = None
    folders: list[str] | None = None
