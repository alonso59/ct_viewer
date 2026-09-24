"""Task manifest and task-run payloads (TASKS.md §Manifest, TSK-01..10; API-42..47)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TASK_ID_RE = r"^[a-z][a-z0-9_-]*(\.[a-z0-9_-]+)+$"
TaskKind = Literal["conversion", "analyzer", "features", "segmentation"]
TaskInput = Literal["items", "rows", "source"]
OutputType = Literal["images", "masks", "features", "metadata", "annotations"]
VOLUME_OUTPUTS: frozenset[str] = frozenset({"images", "masks"})
TaskRunStatus = Literal[
    "queued",
    "waiting_for_runner",
    "running",
    "completed",
    "completed_with_errors",
    "failed",
    "cancelled",
    "interrupted",
]
TERMINAL_TASK_RUN: frozenset[str] = frozenset(
    {"completed", "completed_with_errors", "failed", "cancelled", "interrupted"}
)
RESUMABLE_TASK_RUN: frozenset[str] = frozenset({"failed", "cancelled", "interrupted"})
ItemState = Literal["ok", "failed", "skipped"]


class RuntimeSpec(BaseModel):
    type: Literal["builtin", "external"]
    entry: str | None = None  # builtin: "module.path:function"
    command: list[str] | None = None  # external: argv, `{job_dir}` is substituted
    env_hint: str | None = None

    @model_validator(mode="after")
    def _shape(self) -> RuntimeSpec:
        if self.type == "builtin" and not (self.entry and ":" in self.entry):
            raise ValueError("builtin runtime needs entry 'module:function'")
        if self.type == "external" and not self.command:
            raise ValueError("external runtime needs a command")
        return self


class Resources(BaseModel):
    gpu: Literal["none", "optional", "required"] = "none"
    max_batch: int | None = Field(default=None, ge=1)
    seconds_per_item: float | None = Field(default=None, gt=0)


class SegRequirement(BaseModel):
    labels: list[str] = Field(default_factory=list)  # label names from the project label map


class Requires(BaseModel):
    modality: list[str] | None = None
    channels: int | None = Field(default=None, ge=1)
    seg: SegRequirement | None = None  # the task reads masks (TSK-03: seg_id + labels)


class TaskManifest(BaseModel):
    """`task.json` (TSK-01). Unknown keys are refused so typos surface as invalid manifests."""

    model_config = ConfigDict(extra="forbid")

    manifest: Literal[1] = 1
    id: str = Field(pattern=TASK_ID_RE)
    version: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = ""
    kind: TaskKind
    input: TaskInput
    outputs: list[OutputType] = Field(min_length=1)
    requires: Requires = Field(default_factory=lambda: Requires())
    settings_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    defaults: dict[str, Any] = Field(default_factory=dict)
    runtime: RuntimeSpec
    resources: Resources = Field(default_factory=lambda: Resources())
    # Segmentation tasks: `{"names": {"1": "kidney"}}` or `{"from": "dataset.json"}`.
    labels: dict[str, Any] | None = None
    # Hidden from the Tasks view (CI plugins such as segment.threshold, TST-14).
    test_only: bool = False
    # TSK-13: `workspace` tasks can also run without a project (API-62); `project` ones cannot.
    scope: Literal["project", "workspace"] = "project"


class TaskInfo(BaseModel):
    """API-42 row: a loaded manifest plus where it came from and whether it can run now."""

    manifest: TaskManifest
    source: Literal["builtin", "plugins_root"]
    manifest_hash: str
    # The first-party plugin that contributes this task (TSK-01, PLG-01).
    plugin: str | None = None
    available: bool = True
    unavailable_reason: str | None = None
    # External tasks: a fresh runner heartbeat lists this task (TSK-11).
    runner_online: bool | None = None
    # Radiomics keeps its richer schema behind API-30 (TSK-02, RAD-01).
    settings_schema_url: str | None = None


class InvalidManifest(BaseModel):
    path: str
    error: str


class RunnerInfo(BaseModel):
    runner_id: str
    tasks: list[str] = Field(default_factory=list)
    gpu: str | None = None
    pid: int | None = None
    at: str
    fresh: bool


class TaskList(BaseModel):
    tasks: list[TaskInfo]
    invalid: list[InvalidManifest]
    runners: list[RunnerInfo]


class SettingsIssue(BaseModel):
    loc: list[str | int]
    msg: str
    rule: str
    severity: Literal["error", "warning"] = "error"


class TaskValidateRequest(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)


class TaskValidateResult(BaseModel):
    ok: bool
    issues: list[SettingsIssue]
    settings: dict[str, Any] | None = None  # normalized (defaults applied)
    settings_hash: str | None = None


class TaskSelectionFilter(BaseModel):
    phase: list[str] | None = None
    side: list[Literal["L", "R", "-"]] | None = None
    var: dict[str, list[str]] | None = None  # categorical study variables (VAR-10)


class TaskSelection(BaseModel):
    """TSK-03: all active items / an Explorer filter / an explicit list; scope; seg + labels."""

    item_ids: list[str] | None = None
    filter: TaskSelectionFilter | None = None
    scope: Literal["complete", "voi"] | None = None
    seg_id: str | None = None  # default: `default_seg` (when the task reads masks)
    labels: list[int] = Field(default_factory=list)  # radiomics: one extraction per label
    # `input: source` tasks (the converter): a folder or file inside ALLOWED_DATA_ROOTS.
    source: str | None = None


class Suggestion(BaseModel):
    task_id: str
    reason: str


class PreflightRequest(BaseModel):
    selection: TaskSelection = Field(default_factory=lambda: TaskSelection())
    settings: dict[str, Any] = Field(default_factory=dict)


class PreflightResult(BaseModel):
    """TSK-04: items that aren't ready are skipped, never failed."""

    n_selected: int
    n_ready: int
    missing: dict[str, int]
    suggestions: list[Suggestion]
    derived_root_required: bool = False  # the task writes volumes and none is registered
    ready_item_ids: list[str] = Field(default_factory=list)


class TaskEstimate(BaseModel):
    """TSK-05."""

    n_units: int
    n_skipped: int
    seconds_per_item: float | None
    estimated_total_s: float | None
    output_bytes: int | None = None
    basis: Literal["sample", "manifest", "unknown"]
    sample_item_ids: list[str] = Field(default_factory=list)
    sample_errors: list[str] = Field(default_factory=list)
    detail: dict[str, Any] = Field(default_factory=dict)  # e.g. the converter's dry run (DCM-06)


class TaskRunRequest(BaseModel):
    task_id: str
    settings: dict[str, Any] = Field(default_factory=dict)
    selection: TaskSelection = Field(default_factory=lambda: TaskSelection())
    name: str | None = Field(default=None, max_length=200)


class TaskRunCounts(BaseModel):
    items: int = 0
    ok: int = 0
    failed: int = 0
    skipped: int = 0


class TaskRunInput(BaseModel):
    item_id: str
    image_fp: str | None = None
    seg_id: str | None = None
    mask_fp: str | None = None


class TaskRunOutput(BaseModel):
    """A registered output (TSK-09)."""

    kind: str  # mask | image | annotations | features | metadata | segmentation_set | import
    item_id: str | None = None
    ref: str | None = None  # DERIVED:… for volumes; project-relative path for tabular outputs
    seg_id: str | None = None
    sha256: str | None = None
    detail: str | None = None


class TaskRef(BaseModel):
    id: str
    version: str
    manifest_hash: str


class TaskRunSummary(BaseModel):
    run_id: str
    task: TaskRef
    name: str
    status: TaskRunStatus
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    reviewer: str | None = None
    job_id: str | None = None
    counts: TaskRunCounts = Field(default_factory=TaskRunCounts)
    error: str | None = None


class TaskRunRecord(TaskRunSummary):
    """`tasks/runs/{run_id}/run.json` (TSK-10, NFR-15)."""

    runtime: Literal["builtin", "external"]
    settings: dict[str, Any]
    settings_hash: str
    selection: TaskSelection
    item_ids: list[str] = Field(default_factory=list)
    inputs: list[TaskRunInput] = Field(default_factory=list)
    versions: dict[str, str] = Field(default_factory=dict)
    output_dir: str | None = None  # absolute, inside the project's derived root
    outputs: list[TaskRunOutput] = Field(default_factory=list)
    attempts: int = 0


class TaskRunProgress(BaseModel):
    done: int
    total: int
    eta_s: float | None = None


class TaskRunDetail(TaskRunRecord):
    progress: TaskRunProgress | None = None
    # radiomics.pyradiomics runs live in `radiomics/runs/` (RAD-13); details via API-34.
    detail_url: str | None = None


class TaskRunStarted(BaseModel):
    run_id: str
    job_id: str | None
    status: TaskRunStatus


class TaskItemError(BaseModel):
    item_id: str
    status: ItemState
    message: str = ""
